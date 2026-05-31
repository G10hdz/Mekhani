"""Mekhani CLI entry point."""
import argparse
import logging
import sys

from dotenv import load_dotenv
from pathlib import Path

# Load .env first
_env_path = Path.cwd() / ".env"
if not _env_path.exists():
    _env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path, override=True)

from positronica_core.config import settings
from positronica_core.utils import setup_logging

logger = setup_logging("mekhani")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Mekhani — Multi-platform freelance job automation"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run pipeline once and exit",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Show database statistics",
    )
    parser.add_argument(
        "--test-upwork",
        action="store_true",
        help="Test Upwork MCP connection",
    )
    parser.add_argument(
        "--test-fiverr",
        action="store_true",
        help="Test Fiverr/Apify configuration",
    )
    parser.add_argument(
        "--test-freelancer",
        action="store_true",
        help="Test Freelancer.com API",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without applying to jobs (simulation mode)",
    )
    parser.add_argument(
        "--profile",
        type=str,
        default="default",
        help="Freelancer profile to use (default: default)",
    )
    parser.add_argument(
        "--scrape-only",
        action="store_true",
        help="Only scrape jobs, skip scoring and application",
    )
    parser.add_argument(
        "--score-only",
        action="store_true",
        help="Only score existing jobs, skip scraping",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--yolo",
        action="store_true",
        help="YOLO mode: skip all validation and run pipeline with minimal checks",
    )

    args = parser.parse_args()

    # Apply verbose logging
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # YOLO mode: skip validation and run with minimal checks
    if args.yolo:
        logger.warning("🔥 YOLO MODE ACTIVATED - skipping validation checks!")
        # Force dry-run off and skip config validation
        settings.DRY_RUN = False

    # Validate configuration
    if not settings.is_configured:
        logger.error("Configuration incomplete. Please check:")
        logger.error("  - ANTHROPIC_API_KEY")
        logger.error("  - TELEGRAM_BOT_TOKEN")
        logger.error("  - TELEGRAM_CHAT_ID")
        logger.error("\nCopy .env.example to .env and configure required values.")
        sys.exit(1)

    # Apply dry-run flag
    if args.dry_run:
        settings.DRY_RUN = True
        logger.info("DRY-RUN MODE: No real applications will be sent")

    # Route to appropriate command
    if args.once:
        logger.info("Running pipeline once...")
        from scheduler import run_once
        run_once()
        logger.info("Done!")

    elif args.stats:
        logger.info("Database statistics...")
        from scheduler import print_stats
        print_stats()

    elif args.test_upwork:
        logger.info("Testing Upwork MCP...")
        from scheduler import test_upwork_mcp
        test_upwork_mcp()

    elif args.test_fiverr:
        logger.info("Testing Fiverr/Apify...")
        from scrapers.fiverr import test_apify
        if test_apify():
            print("Fiverr/Apify: OK")
        else:
            print("Fiverr/Apify: NOT CONFIGURED (set APIFY_API_KEY in .env)")

    elif args.test_freelancer:
        logger.info("Testing Freelancer.com API...")
        from scrapers.freelancer import test_api
        if test_api():
            print("Freelancer.com API: OK")
        else:
            print("Freelancer.com API: NOT CONFIGURED (set FREELANCER_OAUTH_TOKEN in .env)")

    elif args.scrape_only:
        logger.info("Running scrape-only mode...")
        from scrapers.upwork import UpworkScraper
        from scrapers.fiverr import FiverrScraper
        from scrapers.freelancer import FreelancerScraper

        db_path = settings.DATABASE_PATH
        total_new, total_dupes = 0, 0

        # Upwork
        try:
            upwork = UpworkScraper(db_path)
            new, dupes = upwork.run()
            total_new += new
            total_dupes += dupes
            logger.info("Upwork: %d new, %d duplicates", new, dupes)
        except Exception as e:
            logger.error("Upwork failed: %s", e)

        # Fiverr
        try:
            fiverr = FiverrScraper(db_path)
            new, dupes = fiverr.run()
            total_new += new
            total_dupes += dupes
            logger.info("Fiverr: %d new, %d duplicates", new, dupes)
        except Exception as e:
            logger.error("Fiverr failed: %s", e)

        # Freelancer
        try:
            freelancer = FreelancerScraper(db_path)
            new, dupes = freelancer.run()
            total_new += new
            total_dupes += dupes
            logger.info("Freelancer: %d new, %d duplicates", new, dupes)
        except Exception as e:
            logger.error("Freelancer failed: %s", e)

        logger.info("Scrape complete: %d new, %d duplicates", total_new, total_dupes)

    elif args.score_only:
        logger.info("Running score-only mode...")
        from pipelines.score_and_filter import filter_and_score_all_profiles, update_job_scores

        db_path = settings.DATABASE_PATH
        scored = filter_and_score_all_profiles(db_path)
        update_job_scores(db_path, scored)

        for profile, jobs in scored.items():
            logger.info("Profile '%s': %d jobs pass threshold", profile, len(jobs))

        logger.info("Scoring complete!")

    else:
        logger.info("Starting scheduler...")
        logger.info("Pipeline will run at: %s", settings.SCHEDULE_HOURS)
        from scheduler import start_scheduler
        start_scheduler()


if __name__ == "__main__":
    main()