"""Upwork scraper using MCP server."""
import logging
import subprocess
import json
import re
from pathlib import Path
from typing import Optional

from positronica_core.db import Job
from .base import BaseScraper
from positronica_core.config import settings

logger = logging.getLogger(__name__)


class UpworkScraper(BaseScraper):
    """Scraper for Upwork using MCP server."""

    source_name = "upwork"

    def __init__(self, db_path: str, mcp_path: str | None = None):
        """Initialize Upwork scraper."""
        super().__init__(db_path)
        self.mcp_path = mcp_path or settings.UPWORK_MCP_PATH

    def _check_mcp_available(self) -> bool:
        """Check if MCP server is available."""
        mcp_dir = Path(self.mcp_path)
        if not mcp_dir.exists():
            logger.warning("Upwork MCP not found at %s", self.mcp_path)
            return False

        # Check for uv and pyproject
        if not (mcp_dir / "pyproject.toml").exists():
            logger.warning("Upwork MCP not properly initialized")
            return False

        return True

    def _run_mcp_command(self, query: str, limit: int = 20) -> list[dict]:
        """Run MCP search command and return parsed results."""
        cmd = [
            "uv", "run", "upwork-mcp", "search",
            "--query", query,
            "--limit", str(limit),
        ]

        try:
            result = subprocess.run(
                cmd,
                cwd=self.mcp_path,
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode != 0:
                logger.error("MCP search failed: %s", result.stderr)
                return []

            # Parse JSON output
            try:
                data = json.loads(result.stdout)
                return data.get("jobs", [])
            except json.JSONDecodeError:
                logger.warning("MCP returned non-JSON: %s", result.stdout[:500])
                return []

        except subprocess.TimeoutExpired:
            logger.error("MCP command timed out")
            return []
        except Exception as e:
            logger.error("MCP command failed: %s", e)
            return []

    def _parse_salary(self, raw: str) -> tuple[Optional[int], Optional[int]]:
        """Parse salary string to min/max values."""
        if not raw:
            return None, None

        # Handle hourly rates: "$50-80/hr" -> (50, 80)
        hourly_match = re.search(r"\$(\d+(?:,\d{3})*)\s*-\s*\$?(\d+(?:,\d{3})*)\s*/hr", raw, re.I)
        if hourly_match:
            min_val = int(hourly_match.group(1).replace(",", ""))
            max_val = int(hourly_match.group(2).replace(",", ""))
            return min_val, max_val

        # Handle fixed rates: "$500-1000" -> (500, 1000)
        fixed_match = re.search(r"\$(\d+(?:,\d{3})*)\s*-\s*\$(\d+(?:,\d{3})*)", raw, re.I)
        if fixed_match:
            min_val = int(fixed_match.group(1).replace(",", ""))
            max_val = int(fixed_match.group(2).replace(",", ""))
            return min_val, max_val

        # Handle single values
        single_match = re.search(r"\$(\d+(?:,\d{3})+)", raw, re.I)
        if single_match:
            val = int(single_match.group(1).replace(",", ""))
            return val, val

        return None, None

    def _parse_tags(self, description: str, title: str) -> list[str]:
        """Extract tags from job description and title."""
        common_tags = [
            "python", "javascript", "react", "node", "api", "rest",
            "fastapi", "django", "flask", "aws", "docker", "kubernetes",
            "postgresql", "mysql", "mongodb", "redis", "graphql",
            "typescript", "vue", "angular", "nextjs", "react native",
            "flutter", "ios", "android", "machine learning", "ai",
            "data science", "nlp", "llm", "openai", "claude",
        ]

        text = f"{description} {title}".lower()
        found = [tag for tag in common_tags if tag in text]
        return list(set(found))

    def _convert_to_job(self, raw: dict) -> Job:
        """Convert MCP raw job to Job model."""
        title = raw.get("title", "Untitled")
        description = raw.get("description", raw.get("snippet", ""))

        salary_raw = raw.get("budget") or raw.get("hourly_rate")
        salary_min, salary_max = self._parse_salary(salary_raw)

        # Extract location and remote status
        location = raw.get("location", "")
        remote = raw.get("remote", True) or "remote" in location.lower()

        return Job(
            url=raw.get("url", ""),
            title=title,
            source=self.source_name,
            company=raw.get("client", {}).get("name") if isinstance(raw.get("client"), dict) else raw.get("client"),
            location=location if location else None,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_raw=salary_raw,
            description=description[:5000] if description else None,  # Limit size
            tags=self._parse_tags(description, title),
            remote=remote,
            posted_at=raw.get("posted_at"),
        )

    def scrape(self, queries: list[str] | None = None, limit_per_query: int = 20) -> list[Job]:
        """Scrape jobs from Upwork MCP."""
        if not self._check_mcp_available():
            logger.warning("Upwork MCP not available, skipping scrape")
            return []

        if queries is None:
            queries = [
                "Python developer",
                "FastAPI developer",
                "API development",
                "full stack developer",
                "AI engineer",
                "data engineer",
            ]

        all_jobs = []

        for query in queries:
            logger.info("Searching Upwork: %s", query)
            raw_jobs = self._run_mcp_command(query, limit_per_query)

            for raw in raw_jobs:
                try:
                    job = self._convert_to_job(raw)
                    all_jobs.append(job)
                except Exception as e:
                    logger.warning("Failed to parse job: %s", e)
                    continue

        logger.info("Upwork scraper: found %d jobs", len(all_jobs))
        return all_jobs

    def run(self, queries: list[str] | None = None) -> tuple[int, int]:
        """Run scraper and save to database."""
        from positronica_core.db.storage import bulk_insert_jobs

        jobs = self.scrape(queries)
        if not jobs:
            return 0, 0

        new, dupes = bulk_insert_jobs(self.db_path, jobs)
        logger.info("Upwork scraper: %d new, %d duplicates", new, dupes)
        return new, dupes


# CLI test function
def test_mcp() -> bool:
    """Test MCP connection."""
    scraper = UpworkScraper("./mekhani.db")
    return scraper._check_mcp_available()