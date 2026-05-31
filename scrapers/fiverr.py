"""Fiverr scraper using Apify."""
import logging
import asyncio
from typing import Optional

from positronica_core.db import Job
from .base import BaseScraper
from positronica_core.config import settings

logger = logging.getLogger(__name__)


class FiverrScraper(BaseScraper):
    """Scraper for Fiverr using Apify actor."""

    source_name = "fiverr"

    def __init__(self, db_path: str):
        """Initialize Fiverr scraper."""
        super().__init__(db_path)
        self.api_key = settings.APIFY_API_KEY
        self.actor_id = "automation-lab/fiverr-scraper"

    def _check_apify_available(self) -> bool:
        """Check if Apify is configured."""
        return bool(self.api_key)

    async def _run_apify_actor(self, keyword: str, max_results: int = 30) -> list[dict]:
        """Run Apify actor and return results."""
        from apify_client import ApifyClient

        if not self.api_key:
            logger.warning("Apify API key not configured")
            return []

        client = ApifyClient(self.api_key)

        # Actor input for job search
        input_data = {
            "keyword": keyword,
            "maxResults": max_results,
            "category": "web-development",
        }

        try:
            # Start actor
            actor_call = client.actor(self.actor_id).call(
                run_input=input_data,
                timeout_secs=120,
            )

            # Get dataset items
            items = []
            for item in client.dataset(actor_call["id"]).iterate_items():
                items.append(item)

            logger.info("Apify actor returned %d items for '%s'", len(items), keyword)
            return items

        except Exception as e:
            logger.error("Apify actor failed: %s", e)
            return []

    def _convert_to_job(self, raw: dict) -> Job:
        """Convert Apify raw item to Job model."""
        title = raw.get("title", "Untitled")
        description = raw.get("description", raw.get("short_description", ""))

        # Fiverr uses "price" or "budget" field
        price_raw = raw.get("price") or raw.get("budget")
        salary_min, salary_max = None, None

        if price_raw:
            # Parse price like "$100-$500" or just "$100"
            import re
            match = re.search(r"\$(\d+)(?:-(\d+))?", str(price_raw))
            if match:
                salary_min = int(match.group(1))
                salary_max = int(match.group(2)) if match.group(2) else salary_min

        # Fiverr is always remote (it's the platform nature)
        tags = []
        if description:
            # Extract common tech tags
            tech_keywords = [
                "python", "javascript", "react", "node", "api", "rest",
                "fastapi", "django", "flask", "aws", "docker", "postgresql",
                "api", "automation", "scraper", "data", "ai", "ml",
            ]
            text = f"{description} {title}".lower()
            tags = [k for k in tech_keywords if k in text]

        return Job(
            url=raw.get("url", ""),
            title=title,
            source=self.source_name,
            company=raw.get("seller", {}).get("name") if isinstance(raw.get("seller"), dict) else None,
            location=None,  # Fiverr is remote by nature
            salary_min=salary_min,
            salary_max=salary_max,
            salary_raw=str(price_raw) if price_raw else None,
            description=description[:5000] if description else None,
            tags=list(set(tags)),
            remote=True,  # Fiverr is always remote
            posted_at=raw.get("created_at"),
        )

    async def _scrape_async(self, keywords: list[str], max_per_keyword: int = 30) -> list[Job]:
        """Async scrape jobs from Fiverr via Apify."""
        if not self._check_apify_available():
            logger.warning("Apify not configured, skipping Fiverr scrape")
            return []

        all_jobs = []

        for keyword in keywords:
            logger.info("Searching Fiverr: %s", keyword)
            raw_items = await self._run_apify_actor(keyword, max_per_keyword)

            for raw in raw_items:
                try:
                    job = self._convert_to_job(raw)
                    all_jobs.append(job)
                except Exception as e:
                    logger.warning("Failed to parse Fiverr item: %s", e)
                    continue

        logger.info("Fiverr scraper: found %d gigs", len(all_jobs))
        return all_jobs

    def scrape(self, keywords: list[str] | None = None, max_per_keyword: int = 30) -> list[Job]:
        """Scrape jobs from Fiverr (sync wrapper)."""
        if keywords is None:
            keywords = [
                "API development",
                "Python automation",
                "web scraper",
                "data pipeline",
                "AI integration",
            ]

        return asyncio.run(self._scrape_async(keywords, max_per_keyword))

    def run(self, keywords: list[str] | None = None) -> tuple[int, int]:
        """Run scraper and save to database."""
        from positronica_core.db.storage import bulk_insert_jobs

        jobs = self.scrape(keywords)
        if not jobs:
            return 0, 0

        new, dupes = bulk_insert_jobs(self.db_path, jobs)
        logger.info("Fiverr scraper: %d new, %d duplicates", new, dupes)
        return new, dupes


def test_apify() -> bool:
    """Test Apify configuration."""
    scraper = FiverrScraper("./mekhani.db")
    return scraper._check_apify_available()