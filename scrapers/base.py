"""Abstract base scraper for all platforms."""
from abc import ABC, abstractmethod
from positronica_core.db import Job


class BaseScraper(ABC):
    """Base scraper class."""

    source_name: str = ""

    def __init__(self, db_path: str):
        """Initialize scraper."""
        self.db_path = db_path

    @abstractmethod
    def scrape(self) -> list[Job]:
        """Scrape jobs from source. Return list of Job objects."""
        pass

    def run(self) -> tuple[int, int]:
        """Run scraper and return (new_jobs, duplicates)."""
        # TODO: Implement with logging and DB storage
        return 0, 0
