"""
Helpers to enforce configured role allowlist.
"""

import re
from typing import Iterable, List, Optional

_ROLE_STOP_WORDS = frozenset({"and", "or", "the", "a", "an", "of", "in", "for", "to"})


def _normalize(value: str) -> str:
    return " ".join((value or "").lower().split())


def extract_allowed_role_from_query(query: str, permitted_roles: Iterable[str]) -> Optional[str]:
    normalized_query = _normalize(query)
    if not normalized_query:
        return None

    for role in permitted_roles:
        role_normalized = _normalize(role)
        if role_normalized and role_normalized in normalized_query:
            return role
    return None


def role_terms(query: str) -> List[str]:
    """Significant words from a role, so "Site Engineer" does not match "Software Engineer"."""
    return [
        word
        for word in re.findall(r"[a-z0-9+#]+", (query or "").lower())
        if word not in _ROLE_STOP_WORDS and len(word) > 1
    ]


def posting_matches_role(query: str, title: str = "", url: str = "") -> bool:
    """A posting matches when every role word appears in its title or URL."""
    terms = role_terms(query)
    if not terms:
        return True
    haystack = f"{title} {url}".lower().replace("-", " ").replace("_", " ")
    return all(term in haystack for term in terms)


def filter_allowed_roles(roles: Iterable[str], permitted_roles: Iterable[str]) -> List[str]:
    allowed_by_normalized = {_normalize(role): role for role in permitted_roles if _normalize(role)}
    filtered: List[str] = []

    for role in roles:
        match = allowed_by_normalized.get(_normalize(role))
        if match and match not in filtered:
            filtered.append(match)
    return filtered

