"""Fetch one listing page per board and report why GitHub vs local differs."""

from __future__ import annotations

import os
import re
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.markets import resolve_location
from scraper.boards import BaytParser, GulfTalentParser, IndeedParser, LinkedInParser, NaukrigulfParser
from scraper.spider import _fetch_with_scrapling, reset_fetch_runtime_state


QUERY = "Software Engineer"
LOCATION = "Dubai, United Arab Emirates"
_MARKET = resolve_location(LOCATION)
BOARDS = [
    ("bayt", BaytParser()),
    ("gulftalent", GulfTalentParser()),
    ("naukrigulf", NaukrigulfParser()),
    ("indeed", IndeedParser()),
    ("linkedin", LinkedInParser()),
]
_ONLY = {
    item.strip().lower()
    for item in (os.getenv("DIAGNOSE_BOARDS") or "").split(",")
    if item.strip()
}
if _ONLY:
    BOARDS = [(name, parser) for name, parser in BOARDS if name in _ONLY]
for _name, _parser in BOARDS:
    if hasattr(_parser, "set_market"):
        _parser.set_market(_MARKET)


def _snippet(response) -> str:
    html = ""
    for attr in ("html_content", "body", "text"):
        value = getattr(response, attr, None)
        if value:
            html = str(value)
            break
    if not html and response is not None:
        html = str(response)[:2000]
    lower = html.lower()
    flags = []
    for needle in (
        "cloudflare",
        "attention required",
        "captcha",
        "unusual traffic",
        "enable javascript",
        "sign in",
        "authwall",
        "challenge",
    ):
        if needle in lower:
            flags.append(needle)
    return f"len={len(html)} flags={flags or ['none']} preview={html[:180]!r}"


def _anchor_hints(response) -> list[str]:
    """Show current link/class shapes when a live parser returns no cards."""
    candidates = []
    try:
        for anchor in list(response.css("a[href]"))[:2000]:
            href = str(anchor.attrib.get("href") or "")
            classes = str(anchor.attrib.get("class") or "")
            if "job" not in href.lower() and "job" not in classes.lower():
                continue
            text = " ".join((anchor.text or "").split())
            ancestry = []
            node = getattr(anchor, "parent", None)
            for _ in range(4):
                if node is None:
                    break
                attrs = getattr(node, "attrib", {}) or {}
                ancestry.append(
                    f"{getattr(node, 'tag', '?')}."
                    f"{str(attrs.get('class') or '').replace(' ', '.')}"
                )
                node = getattr(node, "parent", None)
            score = 0
            if re.search(r"\d{5,}", href):
                score += 4
            if re.search(r"/(?:job|jobs)/", href, flags=re.IGNORECASE):
                score += 2
            if "jobs-in-" in href.lower() or href.rstrip("/").endswith("/jobs"):
                score -= 3
            candidates.append(
                (
                    score,
                    f"href={href!r} class={classes!r} text={text[:80]!r} "
                    f"parents={ancestry!r}",
                )
            )
    except Exception as exc:
        return [f"anchor inspection failed: {exc}"]
    candidates.sort(key=lambda item: item[0], reverse=True)
    return [hint for _score, hint in candidates[:30]]


def _card_hint(response) -> str:
    for selector in (
        "div.ng-box.srp-tuple",
        "div.job-card",
        "article.job-card",
        "li.job-card",
    ):
        try:
            cards = response.css(selector)
            if cards:
                card = cards[0]
                html = card.get() if hasattr(card, "get") else str(card)
                return f"selector={selector!r} html={str(html)[:3000]!r}"
        except Exception:
            continue
    return ""


def main() -> int:
    reset_fetch_runtime_state()
    print(f"CI={os.getenv('CI')!r}", flush=True)
    print(f"timeout={os.getenv('JOB_SCRAPING_FETCH_TIMEOUT_SECONDS')}", flush=True)
    print(f"query={QUERY!r} location={LOCATION!r}\n", flush=True)

    results = []
    for board, parser in BOARDS:
        url = parser.build_search_url(QUERY, LOCATION, 1)
        print("=" * 72, flush=True)
        print(f"BOARD {board}", flush=True)
        print(f"URL {url}", flush=True)
        started = time.time()
        try:
            response = _fetch_with_scrapling(url, board, True)
            elapsed = time.time() - started
            if response is None:
                print(f"RESULT none after {elapsed:.1f}s", flush=True)
                results.append((board, "none", elapsed, 0))
                continue
            status = getattr(response, "status", "?")
            urls = parser.parse_listing(response) or []
            listing_jobs = getattr(parser, "_listing_jobs", None) or []
            print(f"STATUS {status} in {elapsed:.1f}s", flush=True)
            print(f"JOB_URLS {len(urls)} LISTING_JOBS {len(listing_jobs)}", flush=True)
            print(_snippet(response), flush=True)
            if not urls and not listing_jobs:
                card_hint = _card_hint(response)
                if card_hint:
                    print(f"CARD {card_hint}", flush=True)
                for hint in _anchor_hints(response):
                    print(f"ANCHOR {hint}", flush=True)
            results.append((board, str(status), elapsed, len(urls) or len(listing_jobs)))
        except Exception as exc:
            elapsed = time.time() - started
            print(f"ERROR after {elapsed:.1f}s: {exc}", flush=True)
            traceback.print_exc()
            results.append((board, f"error:{type(exc).__name__}", elapsed, 0))

    print("\n" + "=" * 72, flush=True)
    print("SUMMARY", flush=True)
    for board, status, elapsed, n in results:
        print(f"  {board:10} status={status:16} {elapsed:6.1f}s jobs={n}", flush=True)
    return 0 if any(n > 0 for *_, n in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
