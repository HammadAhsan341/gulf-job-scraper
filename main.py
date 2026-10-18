"""
Bulk pipeline runner for all permitted roles:
Scraping -> Enrichment/Cleaning/Skill extraction -> Optional vetting -> DB upsert.

Run this to execute the end-to-end scout stack in one go.
"""

import os
import sys
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import contextmanager

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.state import AgentState
from pipeline.enricher_node import job_enricher_node
from langchain_core.messages import HumanMessage
from core.settings import get_settings
from services.job_record import incoming_improves_stored, merge_incoming_over_stored
from services.supabase import get_supabase_service
from scraper.listing_persist import is_persistable_job, prepare_job_for_persist
from services.cache_refresh import refresh_jobs_cache
from scraper.spider import JobScraperSpider

PERSIST_BATCH_SIZE = 100


def _batched(items, batch_size):
    size = max(1, int(batch_size or 1))
    for i in range(0, len(items), size):
        yield items[i:i + size]


@contextmanager
def _suppress_scrapling_logs():
    """Filter noisy Scrapling [INFO]/[ERROR] lines from stdout/stderr."""
    class _StreamFilter:
        def __init__(self, stream):
            self.stream = stream

        def write(self, data):
            if "] INFO:" in data or "] ERROR:" in data:
                return
            try:
                self.stream.write(data)
            except UnicodeEncodeError:
                self.stream.write(data.encode("ascii", errors="ignore").decode("ascii"))

        def flush(self):
            self.stream.flush()

    original_out = sys.stdout
    original_err = sys.stderr
    sys.stdout = _StreamFilter(original_out)
    sys.stderr = _StreamFilter(original_err)
    try:
        yield
    finally:
        sys.stdout = original_out
        sys.stderr = original_err


class _TotalsAccumulator:
    """Thread-safe counters for pipeline summary."""

    def __init__(self):
        self._lock = threading.Lock()
        self.scraped = 0
        self.enriched = 0
        self.db_upserts = 0
        self.failed_roles: list = []

    def add_scraped(self, n: int):
        with self._lock:
            self.scraped += n

    def add_enriched(self, n: int):
        with self._lock:
            self.enriched += n

    def add_db_upserts(self, n: int):
        with self._lock:
            self.db_upserts += n

    def add_failed_role(self, role: str):
        with self._lock:
            self.failed_roles.append(role)


