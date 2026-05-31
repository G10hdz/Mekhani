"""Score and filter pipeline - multi-profile job matching."""
import logging
import yaml
from pathlib import Path
from typing import Optional

from positronica_core.db import Job
from positronica_core.db.storage import get_unnotified_jobs, mark_notified
from positronica_core.filters import score_job, match_cv
from positronica_core.config import settings

logger = logging.getLogger(__name__)


def load_profiles(config_path: str = "./config/profiles.yaml") -> dict:
    """Load freelancer profiles from YAML config."""
    path = Path(config_path)
    if not path.exists():
        logger.warning("Profiles config not found: %s", config_path)
        return {"default": _get_default_profile()}

    try:
        with open(path) as f:
            data = yaml.safe_load(f)
            profiles = data.get("profiles", {})
            default_name = data.get("default_profile", "default")
            # Attach default reference
            for name, profile in profiles.items():
                profile["_name"] = name
            return profiles
    except Exception as e:
        logger.error("Failed to load profiles: %s", e)
        return {"default": _get_default_profile()}


def _get_default_profile() -> dict:
    """Default profile when no config found."""
    return {
        "name": "Default",
        "skills": ["Python", "JavaScript", "React", "AWS"],
        "keywords": ["web development", "API", "full stack"],
        "min_hourly_rate": 30,
        "max_hourly_rate": 150,
        "prefer_remote": True,
        "excluded_keywords": [],
        "max_age_hours": 72,
        "_name": "default",
    }


def build_skill_weights(skills: list[str]) -> dict[str, float]:
    """
    Convert skill list to weighted dict for scoring.
    Higher weight for more specialized skills.
    """
    # Base weights - skills listed first get higher weight
    weights = {}
    base_weight = 0.15

    for i, skill in enumerate(skills):
        #递减权重，从0.20开始
        weight = max(0.05, base_weight - (i * 0.01))
        weights[skill] = weight

    return weights


def check_excluded_keywords(job: Job, excluded: list[str]) -> bool:
    """Check if job contains any excluded keywords."""
    if not excluded:
        return False

    text = f"{job.title} {job.description or ''}".lower()
    for keyword in excluded:
        if keyword.lower() in text:
            return True
    return False


def check_salary_range(
    job: Job,
    min_rate: float | None = None,
    max_rate: float | None = None,
) -> bool:
    """Check if job salary is within acceptable range."""
    if min_rate is None and max_rate is None:
        return True

    # Prefer hourly, fallback to any available
    effective_min = job.salary_min
    effective_max = job.salary_max

    # If only fixed budget and no hourly, use average
    if effective_min and not effective_max:
        effective_max = effective_min
    elif effective_max and not effective_min:
        effective_min = effective_max

    if effective_min is None:
        return True  # Can't verify, allow

    if min_rate and effective_min < min_rate:
        return False
    if max_rate and effective_max > max_rate:
        return False

    return True


def check_job_age(posted_at: str | None, max_age_hours: int) -> bool:
    """Check if job is not too old."""
    if not posted_at:
        return True  # Can't verify, allow

    from datetime import datetime, timezone, timedelta

    try:
        # Parse ISO format or various formats
        if "Z" in posted_at:
            job_time = datetime.fromisoformat(posted_at.replace("Z", "+00:00"))
        else:
            job_time = datetime.fromisoformat(posted_at)

        now = datetime.now(timezone.utc)
        age = (now - job_time).total_seconds() / 3600

        return age <= max_age_hours

    except Exception:
        return True  # Can't parse, allow


def _calculate_rules_score(job: Job, profile: dict) -> float:
    """
    Calculate rules-based score (0.0-1.0).
    Applies hard filters first, then soft scores.
    """
    # Remote preference
    if profile.get("prefer_remote", True) and not job.remote:
        return 0.3

    # Salary check - hard filter, not score
    min_rate = profile.get("min_hourly_rate")
    max_rate = profile.get("max_hourly_rate")
    if not check_salary_range(job, min_rate, max_rate):
        return 0.0  # Hard fail

    # Job age check - hard filter
    max_age = profile.get("max_age_hours", 72)
    if not check_job_age(job.posted_at, max_age):
        return 0.0  # Hard fail

    # Excluded keywords - hard filter
    if check_excluded_keywords(job, profile.get("excluded_keywords", [])):
        return 0.0  # Hard fail

    # Keywords match bonus
    keywords = profile.get("keywords", [])
    if keywords:
        text = f"{job.title} {job.description or ''}".lower()
        matched = sum(1 for kw in keywords if kw.lower() in text)
        keyword_score = min(matched / 3, 0.5)  # Max 0.5 for keywords
    else:
        keyword_score = 0.25

    return 0.5 + keyword_score


def _calculate_company_score(job: Job) -> float:
    """Calculate company/client score (0.0-1.0)."""
    # Default to neutral - no client data available
    # Could be enhanced with client rating from platforms
    if job.company:
        return 0.6  # Has company name, give benefit
    return 0.5  # Unknown


