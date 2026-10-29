"""Resolve the Gulf scrape shard for scheduled GitHub Actions runs.

Each UTC hour runs all five platforms. Role set alternates every hour (1 then 2).
Scheduled CI runs one country per matrix job so all six GCC markets finish in
parallel within ~30 minutes instead of a 12-hour country rotation.
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from pathlib import Path


BOARDS = ("bayt", "gulftalent", "naukrigulf", "indeed", "linkedin")
ALL_BOARDS = ",".join(BOARDS)
COUNTRIES = ("AE", "SA", "QA", "OM", "KW", "BH")
# Legacy tests referenced 12 slots (6 countries × 2 role sets sequentially).
LEGACY_SLOT_COUNT = len(COUNTRIES) * 2


@dataclass(frozen=True)
class ScheduleSlot:
    index: int
    board: str
    country: str
    role_set: int


def resolve_slot(epoch_hour: int) -> ScheduleSlot:
    hour = int(epoch_hour)
    role_set = (hour % 2) + 1
    return ScheduleSlot(
        index=hour % 2,
        board=ALL_BOARDS,
        country="all",
        role_set=role_set,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--epoch-hour", type=int)
    parser.add_argument("--github-env", type=Path)
    args = parser.parse_args()

    epoch_hour = args.epoch_hour
    if epoch_hour is None:
        epoch_hour = int(time.time() // 3600)
    slot = resolve_slot(epoch_hour)
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
        f"Gulf hour {epoch_hour}: all boards, role set {slot.role_set} "
        f"(countries come from the workflow matrix)"
    )


if __name__ == "__main__":
    main()
