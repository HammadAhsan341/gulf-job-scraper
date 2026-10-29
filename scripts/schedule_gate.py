"""Decide whether a scheduled scrape should start.

GitHub drops cron events, especially at minute 0, and does not retry them.
The workflow registers two scrape waves per hour (about 30 minutes apart),
each with a backup cron a few minutes later. This gate skips duplicate
attempts in the same UTC half-hour after one success. Failed or cancelled
waves retry on the next cron. If the check itself fails, scrape anyway.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

HALF_HOUR_SECONDS = 1800


def half_hour_bucket(dt: datetime) -> str:
    """UTC label for the current 30-minute window (…T10:00 or …T10:30)."""
    utc = dt.astimezone(timezone.utc)
    minute = 0 if utc.minute < 30 else 30
    floored = utc.replace(minute=minute, second=0, microsecond=0)
    return floored.strftime("%Y-%m-%dT%H:%M")


def should_scrape(runs: list[dict], now: datetime, run_id: str) -> tuple[bool, str]:
    bucket = half_hour_bucket(now)
    for run in runs:
        if str(run.get("id")) == str(run_id):
            continue
        if run.get("conclusion") != "success":
            continue
        started = _parse(run.get("run_started_at") or run.get("created_at") or "")
        if started is None:
            continue
        if half_hour_bucket(started) == bucket:
            return False, f"successful run {run.get('id')} already started this 30-minute window"
    return True, "no successful scrape this 30-minute window"


def _parse(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def fetch_runs(repo: str, token: str, workflow: str = "scrape.yml") -> list[dict]:
    url = (
        f"https://api.github.com/repos/{repo}/actions/workflows/{workflow}/runs"
        "?per_page=40&event=schedule"
    )
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "schedule-gate",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    return list(payload.get("workflow_runs") or [])


def main() -> int:
    try:
        runs = fetch_runs(os.environ["GITHUB_REPOSITORY"], os.environ["GH_TOKEN"])
        scrape, reason = should_scrape(runs, datetime.now(timezone.utc), os.environ["GITHUB_RUN_ID"])
    except Exception as exc:
        scrape, reason = True, f"gate check failed ({exc}); scraping anyway"
    print(reason)
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"scrape={'true' if scrape else 'false'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
