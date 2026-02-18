"""Storage and persistence layer."""

from job_scraper.storage.results_storage import ResultsStorage
from job_scraper.storage.sqlite_storage import SqliteStorage, UrlCache

__all__ = ["ResultsStorage", "SqliteStorage", "UrlCache"]
