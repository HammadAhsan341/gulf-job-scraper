"""Shared public-page parser for Gulf boards.

Reads listing cards and JobPosting JSON-LD. Login, bot, and CAPTCHA pages
are detected and skipped; nothing here solves a challenge or uses an account.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from core.markets import stamp_market_fields
from core.state import JobData
from scraper.guest import _jsonld_job_posting_nodes, _jsonld_plain, is_auth_wall

from .base import BaseJobParser


_EMPLOYMENT = {
    "FULL_TIME": "full-time",
    "PART_TIME": "part-time",
    "CONTRACTOR": "contract",
    "TEMPORARY": "temporary",
    "INTERN": "internship",
    "VOLUNTEER": "volunteer",
    "OTHER": "other",
}


class HtmlPage:
    """Minimal response so parsers can run on a saved HTML string."""

    def __init__(self, html: str, url: str = "", status: int = 200):
        self.url = url or ""
        self.status = status
        self.body = html or ""
        self.html_content = self.body
        self._selector = None

    def get(self):
        return self.body

    def css(self, selector: str):
        if self._selector is None:
            from scrapling.parser import Selector

            self._selector = Selector(content=self.body, url=self.url)
        return self._selector.css(selector)


def _salary_from_node(node: Dict[str, Any]) -> Optional[str]:
    raw = node.get("baseSalary") or node.get("estimatedSalary")
    if raw is None:
        return None
    if isinstance(raw, list):
        raw = raw[0] if raw else None
    if isinstance(raw, str):
        text = _jsonld_plain(raw)
        return text or None
    if not isinstance(raw, dict):
        return None
    currency = _jsonld_plain(raw.get("currency"))
    value = raw.get("value")
    amount = ""
    period = ""
    if isinstance(value, dict):
        low = value.get("minValue")
        high = value.get("maxValue")
        single = value.get("value")
        if low is not None and high is not None:
            amount = f"{low} - {high}"
        elif single is not None:
            amount = str(single)
        elif low is not None:
            amount = str(low)
        unit = _jsonld_plain(value.get("unitText"))
        if unit:
            period = unit.lower()
    elif value is not None:
        amount = _jsonld_plain(value)
    parts = [part for part in (currency, amount) if part]
    if not parts:
        return None
    text = " ".join(parts)
    if period:
        text = f"{text} per {period}"
    return text


def _employment_from_node(node: Dict[str, Any]) -> Optional[str]:
    raw = node.get("employmentType")
    if isinstance(raw, list):
        raw = raw[0] if raw else ""
    label = _jsonld_plain(raw).upper().replace(" ", "_").replace("-", "_")
    if not label:
        return None
    return _EMPLOYMENT.get(label, label.replace("_", "-").lower())


def _location_from_node(node: Dict[str, Any]) -> Dict[str, str]:
    loc = node.get("jobLocation")
    if isinstance(loc, list) and loc:
        loc = loc[0]
    if not isinstance(loc, dict):
        text = _jsonld_plain(loc)
        return {"location": text, "city": "", "state_or_emirate": "", "country": ""}
    address = loc.get("address") or loc
    if not isinstance(address, dict):
        text = _jsonld_plain(address)
        return {"location": text, "city": "", "state_or_emirate": "", "country": ""}
    city = _jsonld_plain(address.get("addressLocality"))
    region = _jsonld_plain(address.get("addressRegion"))
    country = _jsonld_plain(address.get("addressCountry"))
    location = ", ".join(part for part in (city, region, country) if part)
    return {
        "location": location,
        "city": city,
        "state_or_emirate": region,
        "country": country,
    }


def job_posting_from_html(html: str) -> Dict[str, Any]:
    """Best JobPosting object in the page, preferring the longest description."""
    best: Dict[str, Any] = {}
    best_len = -1
    for node in _jsonld_job_posting_nodes(html):
        place = _location_from_node(node)
        description = _jsonld_plain(node.get("description"))
        org = node.get("hiringOrganization") or {}
        if isinstance(org, dict):
            company = _jsonld_plain(org.get("name") or org.get("legalName"))
        else:
            company = _jsonld_plain(org)
        record = {
            "title": _jsonld_plain(node.get("title")),
            "description": description,
            "company": company,
            "location": place["location"],
            "city": place["city"],
            "state_or_emirate": place["state_or_emirate"],
            "country": place["country"],
            "salary": _salary_from_node(node),
            "employment_type": _employment_from_node(node),
            "job_url": _jsonld_plain(node.get("url")),
        }
        if len(description) > best_len:
            best = record
            best_len = len(description)
    return best


class PublicBoardParser(BaseJobParser):
    """Listing cards plus a public detail page. Subclasses build the search URL."""

    enrich_from_detail_pages = True
    listing_selectors: tuple[str, ...] = ()
    title_selectors: tuple[str, ...] = ("h2 a", "h3 a", "a")
    company_selectors: tuple[str, ...] = ()
    location_selectors: tuple[str, ...] = ()
    snippet_selectors: tuple[str, ...] = ()
    detail_selectors: tuple[str, ...] = (
        "[itemprop='description']",
        ".job-description",
        "#job-description",
        ".job_description",
    )
    job_href_pattern = re.compile(r".+")

    def __init__(self):
        self._listing_jobs: List[JobData] = []
        self.ctx = None

    def set_market(self, ctx) -> None:
        self.ctx = ctx

    def absolute_url(self, href: str, base: str = "") -> str:
        href = (href or "").strip()
        if not href or href.startswith("#") or href.lower().startswith("javascript:"):
            return ""
        origin = base or self.origin
        if href.startswith("http://") or href.startswith("https://"):
            return href.split("#")[0]
        if href.startswith("//"):
            return "https:" + href.split("#")[0]
        return urljoin(origin, href).split("#")[0]

    @property
    def origin(self) -> str:
        return ""

    def is_job_href(self, href: str) -> bool:
        return bool(href and self.job_href_pattern.search(href))

    def parse_job(self, response: Any) -> Optional[JobData]:
        if response is None or is_auth_wall(response, getattr(response, "url", "")):
            return None
        html = self._get_html(response)
        structured = job_posting_from_html(html)
        title = structured.get("title") or ""
        description = structured.get("description") or ""
        company = structured.get("company") or ""
        location = structured.get("location") or ""
        if len(description) < 40:
            css_job = self._parse_detail_css(response)
            if css_job:
                title = title or css_job.get("title") or ""
                company = company or css_job.get("company") or ""
                location = location or css_job.get("location") or ""
                if len(css_job.get("description") or "") > len(description):
                    description = css_job["description"]
        if not title or len(description) < 40:
            return None
        if not location and self.ctx is not None:
            location = getattr(self.ctx, "location_label", "") or ""
        page_url = str(getattr(response, "url", "") or structured.get("job_url") or "")
        job: JobData = {
            "job_id": self.generate_job_id(title, company or "Unknown", location or title),
            "title": title,
            "company": company or "Unknown",
            "location": location,
            "job_url": page_url,
            "board": self.board_name,
            "description": description,
            "skills": [],
            "posted_date": None,
            "salary": structured.get("salary"),
            "employment_type": structured.get("employment_type"),
            "experience_required": None,
            "raw_html": html,
        }
        if structured.get("city"):
            job["city"] = structured["city"]
        if structured.get("state_or_emirate"):
            job["state_or_emirate"] = structured["state_or_emirate"]
        if not self.validate_job_data(job):
            return None
        return stamp_market_fields(job)

    def _parse_detail_css(self, response: Any) -> Optional[Dict[str, str]]:
        title_el = self._css_first(response, ["h1", ".job-title"])
        title = self.clean_text(self._get_text(title_el))
        company_el = self._css_first(response, list(self.company_selectors) or [".company"])
        company = self.clean_text(self._get_text(company_el))
        location_el = self._css_first(response, list(self.location_selectors) or [".location"])
        location = self.clean_text(self._get_text(location_el))
        description_el = self._css_first(response, list(self.detail_selectors))
        description = self.clean_text(self._get_text(description_el))
        if not title and not description:
            return None
        return {"title": title, "company": company, "location": location, "description": description}

    def parse_listing(self, response: Any) -> List[str]:
        self._listing_jobs = []
        urls: List[str] = []
        seen = set()
        if response is None or is_auth_wall(response, getattr(response, "url", "")):
            return urls
        base = str(getattr(response, "url", "") or self.origin)
        try:
            cards: List[Any] = []
            for selector in self.listing_selectors:
                found = response.css(selector)
                if found:
                    cards = list(found)
                    break
            for card in cards:
                job = self._parse_card(card, base)
                if not job or job["job_url"] in seen:
                    continue
                seen.add(job["job_url"])
                self._listing_jobs.append(job)
                urls.append(job["job_url"])
            # SEO/search layouts sometimes expose posting links without a
            # stable card wrapper. Detail pages remain the source of truth, so
            # keep those URLs even when card metadata cannot be extracted.
            if not urls:
                for anchor in response.css("a[href]"):
                    href = anchor.attrib.get("href", "") if hasattr(anchor, "attrib") else ""
                    job_url = self.absolute_url(href, base)
                    if not job_url or job_url in seen or not self.is_job_href(job_url):
                        continue
                    seen.add(job_url)
                    urls.append(job_url)
            print(f"{self.board_name}: Found {len(urls)} job URLs ({len(self._listing_jobs)} listing cards)")
        except Exception as exc:
            print(f"{self.board_name} listing parse error: {exc}")
        return urls

    def _parse_card(self, card: Any, base: str) -> Optional[JobData]:
        link = None
        href = ""
        for selector in self.title_selectors:
            link = self._css_first(card, [selector])
            if link is None:
                continue
            href = link.attrib.get("href", "") if hasattr(link, "attrib") else ""
            if self.is_job_href(href):
                break
            href = ""
        if not href:
            for anchor in card.css("a") if hasattr(card, "css") else []:
                candidate = anchor.attrib.get("href", "") if hasattr(anchor, "attrib") else ""
                if self.is_job_href(candidate):
                    link = anchor
                    href = candidate
                    break
        job_url = self.absolute_url(href, base)
        if not job_url or not self.is_job_href(job_url):
            return None
        title = self.clean_text(self._get_text(link)) if link is not None else ""
        if not title:
            return None
        company_el = self._css_first(card, list(self.company_selectors))
        company = self.clean_text(self._get_text(company_el)) if company_el else "Unknown"
        location_el = self._css_first(card, list(self.location_selectors))
        location = self.clean_text(self._get_text(location_el)) if location_el else ""
        if not location and self.ctx is not None:
            location = getattr(self.ctx, "location_label", "") or ""
        snippet_el = self._css_first(card, list(self.snippet_selectors))
        snippet = self.clean_text(self._get_text(snippet_el)) if snippet_el else ""
        job: JobData = {
            "job_id": self.generate_job_id(title, company or "Unknown", location or title),
            "title": title,
            "company": company or "Unknown",
            "location": location,
            "job_url": job_url,
            "board": self.board_name,
            "description": snippet,
            "skills": [],
            "posted_date": None,
            "salary": None,
            "employment_type": None,
            "experience_required": None,
            "raw_html": "",
        }
        return stamp_market_fields(job)
