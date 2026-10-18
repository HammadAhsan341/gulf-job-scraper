"""GulfTalent public search and job pages.

Uses the public search HTML and JobPosting JSON-LD. Does not log in or
solve a CAPTCHA.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Any, Optional

from core.state import JobData

from .public import PublicBoardParser


class GulfTalentParser(PublicBoardParser):
    board_name = "gulftalent"
    origin = "https://www.gulftalent.com"
    listing_selectors = ("div.job-card", "article.job-card", "li.job-card")
    title_selectors = ("a.job-link", "a.job-title", "h2 a", "a[href*='/jobs/']")
    company_selectors = (".company-name", ".job-company", ".company")
    location_selectors = (".job-location", ".location")
    snippet_selectors = (".job-summary", ".job-snippet")
    job_href_pattern = re.compile(r"/jobs/[a-z0-9-]+-\d+/?$", re.IGNORECASE)

    def build_search_url(self, query: str, location: str = "", page: int = 1) -> str:
        from core.markets import resolve_location

        ctx = self.ctx or resolve_location(location)
        country = getattr(ctx, "gulftalent_slug", "") or "uae"
        role = re.sub(r"[^a-z0-9]+", "-", (query or "").lower()).strip("-")
        city = ""
        if ctx is not None and not getattr(ctx, "remote", False):
            city = getattr(ctx, "city_slug", "") or ""
        parts = [country, "jobs"]
        if city:
            parts.append(city)
        parts.extend(("title", role))
        url = "https://www.gulftalent.com/" + "/".join(parts)
        params = {}
        if page > 1:
            params["page"] = str(page)
        if params:
            url += "?" + urllib.parse.urlencode(params)
        return url

    def is_job_href(self, href: str) -> bool:
        path = urllib.parse.urlsplit(href or "").path or (href or "")
        if "/jobs/search" in path:
            return False
        return bool(self.job_href_pattern.search(path))


def parse_gulftalent_job(response: Any) -> Optional[JobData]:
    return GulfTalentParser().parse_job(response)