def _persist_scraped_jobs(raw_jobs, supabase, totals, batch_size, state):
    """Dedup, enrich, and upsert one board's jobs immediately."""
    if not raw_jobs:
        print("   Raw jobs: 0")
        return 0

    totals.add_scraped(len(raw_jobs))
    print(f"   Raw jobs: {len(raw_jobs)}")

    job_ids = [job.get("job_id") for job in raw_jobs if job.get("job_id")]
    # Both lookups raise on failure. A partial answer would make stored jobs
    # look new, and the upsert would overwrite their full JDs with listing cards.
    stored_by_id = supabase.get_jobs_by_ids(job_ids)
    processed_ids = supabase.get_processed_ids(list(stored_by_id))

    new_jobs = []
    refill_count = 0
    duplicate_count = 0
    unchanged_ids = []
    for job in raw_jobs:
        job_id = job.get("job_id")
        stored = stored_by_id.get(job_id) if job_id else None
        # processed_jobs alone is not enough: deleting jobs rows leaves those
        # IDs marked, and the next scrape would skip forever with an empty table.
        already = stored is not None and job_id in processed_ids
        if not already:
            board = (job.get("board") or "").lower()
            if not is_persistable_job(job, board):
                print(f"   Skipping {board} card without usable text: {job.get('title')}")
                continue
            job = prepare_job_for_persist(job, board)
            # A stored row without a processed mark still holds real data:
            # merge over it rather than replacing it.
            new_jobs.append(merge_incoming_over_stored(job, stored) if stored else job)
        elif incoming_improves_stored(job, stored):
            new_jobs.append(merge_incoming_over_stored(job, stored))
            refill_count += 1
        else:
            duplicate_count += 1
            unchanged_ids.append(job_id)

    print(f"   New jobs: {len(new_jobs) - refill_count}")
    print(f"   Backfilled missing fields: {refill_count}")
    print(f"   Duplicates filtered: {duplicate_count}")

    # Seen again: keeps live postings out of the stale-job cleanup.
    supabase.touch_jobs(unchanged_ids)

    if not new_jobs:
        return 0

    enrich_input = dict(state)
    enrich_input["raw_job_list"] = new_jobs
    enrich_input["scraping_status"] = "completed"
    enrich_result = job_enricher_node(enrich_input)
    if enrich_result.get("error"):
        # Do not upsert and mark processed half-enriched rows: they would never
        # be retried. Raising lets the caller requeue the batch.
        raise RuntimeError(f"enrichment failed: {enrich_result['error']}")
    enriched_jobs = enrich_result.get("raw_job_list", new_jobs)
    totals.add_enriched(len(enriched_jobs))
    print(f"   Enriched jobs: {len(enriched_jobs)}")

    affected = 0
    for batch in _batched(enriched_jobs, batch_size):
        written = int(supabase.bulk_insert_jobs(batch) or 0)
        affected += written
        if written:
            supabase.mark_jobs_processed([job.get("job_id") for job in batch])
        print(f"   DB upsert batch: {written} jobs")
    totals.add_db_upserts(affected)
    print(f"   DB upserts: {affected}")
    return affected


# LinkedIn remote is worldwide. Indeed remote stays on each country's host.
REMOTE_CAPABLE_BOARDS = ("linkedin", "indeed")


def _configured_countries(settings):
    from core.markets import GCC_COUNTRY_CODES

    codes = list(getattr(settings, "job_scraping_countries", None) or [])
    return codes or list(GCC_COUNTRY_CODES)


def _active_boards(settings):
    from core.settings import DISABLED_BOARDS

    return [
        board
        for board in settings.job_scraping_boards
        if (board or "").strip().lower() not in DISABLED_BOARDS
    ]


def _role_searches(role, settings):
    """(board, location) pairs: country-wide, then each major city, then remote.

    Rozee and Mustakbil are dropped. LinkedIn gets one worldwide remote pass.
    Indeed gets a remote pass on each configured country's host.
    """
    from core.markets import remote_location_label, search_location_labels

    boards = _active_boards(settings)
    countries = _configured_countries(settings)
    include_cities = bool(getattr(settings, "job_scraping_include_cities", True))
    locations = search_location_labels(countries, include_cities=include_cities)
    searches = [(board, location) for location in locations for board in boards]
    remote_roles = {r.strip().lower() for r in settings.remote_roles}
    if role.strip().lower() in remote_roles:
        if "indeed" in boards:
            searches += [("indeed", remote_location_label(code)) for code in countries]
        if "linkedin" in boards:
            searches.append(("linkedin", "Remote"))
    return searches


def _run_budget_deadline(settings):
    """Monotonic deadline for this process, or None when the run is unlimited."""
    budget = float(getattr(settings, "job_scraping_run_budget_seconds", 0) or 0)
    if budget <= 0:
        return None
    return time.monotonic() + budget


def _budget_reached(deadline) -> bool:
    return deadline is not None and time.monotonic() >= deadline


