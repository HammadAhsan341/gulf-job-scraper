"""GCC config, public board adapters, identity, locations, and currencies."""

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.markets import (
    GCC_COUNTRY_CODES,
    GCC_MARKETS,
    currency_in_text,
    default_currency,
    resolve_location,
    search_location_labels,
    stamp_market_fields,
)
from core.role_filters import posting_matches_role
from core.settings import DISABLED_BOARDS, _parse_boards, _parse_countries
from main import _role_searches
from scraper.boards.bayt import BaytParser
from scraper.boards.gulftalent import GulfTalentParser
from scraper.boards.indeed import IndeedParser
from scraper.boards.naukrigulf import NaukrigulfParser
from scraper.boards.public import HtmlPage
from scraper.job_identity import stable_job_id
from scraper.listing_persist import prepare_job_for_persist
from services.job_record import job_to_record
from services.supabase import SupabaseService
from scripts.schedule_slot import BOARDS, COUNTRIES, SLOT_COUNT, resolve_slot
from tests.test_audit_fixes import _enricher
from tests.test_scrape_resilience import _settings

FIXTURES = Path(__file__).parent / "fixtures"

EXPECTED = {
    "AE": ("AED", "ae.indeed.com", "United Arab Emirates", "Dubai"),
    "SA": ("SAR", "sa.indeed.com", "Saudi Arabia", "Riyadh"),
    "QA": ("QAR", "qa.indeed.com", "Qatar", "Doha"),
    "OM": ("OMR", "om.indeed.com", "Oman", "Muscat"),
    "KW": ("KWD", "kw.indeed.com", "Kuwait", "Kuwait City"),
    "BH": ("BHD", "bh.indeed.com", "Bahrain", "Manama"),
}


