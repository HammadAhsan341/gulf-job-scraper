"""Stable job_id from the board's own posting identity.

The old id hashed title|company|location, so two different postings with the
same three fields overwrote each other, and a listing card ("Unknown" company)
and its detail page produced two rows for one posting. Boards expose a native
posting id in the URL; key on board + source host + that id, and fall back to
the old hash only when the URL has none.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlsplit

_LINKEDIN_ID = re.compile(r"/jobs/view/(?:[^/?#]*?-)?(\d{5,})(?:[/?#]|$)")
_INDEED_JK = re.compile(r"^[a-f0-9]{8,}$", re.IGNORECASE)
_NAUKRI_POSTING_ID = re.compile(r"-\d{5,}$")
_BAYT_LISTING = re.compile(r"^/en/[a-z0-9-]+/jobs$")
# Listing/search pages are not postings: never key a job on them.
_SEARCH_PATHS = ("/jobs/search", "/job/jsearch", "/jobs")


def _source_host(hostname: str) -> str:
    host = (hostname or "").lower().removeprefix("www.")
    if host.endswith("linkedin.com"):
        return "linkedin.com"
    return host


def _is_search_page(host: str, path: str) -> bool:
    if path in _SEARCH_PATHS or path.startswith("/jobs/search") or path.startswith("/job/jsearch"):
        return True
    if host.endswith("bayt.com") and _BAYT_LISTING.match(path):
        return True
    if host.endswith("gulftalent.com") and path.rstrip("/").endswith("/jobs/search"):
        return True
    if host.endswith("naukrigulf.com") and "jobs-in-" in path and not _NAUKRI_POSTING_ID.search(path):
        return True
    return False


def _native_identity(board: str, url: str) -> Optional[tuple[str, str]]:
    """(source host, native posting id) or None for search pages and bare URLs."""
    if not url:
        return None
    parts = urlsplit(url.strip())
    query = parse_qs(parts.query)
    host = _source_host(parts.hostname or "")
    if board == "indeed":
        jk = (query.get("jk") or query.get("vjk") or [""])[0]
        if not _INDEED_JK.match(jk):
            return None
        return host or "indeed.com", jk.lower()
    if board == "linkedin":
        match = _LINKEDIN_ID.search(parts.path)
        if match:
            return "linkedin.com", match.group(1)
        current = (query.get("currentJobId") or [""])[0]
        return ("linkedin.com", current) if current.isdigit() else None
    path = parts.path.rstrip("/").lower()
    if not host or not path or _is_search_page(host, path):
        return None
    return host, path


def stable_job_id(job: Dict[str, Any], board_hint: str = "") -> Optional[str]:
    """Return board-native job_id, or None when the URL carries no posting id.

    The hash includes the source host so the same native id on two Indeed
    country sites (or two boards) cannot overwrite each other.
    """
    board = (job.get("board") or job.get("job_source") or board_hint or "").lower()
    identity = _native_identity(board, str(job.get("job_url") or job.get("url") or ""))
    if not identity:
        return None
    host, key = identity
    return hashlib.sha256(f"{board}|{host}|{key}".encode()).hexdigest()[:16]