def _process_single_role(
    role, index, total, settings, supabase, totals,
    batch_size=PERSIST_BATCH_SIZE, deadline=None,
):
    """
    Process one role board-by-board so a hang on LinkedIn cannot delay
    Bayt, GulfTalent, Naukrigulf, or Indeed writes.
    Returns True on success, False on failure.
    """
    print(f"\n[{index}/{total}] Role: {role}")
    print("-" * 60)

    state: AgentState = {
        "messages": [HumanMessage(content=f"Find {role} jobs")],
        "user_id": "bulk_scraper_admin",
        "search_query": role,
        "raw_job_list": [],
        "scraping_status": "pending",
        "current_page": 1,
        "error": None,
        "retry_count": 0,
    }

    failed_boards = []
    searches = _role_searches(role, settings)
    try:
        spider = JobScraperSpider()
        for board, location in searches:
            if _budget_reached(deadline):
                print(f"   Hour budget reached; leaving {role} before {board}.")
                break
            print(f"   Board: {board} ({location})")
            try:
                buffer = []
                queued = set()

                def _queue_jobs(raw_jobs, _board=board):
                    for job in raw_jobs or []:
                        job_id = job.get("job_id")
                        desc = (job.get("description") or "").strip()
                        board_name = (job.get("board") or _board or "").lower()
                        if not is_persistable_job(job, board_name):
                            continue
                        job = prepare_job_for_persist(job, board_name)
                        job_id = job.get("job_id")
                        desc = (job.get("description") or "").strip()
                        key = (job_id, len(desc))
                        if not job_id or key in queued:
                            continue
                        queued.add(key)
                        buffer.append(job)

                def _persist_chunk(chunk, label):
                    print(f"   Persisting {label} ({len(chunk)} jobs)")
                    try:
                        _persist_scraped_jobs(chunk, supabase, totals, batch_size, state)
                    except Exception:
                        # The keys are already in `queued`, so a dropped chunk
                        # would never be offered again: put it back for the
                        # next flush and let the caller see the failure.
                        buffer[:0] = chunk
                        raise

                def persist(raw_jobs, _board=board, flush=False):
                    _queue_jobs(raw_jobs, _board)
                    while len(buffer) >= batch_size:
                        chunk = buffer[:batch_size]
                        del buffer[:batch_size]
                        _persist_chunk(chunk, f"{_board} batch")
                    if flush and buffer:
                        leftover = list(buffer)
                        buffer.clear()
                        _persist_chunk(leftover, f"{_board} leftover")

                raw_jobs = spider.scrape_board(
                    board=board,
                    query=role,
                    location=location,
                    max_pages=settings.job_scraping_max_pages_per_board,
                    max_jobs=settings.job_scraping_max_jobs_per_board,
                    on_jobs=persist,
                )
                persist(raw_jobs, flush=True)
            except Exception as board_exc:
                print(f"   Board {board} ({location}) failed: {board_exc}")
                failed_boards.append(f"{board}/{location}")
                continue
        if failed_boards and len(failed_boards) == len(searches):
            # Every board failed: count the role as failed so the retry pass
            # and the summary see it (previously this path always returned True).
            raise RuntimeError(f"all boards failed: {', '.join(failed_boards)}")
        return True

    except Exception as exc:
        totals.add_failed_role(role)
        print(f"   Role failed: {exc}")
        return False