def _html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class TestMarketConfig(unittest.TestCase):
    def test_six_markets_have_currency_host_and_major_cities(self):
        self.assertEqual(tuple(market.code for market in GCC_MARKETS), GCC_COUNTRY_CODES)
        self.assertEqual(set(EXPECTED), set(GCC_COUNTRY_CODES))
        for market in GCC_MARKETS:
            currency, host, country, city = EXPECTED[market.code]
            self.assertEqual(market.currency, currency)
            self.assertEqual(market.indeed_host, host)
            self.assertEqual(market.country, country)
            self.assertIn(city, [row.name for row in market.cities if row.major])
            self.assertTrue(market.aliases)
            self.assertTrue(market.bayt_slug)
            self.assertTrue(market.gulftalent_slug)
            self.assertTrue(market.naukrigulf_slug)

    def test_aliases_and_cities_resolve(self):
        cases = {
            "UAE": ("AE", "", "AED"),
            "U.A.E.": ("AE", "", "AED"),
            "KSA": ("SA", "", "SAR"),
            "Dubai, UAE": ("AE", "Dubai", "AED"),
            "Abu Dhabi": ("AE", "Abu Dhabi", "AED"),
            "Al Khobar": ("SA", "Khobar", "SAR"),
            "Doha, Qatar": ("QA", "Doha", "QAR"),
            "Muscat": ("OM", "Muscat", "OMR"),
            "Kuwait City": ("KW", "Kuwait City", "KWD"),
            "Manama, Bahrain": ("BH", "Manama", "BHD"),
            "Remote, Saudi Arabia": ("SA", "", "SAR"),
        }
        for text, (code, city, currency) in cases.items():
            resolved = resolve_location(text)
            self.assertIsNotNone(resolved, text)
            self.assertEqual(resolved.country_code, code, text)
            self.assertEqual(resolved.city, city, text)
            self.assertEqual(resolved.currency, currency, text)
            self.assertEqual(resolved.indeed_host, EXPECTED[code][1], text)
            if city:
                self.assertTrue(resolved.state_or_emirate, text)
        remote = resolve_location("Remote, Saudi Arabia")
        self.assertTrue(remote.remote)
        self.assertEqual(remote.query_location, "Remote")

    def test_search_shards_are_country_then_major_cities(self):
        labels = search_location_labels(["QA"], include_cities=True)
        self.assertEqual(labels[0], "Qatar")
        self.assertIn("Doha, Qatar", labels)
        self.assertGreater(len(labels), 1)
        country_only = search_location_labels(["OM", "BH"], include_cities=False)
        self.assertEqual(country_only, ["Oman", "Bahrain"])

    def test_role_search_includes_city_shards_for_one_board(self):
        settings = _settings(
            job_scraping_boards=["bayt"],
            job_scraping_countries=["AE"],
            job_scraping_include_cities=True,
            remote_roles=[],
        )
        locations = [location for _board, location in _role_searches("Software Engineer", settings)]
        self.assertEqual(locations[0], "United Arab Emirates")
        self.assertIn("Dubai, United Arab Emirates", locations)
        self.assertIn("Abu Dhabi, United Arab Emirates", locations)
        self.assertIn("Sharjah, United Arab Emirates", locations)

    def test_settings_drop_pakistan_boards_and_accept_country_names(self):
        self.assertEqual(
            _parse_boards("all"),
            ["bayt", "gulftalent", "naukrigulf", "indeed", "linkedin"],
        )
        self.assertEqual(_parse_boards("rozee,bayt,mustakbil"), ["bayt"])
        self.assertEqual(DISABLED_BOARDS, frozenset({"rozee", "mustakbil"}))
        self.assertEqual(_parse_countries("uae, KSA, qatar"), ["AE", "SA", "QA"])
        self.assertEqual(_parse_countries("all"), list(GCC_COUNTRY_CODES))

    def test_role_filter_keeps_the_searched_title(self):
        self.assertTrue(posting_matches_role(
            "Software Engineer",
            "Senior Software Engineer",
            "https://www.bayt.com/en/uae/jobs/senior-software-engineer-445566/",
        ))
        self.assertFalse(posting_matches_role(
            "Software Engineer",
            "Sales Manager",
            "https://www.bayt.com/en/uae/jobs/sales-manager-5496335/",
        ))
        self.assertFalse(posting_matches_role(
            "Software Engineer",
            "Site Engineer",
            "https://www.bayt.com/en/uae/jobs/site-engineer-5496351/",
        ))
        self.assertTrue(posting_matches_role(
            "Software Engineer",
            "",
            "https://www.gulftalent.com/uae/jobs/software-engineer-643017",
        ))

    def test_schedule_runs_every_platform_for_each_country_and_role_set(self):
        slots = [resolve_slot(hour) for hour in range(SLOT_COUNT)]
        combinations = {(slot.country, slot.role_set) for slot in slots}
        expected = {
            (country, role_set)
            for country in COUNTRIES
            for role_set in (1, 2)
        }
        self.assertEqual(combinations, expected)
        self.assertEqual(SLOT_COUNT, 12)
        for slot in slots:
            self.assertEqual(slot.board, ",".join(BOARDS))
        self.assertEqual(resolve_slot(SLOT_COUNT), resolve_slot(0))


