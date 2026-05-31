"""Apply and notify pipeline - orchestrates proposal generation, docs, and notifications."""
import logging
from pathlib import Path
from typing import Optional

from positronica_core.db import Job, Application
from positronica_core.db.storage import get_unapplied_jobs, save_application, mark_notified
from positronica_core.config import settings

logger = logging.getLogger(__name__)

# Import generators (will be implemented in task 8-9)
try:
    from generators.proposal import ProposalGenerator
    from generators.docs import DocsGenerator
except ImportError as e:
    logger.warning("Generators not available: %s", e)
    ProposalGenerator = None
    DocsGenerator = None


class ApplyAndNotifyPipeline:
    """
    Orchestrates the full apply workflow:
    1. Get high-scoring jobs not yet applied
    2. Generate personalized proposal via LLM
    3. Create Google Doc with proposal
    4. Submit application (or draft)
    5. Send Telegram notification
    """

    def __init__(
        self,
        db_path: str,
        profile_name: str,
        dry_run: bool = False,
    ):
        """Initialize pipeline."""
        self.db_path = db_path
        self.profile_name = profile_name
        self.dry_run = dry_run
        self.results = []

    def _load_profile_skills(self) -> list[str]:
        """Load skills for the current profile."""
        from pipelines.score_and_filter import load_profiles
        profiles = load_profiles()
        profile = profiles.get(self.profile_name, profiles.get("default", {}))
        return profile.get("skills", [])

    def _get_jobs_to_apply(self, limit: int = 10) -> list[dict]:
        """Get jobs that passed scoring threshold and aren't applied."""
        jobs = get_unapplied_jobs(
            self.db_path,
            min_score=settings.MIN_SCORE,
            limit=limit,
        )
        return jobs

    def _create_job_object(self, data: dict) -> Job:
        """Convert DB row to Job object."""
        import json
        tags = data.get("tags", "")
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except (json.JSONDecodeError, TypeError):
                tags = []
        elif tags is None:
            tags = []

        return Job(
            url=data["url"],
            title=data["title"],
            source=data["source"],
            company=data.get("company"),
            location=data.get("location"),
            salary_min=data.get("salary_min"),
            salary_max=data.get("salary_max"),
            salary_raw=data.get("salary_raw"),
            description=data.get("description"),
            tags=tags,
            remote=bool(data.get("remote")),
            score=data.get("score", 0.0),
            posted_at=data.get("posted_at"),
        )

    def process_job(self, job_data: dict) -> dict:
        """
        Process a single job: generate proposal, create doc, notify.
        Returns result dict with status and details.
        """
        job = self._create_job_object(job_data)

        result = {
            "url": job.url,
            "title": job.title,
            "source": job.source,
            "score": job.score,
            "status": "pending",
            "error": None,
            "proposal_preview": None,
            "doc_url": None,
        }

        try:
            # Step 1: Generate proposal
            if ProposalGenerator:
                generator = ProposalGenerator()
                proposal_result = generator.generate(job, self.profile_name)

                if not proposal_result.get("success"):
                    result["status"] = "failed"
                    result["error"] = f"Proposal generation failed: {proposal_result.get('error')}"
                    return result

                proposal_preview = proposal_result.get("preview", "")[:100]
                full_proposal = proposal_result.get("proposal", "")

                result["proposal_preview"] = proposal_preview
            else:
                logger.warning("ProposalGenerator not available, skipping")
                full_proposal = f"Proposal for {job.title}"
                result["proposal_preview"] = "Generator not available"

            # Step 2: Create Google Doc
            doc_url = None
            if DocsGenerator and not self.dry_run:
                docs_gen = DocsGenerator()
                doc_result = docs_gen.create_doc(
                    job_title=job.title,
                    proposal=full_proposal,
                    profile_name=self.profile_name,
                    skills=self._load_profile_skills(),
                )

                if doc_result.get("success"):
                    doc_url = doc_result.get("url")
                    result["doc_url"] = doc_url
            elif self.dry_run:
                logger.info("[DRY-RUN] Would create Google Doc for: %s", job.title)
            else:
                logger.warning("DocsGenerator not available")

            # Step 3: Save application to DB
            app = Application(
                job_url=job.url,
                job_hash=job.url_hash,
                profile_name=self.profile_name,
                status="draft" if self.dry_run else "sent",
                proposal_text=full_proposal,
                google_doc_url=doc_url,
            )

            save_application(self.db_path, app)
            result["status"] = "draft" if self.dry_run else "sent"

            # Step 4: Send Telegram notification
            if not self.dry_run:
                self._send_notification(job, result)
            else:
                logger.info("[DRY-RUN] Would send Telegram notification for: %s", job.title)

            logger.info(
                "Processed job: %s (score: %.2f, status: %s)",
                job.title[:40], job.score, result["status"]
            )

        except Exception as e:
            logger.error("Failed to process job %s: %s", job.url, e)
            result["status"] = "error"
            result["error"] = str(e)

        return result

    def _send_notification(self, job: Job, result: dict):
        """Send Telegram notification for new job."""
        from positronica_core.notifiers import TelegramNotifier

        if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
            logger.warning("Telegram not configured, skipping notification")
            return

        try:
            chat_id = int(settings.TELEGRAM_CHAT_ID)
            notifier = TelegramNotifier(settings.TELEGRAM_BOT_TOKEN, {chat_id})

            # Format message
            score_emoji = "🔥" if result["score"] > 0.7 else "⭐" if result["score"] > 0.5 else "📋"
            msg = f"""{score_emoji} *New Job Match*

*{job.title}*
🏢 {job.company or 'N/A'}
💰 {job.salary_raw or 'Budget not specified'}
📊 Score: {result["score"]:.2f}

🔗 {job.url}
"""

            if result.get("doc_url"):
                msg += f"\n📄 [Proposal Doc]({result['doc_url']})"

            # Send async
            import asyncio
            asyncio.run(notifier.send_job(job.title, job.company or "N/A", result["score"], chat_id))

        except Exception as e:
            logger.error("Failed to send Telegram notification: %s", e)

    def run(self, limit: int = 10) -> list[dict]:
        """
        Run the full apply and notify pipeline.
        Returns list of results.
        """
        logger.info("Starting apply pipeline for profile: %s", self.profile_name)

        jobs = self._get_jobs_to_apply(limit)
        logger.info("Found %d jobs to apply", len(jobs))

        results = []
        for job_data in jobs:
            result = self.process_job(job_data)
            results.append(result)

        self.results = results

        # Summary
        successful = sum(1 for r in results if r["status"] in ("sent", "draft"))
        failed = len(results) - successful

        logger.info(
            "Apply pipeline complete: %d processed, %d successful, %d failed",
            len(results), successful, failed
        )

        return results


def run_apply_pipeline(
    db_path: str,
    profile_name: str = "default",
    limit: int = 10,
    dry_run: bool = False,
) -> list[dict]:
    """
    Convenience function to run the apply pipeline.
    """
    pipeline = ApplyAndNotifyPipeline(db_path, profile_name, dry_run)
    return pipeline.run(limit)


# CLI test
def test_apply_pipeline():
    """Test the apply pipeline with sample data."""
    logger.info("Testing apply pipeline (requires DB and API keys)")
    # This would run if all components are properly configured
    pass