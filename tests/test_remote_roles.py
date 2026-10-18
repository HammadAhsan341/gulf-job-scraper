import unittest

from main import _role_searches
from scraper.boards.linkedin import LinkedInParser
from tests.test_scrape_resilience import _settings

ALL_BOARDS = ["bayt", "gulftalent", "naukrigulf", "indeed", "linkedin"]
UAE = "United Arab Emirates"


class TestRemoteRoleSearches(unittest.TestCase):
    def test_remote_role_gets_country_then_remote_on_linkedin_and_indeed(self):
        settings = _settings(job_scraping_boards=ALL_BOARDS, remote_roles=["Graphic Designer"])
        self.assertEqual(
            _role_searches("graphic designer", settings),
            [(b, UAE) for b in ALL_BOARDS]
            + [("indeed", "Remote, United Arab Emirates"), ("linkedin", "Remote")],
        )

    def test_other_roles_only_search_the_configured_country(self):
        settings = _settings(job_scraping_boards=ALL_BOARDS, remote_roles=["Graphic Designer"])
        self.assertEqual(_role_searches("Software Engineer", settings), [(b, UAE) for b in ALL_BOARDS])

    def test_remote_pass_skips_boards_that_are_not_remote_capable(self):
        settings = _settings(job_scraping_boards=["bayt"], remote_roles=["Graphic Designer"])
        self.assertEqual(_role_searches("Graphic Designer", settings), [("bayt", UAE)])

    def test_rozee_and_mustakbil_are_not_searched(self):
        settings = _settings(
            job_scraping_boards=["rozee", "mustakbil", "bayt"],
            remote_roles=[],
        )
        self.assertEqual(_role_searches("Software Engineer", settings), [("bayt", UAE)])


class TestLinkedInRemoteUrl(unittest.TestCase):
    def test_remote_uses_worldwide_and_remote_filter(self):
        url = LinkedInParser().build_search_url("Graphic Designer", "Remote", 1)
        self.assertIn("location=Worldwide", url)
        self.assertIn("f_WT=2", url)

    def test_pakistan_search_is_unchanged(self):
        url = LinkedInParser().build_search_url("Graphic Designer", "Pakistan", 1)
        self.assertIn("location=Pakistan", url)
        self.assertNotIn("f_WT", url)


if __name__ == "__main__":
    unittest.main()