def score_job_for_profile(job: Job, profile: dict) -> float:
    """
    Score a job for a specific freelancer profile.
    Returns 0.0-1.0 score.
    """
    # Build skill weights from profile
    skills = profile.get("skills", [])
    skill_weights = build_skill_weights(skills)

    # CV match (40%)
    cv_score, matched = match_cv(job, skill_weights)

    # Rules score (25%)
    rules_score = _calculate_rules_score(job, profile)

    # Seniority score (20%) - based on job complexity indicators
    # Simple heuristic: longer descriptions = more senior
    desc_len = len(job.description or "")
    if desc_len > 2000:
        seniority_score = 0.8
    elif desc_len > 500:
        seniority_score = 0.6
    else:
        seniority_score = 0.4

    # Company score (15%)
    company_score = _calculate_company_score(job)

    # Final weighted score
    final_score = score_job(job, cv_score, rules_score, seniority_score, company_score)

    if final_score > 0:
        logger.debug(
            "Scored job '%s' = %.2f (cv=%.2f, rules=%.2f, seniority=%.2f, company=%.2f)",
            job.title[:40], final_score, cv_score, rules_score, seniority_score, company_score
        )

    return final_score


def score_jobs_for_profile(
    jobs: list[Job],
    profile: dict,
    min_score: float | None = None,
) -> list[tuple[Job, float]]:
    """
    Score a list of jobs for a profile.
    Returns list of (job, score) tuples, sorted by score descending.
    """
    if min_score is None:
        min_score = settings.MIN_SCORE

    scored = []
    for job in jobs:
        score = score_job_for_profile(job, profile)
        if score >= min_score:
            scored.append((job, score))

    # Sort by score descending
    scored.sort(key=lambda x: x[1], reverse=True)

    return scored


def filter_and_score_all_profiles(
    db_path: str,
    profiles_config: str = "./config/profiles.yaml",
    min_score: float | None = None,
    limit: int = 100,
) -> dict[str, list[tuple[Job, float]]]:
    """
    Get jobs from DB and score against all profiles.
    Returns dict of profile_name -> list of (job, score).
    """
    if min_score is None:
        min_score = settings.MIN_SCORE

    # Get unnotified jobs
    jobs_data = get_unnotified_jobs(db_path, min_score=0.0, limit=limit)

    # Convert to Job objects
    from positronica_core.db import Job as JobModel
    jobs = []
    for data in jobs_data:
        job = JobModel(
            url=data["url"],
            title=data["title"],
            source=data["source"],
            company=data.get("company"),
            location=data.get("location"),
            salary_min=data.get("salary_min"),
            salary_max=data.get("salary_max"),
            salary_raw=data.get("salary_raw"),
            description=data.get("description"),
            tags=data.get("tags", []),
            remote=bool(data.get("remote")),
            score=data.get("score", 0.0),
            posted_at=data.get("posted_at"),
        )
        jobs.append(job)

    if not jobs:
        logger.info("No jobs to score")
        return {}

    # Load profiles and score
    profiles = load_profiles(profiles_config)
    results = {}

    for profile_name, profile in profiles.items():
        scored_jobs = score_jobs_for_profile(jobs, profile, min_score)
        if scored_jobs:
            results[profile_name] = scored_jobs
            logger.info("Profile '%s': %d jobs pass threshold", profile_name, len(scored_jobs))

    return results


def update_job_scores(db_path: str, scored_jobs: dict[str, list[tuple[Job, float]]]) -> int:
    """
    Update job scores in database.
    Takes best score for each job across all profiles.
    Returns count of updated jobs.
    """
    import sqlite3

    # Collect best score per job
    job_scores = {}
    for profile_name, jobs_list in scored_jobs.items():
        for job, score in jobs_list:
            url_hash = job.url_hash
            if url_hash not in job_scores or score > job_scores[url_hash]:
                job_scores[url_hash] = score

    if not job_scores:
        return 0

    # Batch update
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")

    updated = 0
    for url_hash, score in job_scores.items():
        cursor = conn.execute(
            "UPDATE jobs SET score = ? WHERE url_hash = ?",
            (score, url_hash)
        )
        updated += cursor.rowcount

    conn.commit()
    conn.close()

    logger.info("Updated scores for %d jobs", updated)
    return updated


# CLI function for testing
def test_scoring():
    """Test scoring with sample job."""
    test_job = Job(
        url="https://example.com/job/123",
        title="Senior Python Developer - FastAPI",
        source="upwork",
        description="Looking for an experienced Python developer to build REST APIs with FastAPI, PostgreSQL, and Docker. Must have experience with AWS and CI/CD pipelines.",
        salary_min=50,
        salary_max=80,
        tags=["Python", "FastAPI", "AWS", "Docker"],
        remote=True,
    )

    profile = _get_default_profile()
    score = score_job_for_profile(test_job, profile)
    print(f"Test job score: {score:.2f}")
    return score > 0.3