class TestBoardAdapters(unittest.TestCase):
    def test_bayt_search_listing_and_jsonld(self):
        parser = BaytParser()
        parser.set_market(resolve_location("Dubai, United Arab Emirates"))
        url = parser.build_search_url("Senior Software Engineer", "Dubai, United Arab Emirates", 2)
        self.assertEqual(
            url,
            "https://www.bayt.com/en/uae/jobs/q/senior-software-engineer/?location=Dubai&page=2",
        )

        page = HtmlPage(_html("bayt_listing.html"), url="https://www.bayt.com/en/uae/jobs/")
        urls = parser.parse_listing(page)
        self.assertEqual(urls, ["https://www.bayt.com/en/uae/jobs/senior-software-engineer-445566/"])
        card = parser._listing_jobs[0]
        self.assertEqual(card["title"], "Senior Software Engineer")
        self.assertEqual(card["company"], "Acme Gulf")
        self.assertEqual(card["city"], "Dubai")
        self.assertEqual(card["country_code"], "AE")
        self.assertEqual(card["source_host"], "bayt.com")

        detail = parser.parse_job(HtmlPage(
            _html("bayt_detail.html"),
            url="https://www.bayt.com/en/uae/jobs/senior-software-engineer-445566/",
        ))
        self.assertEqual(detail["company"], "Acme Gulf")
        self.assertIn("payments services", detail["description"])
        self.assertIn("AED", detail["salary"])
        self.assertEqual(detail["employment_type"], "full-time")
        self.assertEqual(detail["state_or_emirate"], "Dubai")
        self.assertEqual(detail["country_code"], "AE")

    def test_bayt_login_wall_is_not_a_job(self):
        parser = BaytParser()
        job = parser.parse_job(HtmlPage(
            _html("bayt_login.html"),
            url="https://www.bayt.com/en/login",
        ))
        self.assertIsNone(job)

    def test_gulftalent_search_listing_and_jsonld(self):
        parser = GulfTalentParser()
        parser.set_market(resolve_location("Doha, Qatar"))
        url = parser.build_search_url("Backend Engineer", "Doha, Qatar", 1)
        self.assertEqual(
            url,
            "https://www.gulftalent.com/qatar/jobs/doha/title/backend-engineer",
        )
        self.assertNotIn("page=", url)

        page = HtmlPage(_html("gulftalent_listing.html"), url=url)
        urls = parser.parse_listing(page)
        self.assertEqual(urls, ["https://www.gulftalent.com/jobs/backend-engineer-doha-778899"])
        card = parser._listing_jobs[0]
        self.assertEqual(card["company"], "Qatar Tech")
        self.assertEqual(card["city"], "Doha")
        self.assertEqual(card["country_code"], "QA")
        self.assertEqual(card["source_host"], "gulftalent.com")

        detail = parser.parse_job(HtmlPage(
            _html("gulftalent_detail.html"),
            url="https://www.gulftalent.com/jobs/backend-engineer-doha-778899",
        ))
        self.assertIn("QAR", detail["salary"])
        self.assertEqual(detail["city"], "Doha")
        self.assertGreater(len(detail["description"]), 40)

        seo_page = HtmlPage(
            '<a href="/qatar/jobs/backend-engineer-778899">Backend Engineer</a>',
            url="https://www.gulftalent.com/qatar/jobs/doha/title/backend-engineer",
        )
        self.assertEqual(
            parser.parse_listing(seo_page),
            ["https://www.gulftalent.com/qatar/jobs/backend-engineer-778899"],
        )

    def test_naukrigulf_search_listing_and_jsonld(self):
        parser = NaukrigulfParser()
        parser.set_market(resolve_location("Riyadh, Saudi Arabia"))
        url = parser.build_search_url("Data Engineer", "Riyadh, Saudi Arabia", 3)
        self.assertEqual(
            url,
            "https://www.naukrigulf.com/data-engineer-jobs-in-riyadh?pageNo=3",
        )
        page = HtmlPage(_html("naukrigulf_listing.html"), url="https://www.naukrigulf.com/data-engineer-jobs-in-riyadh")
        urls = parser.parse_listing(page)
        self.assertEqual(len(urls), 1)
        self.assertIn("8800112", urls[0])
        card = parser._listing_jobs[0]
        self.assertEqual(card["title"], "Data Engineer")
        self.assertEqual(card["country_code"], "SA")
        self.assertEqual(card["state_or_emirate"], "Riyadh")
        self.assertEqual(card["source_host"], "naukrigulf.com")

        detail = parser.parse_job(HtmlPage(
            _html("naukrigulf_detail.html"),
            url=urls[0],
        ))
        self.assertEqual(detail["company"], "Northstar")
        self.assertIn("SAR", detail["salary"])
        self.assertEqual(detail["city"], "Riyadh")

    def test_indeed_host_follows_the_market(self):
        pakistan = IndeedParser()
        self.assertTrue(
            pakistan.build_search_url("Software Engineer", "Pakistan", 1).startswith(
                "https://pk.indeed.com/jobs?"
            )
        )
        parser = IndeedParser()
        parser.set_market(resolve_location("Sharjah, United Arab Emirates"))
        url = parser.build_search_url("Software Engineer", "Sharjah, United Arab Emirates", 2)
        self.assertTrue(url.startswith("https://ae.indeed.com/jobs?"))
        self.assertIn("start=10", url)
        self.assertIn("l=Sharjah", url)
        remote = parser.build_search_url("Software Engineer", "Remote, United Arab Emirates", 1)
        self.assertIn("ae.indeed.com", remote)
        self.assertIn("l=Remote", remote)
        self.assertEqual(
            parser.viewjob_url("/rc/clk?jk=ae59229661c2e928&from=serp", parser.host),
            "https://ae.indeed.com/viewjob?jk=ae59229661c2e928",
        )
        saudi = IndeedParser(host="sa.indeed.com")
        pane = saudi.build_serp_vjk_url("Data Engineer", "Riyadh", "abc123def4567890", page=1)
        self.assertTrue(pane.startswith("https://sa.indeed.com/jobs?"))
        self.assertIn("vjk=abc123def4567890", pane)


