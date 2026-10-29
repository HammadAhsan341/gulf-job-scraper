"""Resolve the Gulf scrape shard for scheduled GitHub Actions runs.

Every 30 minutes (UTC half-hour) runs all five platforms across six parallel
country jobs. Role set alternates each half-hour (1 then 2).
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from pathlib import Path

from scripts.schedule_gate import HALF_HOUR_SECONDS

BOARDS = ("bayt", "gulftalent", "naukrigulf", "indeed", "linkedin")
ALL_BOARDS = ",".join(BOARDS)
COUNTRIES = ("AE", "SA", "QA", "OM", "KW", "BH")
LEGACY_SLOT_COUNT = len(COUNTRIES) * 2


@dataclass(frozen=True)
class ScheduleSlot:
    index: int
    board: str
    country: str
    role_set: int


def resolve_slot(epoch_half_hour: int) -> ScheduleSlot:
    half = int(epoch_half_hour)
    role_set = (half % 2) + 1
    return ScheduleSlot(
        index=half % 2,
        board=ALL_BOARDS,
        country="all",
        role_set=role_set,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--epoch-half-hour", type=int)
    parser.add_argument("--epoch-hour", type=int, help="Deprecated; prefer --epoch-half-hour")
    parser.add_argument("--github-env", type=Path)
    args = parser.parse_args()

    if args.epoch_half_hour is not None:
        epoch_half = int(args.epoch_half_hour)
    elif args.epoch_hour is not None:
        epoch_half = int(args.epoch_hour) * 2
    else:
        epoch_half = int(time.time() // HALF_HOUR_SECONDS)
    slot = resolve_slot(epoch_half)
    lines = (
        f"JOB_SCRAPING_BOARDS={slot.board}",
        f"GULF_ROLE_SET={slot.role_set}",
    )
    if args.github_env:
        with args.github_env.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    else:
        print("\n".join(lines))
    print(
        f"Gulf half-hour {epoch_half}: all boards, role set {slot.role_set} "
        f"(countries run in parallel via workflow matrix)"
    )


if __name__ == "__main__":
    main()
