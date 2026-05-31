"""Freelancer.com scraper using REST API."""
import logging
import requests
import re
from typing import Optional

from positronica_core.db import Job
from .base import BaseScraper
from positronica_core.config import settings

logger = logging.getLogger(__name__)


class FreelancerScraper(BaseScraper):
    """Scraper for Freelancer.com using REST API."""

    source_name = "freelancer"

    def __init__(self, db_path: str):
        """Initialize Freelancer scraper."""
        super().__init__(db_path)
        self.api_token = settings.FREELANCER_OAUTH_TOKEN
        self.api_base = settings.FREELANCER_API_BASE

    def _check_api_available(self) -> bool:
        """Check if Freelancer API is configured."""
        return bool(self.api_token)

    def _make_request(self, endpoint: str, params: dict | None = None) -> dict | None:
        """Make authenticated API request."""
        if not self.api_token:
            logger.warning("Freelancer OAuth token not configured")
            return None

        url = f"{self.api_base}{endpoint}"
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }

        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            return response.json()

        except requests.RequestException as e:
            logger.error("Freelancer API request failed: %s", e)
            return None

    def _search_jobs(self, query: str, limit: int = 50) -> list[dict]:
        """Search jobs using Freelancer API."""
        # Freelancer API endpoint for job search
        # Note: This uses the public search API
        endpoint = "/projects/search/"

        params = {
            "query": query,
            "limit": min(limit, 100),
            "offset": 0,
            "sort": "newest",
            "project_types[]": ["fixed", "hourly"],
        }

        data = self._make_request(endpoint, params)
        if not data:
            return []

        # Parse response based on Freelancer API structure
        results = data.get("result", []) or data.get("projects", [])
        return results

    def _parse_salary(self, raw: str | dict) -> tuple[Optional[int], Optional[int]]:
        """Parse budget/price to min/max values."""
        if not raw:
            return None, None

        # Handle dict with min/max
        if isinstance(raw, dict):
            min_val = raw.get("minimum") or raw.get("min")
            max_val = raw.get("maximum") or raw.get("max")
            if min_val and max_val:
                return int(min_val), int(max_val)
            elif min_val:
                return int(min_val), int(min_val)

        # Handle string like "$500-$1000" or "$500"
        raw_str = str(raw)
        match = re.search(r"\$(\d+)(?:-(\d+))?", raw_str)
        if match:
            min_val = int(match.group(1))
            max_val = int(match.group(2)) if match.group(2) else min_val
            return min_val, max_val

        # Try to parse plain numbers
        try:
            val = int(raw_str.replace(",", ""))
            return val, val
        except (ValueError, AttributeError):
            pass

        return None, None

    def _convert_to_job(self, raw: dict) -> Job:
        """Convert API response to Job model."""
        title = raw.get("title", raw.get("name", "Untitled"))
        description = raw.get("description", raw.get("snippet", ""))

        # Budget handling
        budget = raw.get("budget") or raw.get("price") or raw.get("amount")
        salary_min, salary_max = self._parse_salary(budget)

        # Extract employer info
        employer = raw.get("owner", raw.get("employer", {}))
        company = None
        if isinstance(employer, dict):
            company = employer.get("name") or employer.get("username")
        elif isinstance(employer, str):
            company = employer

        # Location
        location = raw.get("location", {}).get("country") if isinstance(raw.get("location"), dict) else None

        # Tags/Skills
        tags = []
        skills = raw.get("skills", [])
        if skills:
            tags = [s.get("name", str(s)) if isinstance(s, dict) else str(s) for s in skills[:10]]

        # Employment type indicates remote
        job_type = raw.get("type", raw.get("job_type", ""))
        remote = job_type in ["remote", "hourly"] or not location

        # Time posted
        posted_at = raw.get("time_submitted") or raw.get("created_at")

        return Job(
            url=raw.get("url", f"https://www.freelancer.com/projects/{raw.get('id', '')}"),
            title=title,
            source=self.source_name,
            company=company,
            location=location,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_raw=str(budget) if budget else None,
            description=description[:5000] if description else None,
            tags=tags,
            remote=remote,
            posted_at=posted_at,
        )

    def scrape(self, queries: list[str] | None = None, limit_per_query: int = 50) -> list[Job]:
        """Scrape jobs from Freelancer.com."""
        if not self._check_api_available():
            logger.warning("Freelancer API not configured, skipping scrape")
            return []

        if queries is None:
            queries = [
                "Python",
                "FastAPI",
                "API development",
                "full stack",
                "AI",
                "machine learning",
                "data engineer",
            ]

        all_jobs = []

        for query in queries:
            logger.info("Searching Freelancer: %s", query)
            raw_jobs = self._search_jobs(query, limit_per_query)

            for raw in raw_jobs:
                try:
                    job = self._convert_to_job(raw)
                    all_jobs.append(job)
                except Exception as e:
                    logger.warning("Failed to parse Freelancer job: %s", e)
                    continue

        logger.info("Freelancer scraper: found %d jobs", len(all_jobs))
        return all_jobs

    def run(self, queries: list[str] | None = None) -> tuple[int, int]:
        """Run scraper and save to database."""
        from positronica_core.db.storage import bulk_insert_jobs

        jobs = self.scrape(queries)
        if not jobs:
            return 0, 0

        new, dupes = bulk_insert_jobs(self.db_path, jobs)
        logger.info("Freelancer scraper: %d new, %d duplicates", new, dupes)
        return new, dupes


def test_api() -> bool:
    """Test Freelancer API configuration."""
    scraper = FreelancerScraper("./mekhani.db")
    return scraper._check_api_available()