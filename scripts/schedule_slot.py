"""Resolve the Gulf scrape shard.

Every hour runs all five platforms. Country and role set rotate so the
full set is covered every 12 hours.
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from pathlib import Path


BOARDS = ("bayt", "gulftalent", "naukrigulf", "indeed", "linkedin")
ALL_BOARDS = ",".join(BOARDS)
COUNTRIES = ("AE", "SA", "QA", "OM", "KW", "BH")
SLOT_COUNT = len(COUNTRIES) * 2


@dataclass(frozen=True)
class ScheduleSlot:
    index: int
    board: str
    country: str
    role_set: int


def resolve_slot(epoch_hour: int) -> ScheduleSlot:
    index = int(epoch_hour) % SLOT_COUNT
    return ScheduleSlot(
        index=index,
        board=ALL_BOARDS,
        country=COUNTRIES[index % len(COUNTRIES)],
        role_set=index // len(COUNTRIES) + 1,
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
        f"JOB_SCRAPING_COUNTRIES={slot.country}",
        f"GULF_ROLE_SET={slot.role_set}",
    )
    if args.github_env:
        with args.github_env.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    else:
        print("\n".join(lines))
    print(
        f"Gulf slot {slot.index}/{SLOT_COUNT - 1} -> "
        f"{slot.board}, {slot.country}, role set {slot.role_set}"
    )


if __name__ == "__main__":
    main()
