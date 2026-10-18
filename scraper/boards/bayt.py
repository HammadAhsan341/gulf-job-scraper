"""Bayt public job pages.

Search and detail HTML only. A login or human-check page is treated as a wall
and the listing card is left unchanged.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Any, Optional

from core.state import JobData

from .public import PublicBoardParser


class BaytParser(PublicBoardParser):
    board_name = "bayt"
    origin = "https://www.bayt.com"
    listing_selectors = (
        "li.has-pointer-d",
        "li[data-job-id]",
        "article.job-item",
    )
    title_selectors = ("h2 a", "h2.jb-title a", "a[href*='/jobs/']")
    company_selectors = (".jb-company", ".job-company", "[data-automation='company']")
    location_selectors = (".jb-loc", ".job-location", "[data-automation='location']")
    snippet_selectors = (".jb-snippet", ".job-desc", ".jb-description")
    job_href_pattern = re.compile(
        r"/en/[a-z0-9-]+/jobs/[a-z0-9-]+-\d+/?$",
        re.IGNORECASE,
    )

    def build_search_url(self, query: str, location: str = "", page: int = 1) -> str:
        from core.markets import resolve_location

        ctx = self.ctx or resolve_location(location)
        slug = getattr(ctx, "bayt_slug", "") or "uae"
        role = re.sub(r"[^a-z0-9]+", "-", (query or "").lower()).strip("-") or "jobs"
        params = {}
        city = ""
        if ctx is not None and not getattr(ctx, "remote", False):
            city = getattr(ctx, "city", "") or ""
        if city:
            params["location"] = city
        if page > 1:
            params["page"] = str(page)
        url = f"https://www.bayt.com/en/{slug}/jobs/q/{role}/"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        return url

    def is_job_href(self, href: str) -> bool:
        path = urllib.parse.urlsplit(href or "").path or (href or "")
        return bool(self.job_href_pattern.search(path.rstrip("/"))) or bool(
            self.job_href_pattern.search(path)
        )


def parse_bayt_job(response: Any) -> Optional[JobData]:
    return BaytParser().parse_job(response)
