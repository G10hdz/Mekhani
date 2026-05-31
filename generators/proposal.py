"""Proposal generator using Claude API."""
import logging
import json
import yaml
from pathlib import Path
from typing import Optional

from positronica_core.db import Job
from positronica_core.llm import ClaudeClient
from positronica_core.config import settings

logger = logging.getLogger(__name__)

# Default freelancer info (can be moved to config)
DEFAULT_FREELANCER = {
    "name": "Freelancer",
    "bio": "Experienced full-stack developer with expertise in Python, React, and cloud technologies. Specialized in building scalable APIs and data pipelines.",
}


class ProposalGenerator:
    """Generates personalized proposals using Claude API."""

    def __init__(self, config_path: str = "./config/profiles.yaml"):
        """Initialize generator with config."""
        self.config_path = config_path
        self._profiles = None

    def _load_profile(self, profile_name: str) -> dict:
        """Load profile from config."""
        if self._profiles is None:
            self._load_profiles()

        profile = self._profiles.get(profile_name) or self._profiles.get("default", {})
        return profile

    def _load_profiles(self):
        """Load all profiles from config."""
        path = Path(self.config_path)
        if not path.exists():
            logger.warning("Profiles config not found, using defaults")
            self._profiles = {"default": DEFAULT_FREELANCER.copy()}
            return

        try:
            with open(path) as f:
                data = yaml.safe_load(f)
                self._profiles = data.get("profiles", {"default": DEFAULT_FREELANCER.copy()})
        except Exception as e:
            logger.error("Failed to load profiles: %s", e)
            self._profiles = {"default": DEFAULT_FREELANCER.copy()}

    def generate(self, job: Job, profile_name: str = "default") -> dict:
        """
        Generate a proposal for a job using the specified profile.

        Args:
            job: Job object to generate proposal for
            profile_name: Profile name from config

        Returns:
            dict with keys: success (bool), preview (str), proposal (str), error (str)
        """
        profile = self._load_profile(profile_name)

        # Get profile-specific info or use defaults
        freelancer_name = profile.get("name", DEFAULT_FREELANCER["name"])
        freelancer_skills = profile.get("skills", DEFAULT_FREELANCER["skills"])
        freelancer_bio = profile.get("bio", DEFAULT_FREELANCER["bio"])

        # Initialize Claude client
        try:
            client = ClaudeClient()
        except ValueError as e:
            logger.error("Claude client initialization failed: %s", e)
            return {"success": False, "error": str(e)}

        try:
            preview, proposal = client.generate_proposal(
                job=job,
                freelancer_name=freelancer_name,
                freelancer_bio=freelancer_bio,
                freelancer_skills=freelancer_skills,
            )

            if not preview and not proposal:
                return {"success": False, "error": "Empty response from Claude"}

            # Clean up preview (ensure under 35 words)
            words = preview.split()
            if len(words) > 35:
                preview = " ".join(words[:35])

            return {
                "success": True,
                "preview": preview,
                "proposal": proposal,
                "word_count": len(proposal.split()) if proposal else 0,
            }

        except Exception as e:
            logger.error("Proposal generation failed: %s", e)
            return {"success": False, "error": str(e)}

    def generate_batch(self, jobs: list[Job], profile_name: str = "default") -> list[dict]:
        """
        Generate proposals for multiple jobs.

        Args:
            jobs: List of Job objects
            profile_name: Profile name from config

        Returns:
            List of result dicts (same as generate())
        """
        results = []
        for i, job in enumerate(jobs):
            logger.info("Generating proposal %d/%d: %s", i + 1, len(jobs), job.title[:40])
            result = self.generate(job, profile_name)
            result["job_url"] = job.url
            result["job_title"] = job.title
            results.append(result)

            # Small delay between API calls to avoid rate limits
            import time
            time.sleep(1)

        return results


def generate_quick_preview(job: Job, skills: list[str]) -> str:
    """
    Generate just a quick preview (35 words) for a job.
    Used for listing in Telegram notifications.
    """
    prompt = f"""Write a compelling 35-word preview for a job proposal. Focus on the value proposition.

Job: {job.title}
Skills: {', '.join(skills[:5])}

Respond with only the preview text, no additional explanation."""

    try:
        client = ClaudeClient()
        response = client._call_api(prompt, max_tokens=100)
        if response:
            # Clean and truncate
            preview = response.strip()[:200]
            return preview
    except Exception as e:
        logger.warning("Quick preview generation failed: %s", e)

    # Fallback
    return f"Experienced developer interested in {job.title}. Can deliver quality work on time."


# CLI test
def test_proposal():
    """Test proposal generation."""
    test_job = Job(
        url="https://upwork.com/job/123",
        title="Senior Python Developer Needed",
        source="upwork",
        company="TechCorp",
        description="Looking for an experienced Python developer to build REST APIs with FastAPI. Must have experience with PostgreSQL and Docker.",
        salary_min=50,
        salary_max=80,
    )

    result = generate(test_job, "default")
    print(f"Success: {result.get('success')}")
    if result.get("preview"):
        print(f"Preview: {result['preview']}")
    if result.get("error"):
        print(f"Error: {result['error']}")

    return result.get("success", False)