def run_bulk_pipeline():
    """Run scrape + enrichment for all permitted roles and upsert in batches."""
    settings = get_settings()
    roles = settings.permitted_roles
    batch_size = PERSIST_BATCH_SIZE
    supabase = get_supabase_service()
    max_workers = settings.job_scraping_workers

    # Pre-load the enricher singleton before threads start (avoids lazy-init race)
    from pipeline.enricher import get_enricher
    get_enricher()

    countries = _configured_countries(settings)
    supabase.delete_stale_jobs(
        days=settings.job_stale_after_days,
        market=getattr(settings, "job_scraping_market", None) or "gulf",
        country_code=countries[0] if len(countries) == 1 else None,
    )
    clearer = getattr(supabase, "clear_orphan_processed_jobs", None)
    if callable(clearer):
        clearer()

    deadline = _run_budget_deadline(settings)
    budget = float(getattr(settings, "job_scraping_run_budget_seconds", 0) or 0)

    print("\n" + "=" * 78)
    print(
        f"RUNNING BULK PIPELINE FOR {len(roles)} ROLES "
        f"({max_workers} worker(s), "
        f"max {settings.job_scraping_max_concurrent_fetches} fetches/board)"
    )
    if budget > 0:
        print(f"Run budget: {budget:.0f}s (stop and sync when it is used)")
    print("=" * 78 + "\n")

    totals = _TotalsAccumulator()

    def _submit(executor, futures, idx, role, role_total):
        futures[executor.submit(
            _process_single_role,
            role, idx, role_total,
            settings, supabase, totals, batch_size, deadline,
        )] = role

    # Main pass. Workers stay capped, and a budget stops new roles so the
    # hourly job can exit and sync instead of running until GitHub kills it.
    pending = list(enumerate(roles, 1))
    if max_workers > 1:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            while pending or futures:
                while pending and len(futures) < max_workers:
                    if _budget_reached(deadline):
                        print(
                            f"Hour budget reached; {len(pending)} roles left "
                            "for the next run."
                        )
                        pending.clear()
                        break
                    idx, role = pending.pop(0)
                    _submit(executor, futures, idx, role, len(roles))
                if not futures:
                    break
                done, _ = wait(futures, return_when=FIRST_COMPLETED)
                for future in done:
                    role = futures.pop(future)
                    try:
                        future.result()
                    except Exception as exc:
                        print(f"   Unexpected worker error for '{role}': {exc}")
                        totals.add_failed_role(role)
    else:
        for idx, role in pending:
            if _budget_reached(deadline):
                print(f"Hour budget reached; stopping before role {idx}.")
                break
            _process_single_role(
                role, idx, len(roles),
                settings, supabase, totals, batch_size, deadline,
            )

    # Retry after a cooldown so a burst of blocks is not immediately retried.
    # Skip it once the hour is used up; the workflow starts a fresh pass.
    failed = totals.failed_roles[:]
    if failed and not _budget_reached(deadline):
        backoff = max(0.0, settings.job_scraping_retry_backoff_seconds)
        print("\n" + "=" * 78)
        print(
            f"RETRYING {len(failed)} FAILED ROLES (sequential, "
            f"{backoff:.0f}s cooldown first)"
        )
        print("=" * 78 + "\n")
        if backoff:
            time.sleep(backoff)

        totals.failed_roles.clear()

        for idx, role in enumerate(failed, 1):
            if _budget_reached(deadline):
                print(f"Hour budget reached; not retrying {role}.")
                break
            _process_single_role(
                role, idx, len(failed),
                settings, supabase, totals, batch_size, deadline,
            )

    # Summary
    print("\n" + "=" * 78)
    print("BULK PIPELINE SUMMARY")
    print(f"Roles processed: {len(roles)}")
    print(f"Roles failed (after retry): {len(totals.failed_roles)}")
    if totals.failed_roles:
        print(f"Failed roles: {', '.join(totals.failed_roles)}")
    print(f"Jobs scraped: {totals.scraped}")
    print(f"Jobs enriched: {totals.enriched}")
    print(f"DB upserts: {totals.db_upserts}")
    print("=" * 78 + "\n")

    # The jobs listing reads Redis only; publish this run's jobs now rather
    # than waiting for the API's next timed rebuild.
    refresh_jobs_cache()

    return {
        "roles": len(roles),
        "scraped": totals.scraped,
        "enriched": totals.enriched,
        "vetted": 0,
        "db_upserts": totals.db_upserts,
        "failed_roles": len(totals.failed_roles),
    }


def _configure_stdio():
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(line_buffering=True)
        except (AttributeError, OSError, ValueError):
            pass


if __name__ == "__main__":
    _configure_stdio()
    with _suppress_scrapling_logs():
        result = run_bulk_pipeline()
    # Exit 2 tells the hourly workflow this pass fetched nothing, so it
    # starts the scraper again instead of waiting out a cancelled run.
    if result["scraped"] <= 0:
        print("No jobs fetched this run.")
        sys.exit(2)
