"""APScheduler orchestration for Mekhani."""
import logging
import signal
import sys
from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from positronica_core.config import settings

logger = logging.getLogger(__name__)

# Pipeline imports
from scrapers.upwork import UpworkScraper
from scrapers.fiverr import FiverrScraper
from scrapers.freelancer import FreelancerScraper
from pipelines.score_and_filter import filter_and_score_all_profiles, update_job_scores
from pipelines.apply_and_notify import ApplyAndNotifyPipeline


def run_pipeline():
    """Run the full job automation pipeline."""
    logger.info("=" * 60)
    logger.info("Starting pipeline run at %s", datetime.now().isoformat())
    logger.info("=" * 60)

    db_path = settings.DATABASE_PATH
    results = {
        "scraped": {},
        "scored": {},
        "applied": {},
    }

    try:
        # Step 1: Scrape jobs from all platforms
        logger.info("[1/4] Scraping jobs...")

        scrapers = []

        # Upwork
        try:
            upwork = UpworkScraper(db_path)
            new_upwork, dupes_upwork = upwork.run()
            results["scraped"]["upwork"] = {"new": new_upwork, "dupes": dupes_upwork}
            logger.info("Upwork: %d new, %d duplicates", new_upwork, dupes_upwork)
        except Exception as e:
            logger.error("Upwork scraper failed: %s", e)
            results["scraped"]["upwork"] = {"error": str(e)}

        # Fiverr
        try:
            fiverr = FiverrScraper(db_path)
            new_fiverr, dupes_fiverr = fiverr.run()
            results["scraped"]["fiverr"] = {"new": new_fiverr, "dupes": dupes_fiverr}
            logger.info("Fiverr: %d new, %d duplicates", new_fiverr, dupes_fiverr)
        except Exception as e:
            logger.error("Fiverr scraper failed: %s", e)
            results["scraped"]["fiverr"] = {"error": str(e)}

        # Freelancer
        try:
            freelancer = FreelancerScraper(db_path)
            new_freelancer, dupes_freelancer = freelancer.run()
            results["scraped"]["freelancer"] = {"new": new_freelancer, "dupes": dupes_freelancer}
            logger.info("Freelancer: %d new, %d duplicates", new_freelancer, dupes_freelancer)
        except Exception as e:
            logger.error("Freelancer scraper failed: %s", e)
            results["scraped"]["freelancer"] = {"error": str(e)}

        # Step 2: Score and filter jobs
        logger.info("[2/4] Scoring jobs...")

        try:
            scored = filter_and_score_all_profiles(db_path)
            results["scored"] = {name: len(jobs) for name, jobs in scored.items()}
            logger.info("Scored jobs by profile: %s", results["scored"])

            # Update scores in DB
            update_job_scores(db_path, scored)
        except Exception as e:
            logger.error("Scoring failed: %s", e)

        # Step 3: Apply to jobs
        logger.info("[3/4] Applying to jobs...")

        if not settings.DRY_RUN:
            try:
                pipeline = ApplyAndNotifyPipeline(
                    db_path,
                    profile_name="default",
                    dry_run=settings.DRY_RUN,
                )
                apply_results = pipeline.run(limit=10)
                results["applied"]["total"] = len(apply_results)
                results["applied"]["successful"] = sum(
                    1 for r in apply_results if r["status"] in ("sent", "draft")
                )
                logger.info("Applications: %d/%d successful",
                           results["applied"]["successful"],
                           results["applied"]["total"])
            except Exception as e:
                logger.error("Apply pipeline failed: %s", e)
        else:
            logger.info("[DRY-RUN] Skipping actual applications")

        # Step 4: Summary
        logger.info("[4/4] Pipeline complete")

        total_new = sum(
            r.get("new", 0)
            for r in results["scraped"].values()
            if isinstance(r, dict)
        )
        total_dupes = sum(
            r.get("dupes", 0)
            for r in results["scraped"].values()
            if isinstance(r, dict)
        )

        logger.info("=" * 60)
        logger.info("Pipeline Summary:")
        logger.info("  Jobs scraped: %d new, %d duplicates", total_new, total_dupes)
        logger.info("  Jobs scored: %s", results.get("scored", {}))
        if not settings.DRY_RUN:
            logger.info("  Applications: %d/%d",
                       results.get("applied", {}).get("successful", 0),
                       results.get("applied", {}).get("total", 0))
        logger.info("=" * 60)

    except Exception as e:
        logger.error("Pipeline failed: %s", e)
        raise


def run_once():
    """Run pipeline once (for --once flag)."""
    logger.info("Running pipeline once...")
    run_pipeline()


def start_scheduler():
    """Start the APScheduler with cron jobs."""
    logger.info("Initializing scheduler...")

    # Parse schedule hours
    hours = [int(h.strip()) for h in settings.SCHEDULE_HOURS.split(",")]
    logger.info("Scheduled hours: %s", hours)

    # Create scheduler
    scheduler = BlockingScheduler()

    # Add job with cron trigger for each scheduled hour
    for hour in hours:
        scheduler.add_job(
            run_pipeline,
            CronTrigger(hour=hour, minute=0),
            id=f"pipeline_{hour}",
            name=f"Pipeline at {hour}:00",
            replace_existing=True,
        )

    logger.info("Scheduler configured for hours: %s", hours)

    # Setup signal handlers for graceful shutdown
    def signal_handler(signum, frame):
        logger.info("Received signal %d, shutting down...", signum)
        scheduler.shutdown(wait=True)
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start scheduler
    logger.info("Starting scheduler...")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped")
    except Exception as e:
        logger.error("Scheduler error: %s", e)
        raise


def print_stats():
    """Print database statistics."""
    from positronica_core.db.storage import get_stats

    db_path = settings.DATABASE_PATH

    if not Path(db_path).exists():
        logger.warning("Database not found: %s", db_path)
        return

    stats = get_stats(db_path)

    print("\n" + "=" * 40)
    print("Mekhani Statistics")
    print("=" * 40)
    print(f"Total jobs: {stats['jobs_total']}")
    print(f"Notified: {stats['jobs_notified']}")
    print("\nBy source:")
    for source, count in stats.get("jobs_by_source", {}).items():
        print(f"  {source}: {count}")
    print(f"\nApplications: {stats['applications_sent']}/{stats['applications_total']} sent")
    print("=" * 40 + "\n")


def test_upwork_mcp():
    """Test Upwork MCP connection."""
    from scrapers.upwork import test_mcp

    if test_mcp():
        logger.info("Upwork MCP: OK")
        print("Upwork MCP connection: OK")
    else:
        logger.warning("Upwork MCP: NOT AVAILABLE")
        print("Upwork MCP connection: NOT AVAILABLE (run setup in CLAUDE.md)")


# Entry points for CLI
def main():
    """CLI entry point."""
    import argparse
    parser = argparse.ArgumentParser(description="Mekhani CLI")
    parser.add_argument("--once", action="store_true", help="Run pipeline once")
    parser.add_argument("--stats", action="store_true", help="Show stats")
    parser.add_argument("--test-upwork", action="store_true", help="Test Upwork MCP")
    parser.add_argument("--dry-run", action="store_true", help="Dry run mode")
    args = parser.parse_args()

    # Apply dry-run to settings
    if args.dry_run:
        settings.DRY_RUN = True

    if args.once:
        run_once()
    elif args.stats:
        print_stats()
    elif args.test_upwork:
        test_upwork_mcp()
    else:
        start_scheduler()


if __name__ == "__main__":
    main()