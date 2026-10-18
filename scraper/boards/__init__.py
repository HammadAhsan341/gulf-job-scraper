"""Job board parsers for Bayt, GulfTalent, Naukrigulf, LinkedIn, and Indeed.

Rozee and Mustakbil stay importable from their modules for old fixtures, and
are not registered here. The Gulf spider does not scrape them.
"""

from .base import BaseJobParser
from .bayt import BaytParser, parse_bayt_job
from .gulftalent import GulfTalentParser, parse_gulftalent_job
from .indeed import IndeedParser, parse_indeed_job
from .linkedin import LinkedInParser, parse_linkedin_job
from .naukrigulf import NaukrigulfParser, parse_naukrigulf_job

__all__ = [
    "BaseJobParser",
    "BaytParser",
    "GulfTalentParser",
    "NaukrigulfParser",
    "LinkedInParser",
    "IndeedParser",
    "parse_bayt_job",
    "parse_gulftalent_job",
    "parse_naukrigulf_job",
    "parse_linkedin_job",
    "parse_indeed_job",
]
