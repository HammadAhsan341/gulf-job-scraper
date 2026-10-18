"""GCC market metadata and location normalization for the Gulf scraper.

Search shards use the country plus each major city. Aliases cover the names
boards put on cards ("UAE", "KSA", "Al Khobar") so one posting maps to one
country, city, and currency.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence
from urllib.parse import urlsplit


@dataclass(frozen=True)
class City:
    name: str
    state_or_emirate: str
    aliases: tuple[str, ...]
    # Major cities are search shards. Other aliases still normalize a card.
    major: bool = True

    @property
    def slug(self) -> str:
        return _slug(self.name)


@dataclass(frozen=True)
class Market:
    code: str
    country: str
    currency: str
    indeed_host: str
    aliases: tuple[str, ...]
    bayt_slug: str
    gulftalent_slug: str
    naukrigulf_slug: str
    cities: tuple[City, ...]
    market: str = "gulf"

    @property
    def linkedin_location(self) -> str:
        return self.country


@dataclass(frozen=True)
class ResolvedLocation:
    market: str
    country_code: str
    country: str
    city: str
    state_or_emirate: str
    currency: str
    indeed_host: str
    location_label: str
    remote: bool = False
    bayt_slug: str = ""
    gulftalent_slug: str = ""
    naukrigulf_slug: str = ""
    city_slug: str = ""

    @property
    def query_location(self) -> str:
        """Location string to send to a board search box."""
        if self.remote:
            return "Remote"
        return self.location_label


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")


def _norm(value: str) -> str:
    text = (value or "").lower().replace("&", " and ")
    text = text.replace(".", "")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _city(
    name: str,
    state: str,
    aliases: Sequence[str] = (),
    major: bool = True,
) -> City:
    names = (name, *aliases)
    return City(
        name=name,
        state_or_emirate=state,
        aliases=tuple(dict.fromkeys(_norm(item) for item in names if _norm(item))),
        major=major,
    )


GCC_MARKETS: tuple[Market, ...] = (
    Market(
        code="AE",
        country="United Arab Emirates",
        currency="AED",
        indeed_host="ae.indeed.com",
        aliases=("ae", "uae", "u a e", "united arab emirates", "emirates"),
        bayt_slug="uae",
        gulftalent_slug="uae",
        naukrigulf_slug="uae",
        cities=(
            _city("Dubai", "Dubai"),
            _city("Abu Dhabi", "Abu Dhabi", ("abu dhabi", "abudhabi")),
            _city("Sharjah", "Sharjah"),
            _city("Ajman", "Ajman", major=False),
        ),
    ),
    Market(
        code="SA",
        country="Saudi Arabia",
        currency="SAR",
        indeed_host="sa.indeed.com",
        aliases=("sa", "ksa", "saudi", "saudi arabia", "kingdom of saudi arabia"),
        bayt_slug="saudi-arabia",
        gulftalent_slug="saudi-arabia",
        naukrigulf_slug="saudi-arabia",
        cities=(
            _city("Riyadh", "Riyadh"),
            _city("Jeddah", "Makkah", ("jeddah", "jidda", "jiddah")),
            _city("Dammam", "Eastern Province"),
            _city("Khobar", "Eastern Province", ("khobar", "al khobar", "al-khobar"), major=False),
        ),
    ),
    Market(
        code="QA",
        country="Qatar",
        currency="QAR",
        indeed_host="qa.indeed.com",
        aliases=("qa", "qatar"),
        bayt_slug="qatar",
        gulftalent_slug="qatar",
        naukrigulf_slug="qatar",
        cities=(
            _city("Doha", "Doha"),
            _city("Al Rayyan", "Al Rayyan", ("al rayyan", "ar rayyan")),
            _city("Al Wakrah", "Al Wakrah", ("al wakrah", "al wakra")),
        ),
    ),
    Market(
        code="OM",
        country="Oman",
        currency="OMR",
        indeed_host="om.indeed.com",
        aliases=("om", "oman", "sultanate of oman"),
        bayt_slug="oman",
        gulftalent_slug="oman",
        naukrigulf_slug="oman",
        cities=(
            _city("Muscat", "Muscat"),
            _city("Salalah", "Dhofar"),
            _city("Sohar", "North Al Batinah"),
        ),
    ),
    Market(
        code="KW",
        country="Kuwait",
        currency="KWD",
        indeed_host="kw.indeed.com",
        aliases=("kw", "kuwait"),
        bayt_slug="kuwait",
        gulftalent_slug="kuwait",
        naukrigulf_slug="kuwait",
        cities=(
            _city("Kuwait City", "Capital", ("kuwait city", "al kuwayt", "kuwait-city")),
            _city("Hawalli", "Hawalli", ("hawalli", "hawally")),
            _city("Ahmadi", "Ahmadi", ("ahmadi", "al ahmadi")),
        ),
    ),
    Market(
        code="BH",
        country="Bahrain",
        currency="BHD",
        indeed_host="bh.indeed.com",
        aliases=("bh", "bahrain"),
        bayt_slug="bahrain",
        gulftalent_slug="bahrain",
        naukrigulf_slug="bahrain",
        cities=(
            _city("Manama", "Capital"),
            _city("Riffa", "Southern", ("riffa", "ar rifa")),
            _city("Muharraq", "Muharraq", ("muharraq", "al muharraq")),
        ),
    ),
)

GCC_COUNTRY_CODES: tuple[str, ...] = tuple(market.code for market in GCC_MARKETS)

_BY_CODE: Dict[str, Market] = {market.code: market for market in GCC_MARKETS}
_COUNTRY_ALIAS: Dict[str, Market] = {}
_CITY_ALIAS: Dict[str, tuple[Market, City]] = {}
for _market in GCC_MARKETS:
    for _alias in (_market.code, _market.country, *_market.aliases):
        _COUNTRY_ALIAS[_norm(_alias)] = _market
    for _city_row in _market.cities:
        for _alias in _city_row.aliases:
            _CITY_ALIAS.setdefault(_alias, (_market, _city_row))


def market_by_code(code: str) -> Optional[Market]:
    return _BY_CODE.get((code or "").strip().upper())


def major_cities(market: Market) -> tuple[City, ...]:
    return tuple(city for city in market.cities if city.major)


def search_location_labels(
    country_codes: Iterable[str],
    include_cities: bool = True,
) -> List[str]:
    """Country-wide label, then each major city, in config order."""
    labels: List[str] = []
    for code in country_codes:
        market = market_by_code(str(code))
        if market is None:
            continue
        labels.append(market.country)
        if include_cities:
            for city in major_cities(market):
                labels.append(f"{city.name}, {market.country}")
    return labels


def remote_location_label(country_code: str) -> str:
    market = market_by_code(country_code)
    if market is None:
        return "Remote"
    return f"Remote, {market.country}"


def _lookup_country(text: str) -> Optional[Market]:
    return _COUNTRY_ALIAS.get(_norm(text))


def _lookup_city(text: str) -> Optional[tuple[Market, City]]:
    return _CITY_ALIAS.get(_norm(text))


def _resolved(
    market: Market,
    city: Optional[City] = None,
    remote: bool = False,
) -> ResolvedLocation:
    if remote and city is None:
        label = f"Remote, {market.country}" if market.country else "Remote"
    elif city is not None:
        label = f"{city.name}, {market.country}"
    else:
        label = market.country
    return ResolvedLocation(
        market=market.market,
        country_code=market.code,
        country=market.country,
        city=city.name if city else "",
        state_or_emirate=city.state_or_emirate if city else "",
        currency=market.currency,
        indeed_host=market.indeed_host,
        location_label=label,
        remote=remote,
        bayt_slug=market.bayt_slug,
        gulftalent_slug=market.gulftalent_slug,
        naukrigulf_slug=market.naukrigulf_slug,
        city_slug=city.slug if city else "",
    )


def resolve_location(text: str) -> Optional[ResolvedLocation]:
    """Map a free-text place to one GCC country and, when present, one city."""
    raw = " ".join((text or "").replace("·", ",").split())
    if not raw:
        return None

    remote = False
    body = raw
    if _norm(body) == "remote" or body.lower().startswith("remote"):
        remote = True
        body = re.sub(r"^remote\b[\s,:\-]*", "", body, count=1, flags=re.IGNORECASE).strip(" ,")
        if not body:
            return ResolvedLocation(
                market="gulf",
                country_code="",
                country="",
                city="",
                state_or_emirate="",
                currency="",
                indeed_host="",
                location_label="Remote",
                remote=True,
            )

    parts = [part.strip() for part in body.split(",") if part.strip()]
    if not parts:
        parts = [body]

    found_market: Optional[Market] = None
    found_city: Optional[City] = None
    for part in parts:
        country = _lookup_country(part)
        city_hit = _lookup_city(part)
        if country is not None:
            found_market = country
        if city_hit is not None:
            city_market, city = city_hit
            if found_market is None or found_market.code == city_market.code:
                found_market = city_market
                found_city = city

    if found_market is None:
        # "Dubai UAE" without a comma.
        tokens = _norm(body)
        city_hit = _CITY_ALIAS.get(tokens)
        if city_hit is not None:
            found_market, found_city = city_hit
        else:
            found_market = _COUNTRY_ALIAS.get(tokens)

    if found_market is None:
        return None
    if found_city is not None and found_city.name not in {c.name for c in found_market.cities}:
        found_city = None
    return _resolved(found_market, found_city, remote=remote)


def source_host_from_url(url: str) -> str:
    host = (urlsplit(url or "").hostname or "").lower().removeprefix("www.")
    if host.endswith("linkedin.com"):
        return "linkedin.com"
    return host


def default_currency(location: str = "", country_code: str = "") -> str:
    """Currency implied by a Gulf place. Unknown places stay on PKR."""
    market = market_by_code(country_code)
    if market is not None:
        return market.currency
    resolved = resolve_location(location)
    if resolved and resolved.currency:
        return resolved.currency
    return "PKR"


_CURRENCY_RULES: tuple[tuple[str, str], ...] = (
    (r"(?:\$|\busd\b|\bus\$\b)", "USD"),
    (r"(?:£|\bgbp\b)", "GBP"),
    (r"(?:€|\beur\b)", "EUR"),
    (r"(?:\baed\b|\bdhs?\b|\bdirhams?\b|د\.إ)", "AED"),
    (r"(?:\bsar\b|\bsr\b|\briyals?\b|ر\.س)", "SAR"),
    (r"(?:\bqar\b|\bqr\b)", "QAR"),
    (r"(?:\bomr\b|\br\.o\.?\b|\bro\b)", "OMR"),
    (r"(?:\bkwd\b|\bkd\b)", "KWD"),
    (r"(?:\bbhd\b|\bbd\b)", "BHD"),
    (r"(?:\bpkr\b|\brs\.?(?!\w)|\brupees?\b)", "PKR"),
)


def currency_in_text(salary: str) -> str:
    """Explicit currency token in a salary string, or empty when there is none."""
    text = salary or ""
    for pattern, code in _CURRENCY_RULES:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return code
    return ""


def stamp_market_fields(job: Dict, search_location: str = "") -> Dict:
    """Fill market, country, city, emirate, and source host on a job dict."""
    out = dict(job)
    posting = resolve_location(str(out.get("location") or ""))
    search = resolve_location(search_location) if search_location else None

    chosen: Optional[ResolvedLocation] = None
    if posting and posting.country_code and not posting.remote:
        chosen = posting
    elif search and search.country_code:
        chosen = search
    elif posting and posting.country_code:
        chosen = posting

    if chosen and chosen.country_code:
        out["market"] = chosen.market or "gulf"
        out["country_code"] = chosen.country_code
        out["country"] = chosen.country
        city = chosen.city
        state = chosen.state_or_emirate
        if (
            not city
            and search
            and search.city
            and search.country_code == chosen.country_code
        ):
            city = search.city
            state = search.state_or_emirate
        if city:
            out["city"] = city
        if state:
            out["state_or_emirate"] = state
    elif search and search.remote and not out.get("market"):
        out["market"] = "gulf"

    host = source_host_from_url(str(out.get("job_url") or out.get("url") or ""))
    if host:
        out["source_host"] = host
    return out