class TestIdentityAndRecord(unittest.TestCase):
    def test_same_indeed_id_on_two_hosts_does_not_collide(self):
        jk = "abc123def4567890"
        ae = stable_job_id({
            "board": "indeed",
            "job_url": f"https://ae.indeed.com/viewjob?jk={jk}",
        })
        sa = stable_job_id({
            "board": "indeed",
            "job_url": f"https://sa.indeed.com/rc/clk?jk={jk.upper()}&from=serp",
        })
        same = stable_job_id({
            "board": "indeed",
            "job_url": f"https://ae.indeed.com/viewjob?jk={jk}",
        })
        self.assertNotEqual(ae, sa)
        self.assertEqual(ae, same)

    def test_gulf_search_pages_are_not_posting_ids(self):
        self.assertIsNone(stable_job_id({
            "board": "bayt",
            "job_url": "https://www.bayt.com/en/uae/jobs/?keywords=python",
        }))
        self.assertIsNone(stable_job_id({
            "board": "gulftalent",
            "job_url": "https://www.gulftalent.com/jobs/search?keywords=python",
        }))
        self.assertIsNone(stable_job_id({
            "board": "naukrigulf",
            "job_url": "https://www.naukrigulf.com/data-engineer-jobs-in-riyadh",
        }))
        posting = stable_job_id({
            "board": "bayt",
            "job_url": "https://www.bayt.com/en/uae/jobs/senior-software-engineer-445566/",
        })
        self.assertTrue(posting)

    def test_prepare_and_record_carry_geo_fields(self):
        job = prepare_job_for_persist({
            "job_id": "old",
            "board": "bayt",
            "title": "Senior Software Engineer",
            "company": "Acme Gulf",
            "location": "Dubai, United Arab Emirates",
            "description": "Build payments services for the Dubai office team.",
            "job_url": "https://www.bayt.com/en/uae/jobs/senior-software-engineer-445566/",
            "search_location": "United Arab Emirates",
        })
        self.assertEqual(job["market"], "gulf")
        self.assertEqual(job["country_code"], "AE")
        self.assertEqual(job["country"], "United Arab Emirates")
        self.assertEqual(job["city"], "Dubai")
        self.assertEqual(job["state_or_emirate"], "Dubai")
        self.assertEqual(job["source_host"], "bayt.com")
        self.assertEqual(job["job_id"], stable_job_id(job))
        record = job_to_record(job)
        self.assertEqual(record["market"], "gulf")
        self.assertEqual(record["country_code"], "AE")
        self.assertEqual(record["city"], "Dubai")
        self.assertEqual(record["state_or_emirate"], "Dubai")
        self.assertEqual(record["source_host"], "bayt.com")
        self.assertNotIn("search_location", record["raw_payload"])

    def test_country_shard_fills_city_when_the_card_has_none(self):
        stamped = stamp_market_fields(
            {"location": "", "job_url": "https://www.gulftalent.com/jobs/backend-engineer-doha-778899"},
            "Doha, Qatar",
        )
        self.assertEqual(stamped["city"], "Doha")
        self.assertEqual(stamped["country_code"], "QA")
        self.assertEqual(stamped["source_host"], "gulftalent.com")


