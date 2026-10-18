"""Naukrigulf public search and job pages.

Listing and detail HTML, including JobPosting JSON-LD. Auth and CAPTCHA
pages are skipped.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Any, Optional

from core.state import JobData

from .public import PublicBoardParser


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")


class NaukrigulfParser(PublicBoardParser):
    board_name = "naukrigulf"
    origin = "https://www.naukrigulf.com"
    listing_selectors = (
        "div.ng-box.srp-tuple",
        "article.ng-job",
        "div.ng-job",
        "article.job-tuple",
    )
    title_selectors = (
        "a.info-position",
        "a.ng-title",
        "a.title",
        "h2 a",
        "a[href*='jobs-in']",
    )
    company_selectors = (".info-org", ".ng-company", ".company-name", ".comp-name")
    location_selectors = (".info-loc", ".ng-loc", ".loc", ".location")
    snippet_selectors = (".description", ".ng-snippet", ".job-desc")
    # Posting URLs end in -jid-<numeric id>; search URLs have no jid segment.
    job_href_pattern = re.compile(r"(?:-jid-|-)\d{5,}(?:/|$)", re.IGNORECASE)

    def build_search_url(self, query: str, location: str = "", page: int = 1) -> str:
        from core.markets import resolve_location

        ctx = self.ctx or resolve_location(location)
        place = "uae"
        if ctx is not None:
            place = getattr(ctx, "city_slug", "") or getattr(ctx, "naukrigulf_slug", "") or place
            if getattr(ctx, "remote", False):
                place = getattr(ctx, "naukrigulf_slug", "") or place
        url = f"https://www.naukrigulf.com/{_slug(query)}-jobs-in-{place}"
        if page > 1:
            url += "?" + urllib.parse.urlencode({"pageNo": str(page)})
        return url

    def is_job_href(self, href: str) -> bool:
        path = urllib.parse.urlsplit(href or "").path or (href or "")
        if "-cid-" in path.lower():
            return False
        if not self.job_href_pattern.search(path):
            return False
        # The search URL itself is "{query}-jobs-in-{place}" with no posting id.
        return True


def parse_naukrigulf_job(response: Any) -> Optional[JobData]:
    return NaukrigulfParser().parse_job(response)
