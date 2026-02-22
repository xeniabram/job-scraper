"""Web scraping and automation modules."""
from job_scraper.scraper.base import BaseScraper
from job_scraper.scraper.justjoinit_scraper import JustJoinItScraper
from job_scraper.scraper.nofluff_scraper import NoFluffScraper
from job_scraper.scraper.protocol_scraper import ProtocolScraper

scrapers: dict[str, type[BaseScraper]] = {
    "justjoin": JustJoinItScraper,
    "protocol": ProtocolScraper,
    "nofluff": NoFluffScraper
}