class TestGulfCurrencies(unittest.TestCase):
    def test_explicit_codes_and_location_defaults(self):
        enricher = _enricher()
        aed = enricher.normalize_salary("AED 18,000 - 25,000 per month", "Dubai")
        self.assertEqual(aed["currency"], "AED")
        self.assertEqual((aed["min"], aed["max"], aed["period"]), (18000, 25000, "month"))
        sar = enricher.normalize_salary("SAR 12,000 per annum", "Riyadh")
        self.assertEqual((sar["currency"], sar["period"]), ("SAR", "year"))
        self.assertEqual(enricher.normalize_salary("QAR 15000", "Doha")["currency"], "QAR")
        self.assertEqual(enricher.normalize_salary("OMR 800", "Muscat")["currency"], "OMR")
        self.assertEqual(enricher.normalize_salary("KD 400", "Kuwait City")["currency"], "KWD")
        self.assertEqual(enricher.normalize_salary("BD 500", "Manama")["currency"], "BHD")
        self.assertEqual(enricher.normalize_salary("Dhs 9,000", "Sharjah")["currency"], "AED")
        implied = enricher.normalize_salary("8,000 - 12,000", "Dubai, UAE")
        self.assertEqual(implied["currency"], "AED")
        pakistan = enricher.normalize_salary("PKR 80,000 - 120,000", "Pakistan")
        self.assertEqual(pakistan["currency"], "PKR")
        self.assertEqual((pakistan["min"], pakistan["max"]), (80000, 120000))
        self.assertEqual(currency_in_text("Rs 50,000"), "PKR")
        self.assertEqual(default_currency("Jeddah"), "SAR")
        self.assertEqual(default_currency("", "QA"), "QAR")
        self.assertEqual(default_currency("Lahore"), "PKR")


class _Query:
    def __init__(self, sink):
        self.sink = sink

    def select(self, *_args, **_kwargs):
        return self

    def lt(self, *_args):
        return self

    def eq(self, column, value):
        self.sink["eq"].append((column, value))
        return self

    def order(self, *_args, **_kwargs):
        return self

    def range(self, *_args):
        return self

    def execute(self):
        return SimpleNamespace(data=[])

    def delete(self):
        self.sink["delete"] += 1
        return self

    def in_(self, *_args):
        return self

    def gte(self, *_args):
        return self


class _Client:
    def __init__(self):
        self.sink = {"eq": [], "delete": 0, "tables": []}

    def table(self, name):
        self.sink["tables"].append(name)
        return _Query(self.sink)


class TestStaleCleanupScope(unittest.TestCase):
    def test_gulf_country_filter_does_not_sweep_every_processed_row(self):
        service = SupabaseService.__new__(SupabaseService)
        service.client = _Client()
        deleted = service.delete_stale_jobs(days=7, market="gulf", country_code="ae")
        self.assertEqual(deleted, 0)
        self.assertIn(("market", "gulf"), service.client.sink["eq"])
        self.assertIn(("country_code", "AE"), service.client.sink["eq"])
        self.assertEqual(service.client.sink["delete"], 0)

    def test_unscoped_cleanup_still_sweeps_old_processed_rows(self):
        service = SupabaseService.__new__(SupabaseService)
        service.client = _Client()
        service.delete_stale_jobs(days=7)
        self.assertEqual(service.client.sink["eq"], [])
        self.assertEqual(service.client.sink["delete"], 1)
        self.assertIn("processed_jobs", service.client.sink["tables"])


class TestSpiderBoards(unittest.TestCase):
    def test_registered_boards_exclude_rozee_and_mustakbil(self):
        from scraper.spider import JobScraperSpider

        spider = JobScraperSpider()
        self.assertEqual(
            set(spider.parsers),
            {"bayt", "gulftalent", "naukrigulf", "indeed", "linkedin"},
        )
        self.assertEqual(spider.scrape_board("rozee", "Software Engineer"), [])
        self.assertEqual(spider.scrape_board("mustakbil", "Software Engineer"), [])


if __name__ == "__main__":
    unittest.main()
