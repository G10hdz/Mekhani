"""Docs generator - creates Google Docs and local markdown exports."""
import logging
import json
from pathlib import Path
from typing import Optional, Tuple
from datetime import datetime

from positronica_core.config import settings

logger = logging.getLogger(__name__)


class DocsGenerator:
    """Creates Google Docs with proposals and Mermaid diagrams."""

    def __init__(
        self,
        credentials_path: Optional[str] = None,
        output_dir: str = "./outputs/proposals",
    ):
        """Initialize docs generator."""
        self.credentials_path = credentials_path or settings.GOOGLE_DOCS_CREDENTIALS_JSON
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._service = None

    def _get_service(self):
        """Lazy-load Google Docs service."""
        if self._service is not None:
            return self._service

        # Check if credentials exist
        creds_path = Path(self.credentials_path)
        if not creds_path.exists():
            logger.warning("Google Docs credentials not found: %s", self.credentials_path)
            return None

        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build

            # Load token if exists
            token_path = Path(self.credentials_path).parent / "token.json"
            if token_path.exists():
                creds = Credentials.from_authorized_user_info(
                    json.loads(token_path.read_text()),
                    scopes=[
                        "https://www.googleapis.com/auth/documents",
                        "https://www.googleapis.com/auth/drive.file",
                    ],
                )
            else:
                # Would need OAuth flow here - for now return None
                logger.warning("Token not found, OAuth required")
                return None

            self._service = build("docs", "v1", credentials=creds)
            return self._service

        except ImportError:
            logger.warning("google-api-python-client not installed")
            return None
        except Exception as e:
            logger.error("Failed to initialize Google Docs service: %s", e)
            return None

    def _build_mermaid_diagram(self, job_title: str, skills: list[str]) -> str:
        """Build Mermaid flowchart for job breakdown."""
        skill_list = ", ".join(skills[:6])

        diagram = f"""```mermaid
flowchart TD
    A[<b>Job Proposal</b><br/>{job_title[:30]}...] --> B[<b>Key Skills</b><br/>{skill_list}]
    B --> C[<b>Approach</b><br/>Solution Design]
    B --> D[<b>Timeline</b><br/>Est. Delivery]
    B --> E[<b>Value</b><br/>Business Impact]
    
    style A fill:#1a1a2e,stroke:#16213e,color:#fff
    style B fill:#16213e,stroke:#0f3460,color:#fff
    style C fill:#0f3460,stroke:#e94560,color:#fff
    style D fill:#0f3460,stroke:#e94560,color:#fff
    style E fill:#0f3460,stroke:#e94560,color:#fff
```"""
        return diagram

    def _build_proposal_content(
        self,
        job_title: str,
        proposal: str,
        profile_name: str,
        skills: list[str],
    ) -> list[dict]:
        """Build document content structure for Google Docs API."""
        import textwrap

        # Wrap proposal text
        wrapped_proposal = textwrap.fill(proposal, width=80)

        content = [
            # Title
            {
                "insertText": {
                    "location": {"index": 1},
                    "text": f"Proposal: {job_title}\n\n",
                }
            },
            # Title styling
            {
                "updateTextStyle": {
                    "textStyle": {
                        "bold": True,
                        "fontSize": {"magnitude": 18, "unit": "PT"},
                    },
                    "range": {"startIndex": 1, "endIndex": len(f"Proposal: {job_title}\n\n")},
                }
            },
            # Profile info
            {
                "insertText": {
                    "location": {"index": 1},
                    "text": f"Profile: {profile_name}\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n",
                }
            },
            # Skills section
            {
                "insertText": {
                    "location": {"index": 1},
                    "text": f"Matching Skills: {', '.join(skills[:8])}\n\n",
                }
            },
            # Proposal body
            {
                "insertText": {
                    "location": {"index": 1},
                    "text": f"\n{wrapped_proposal}\n\n",
                }
            },
            # Mermaid diagram
            {
                "insertText": {
                    "location": {"index": 1},
                    "text": "\n## Approach Diagram\n\n",
                }
            },
            {
                "insertText": {
                    "location": {"index": 1},
                    "text": self._build_mermaid_diagram(job_title, skills),
                }
            },
        ]

        return content

    def create_doc(
        self,
        job_title: str,
        proposal: str,
        profile_name: str,
        skills: list[str],
    ) -> dict:
        """
        Create a Google Doc with the proposal.

        Args:
            job_title: Title of the job
            proposal: Full proposal text
            profile_name: Freelancer profile name
            skills: List of relevant skills

        Returns:
            dict with keys: success (bool), doc_id (str), doc_url (str), error (str)
        """
        service = self._get_service()
        if not service:
            # Fall back to local markdown export
            return self._export_markdown(job_title, proposal, profile_name, skills)

        try:
            # Create document
            doc = service.documents().create(body={"title": f"Proposal: {job_title}"}).execute()
            doc_id = doc.get("documentId")
            doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"

            # Build content
            content = self._build_proposal_content(job_title, proposal, profile_name, skills)

            # Apply content (batching would be better but API is simple here)
            for req in content[:4]:  # Limit to avoid complex batch
                try:
                    service.documents().batchUpdate(
                        documentId=doc_id,
                        body={"requests": [req]}
                    )
                except Exception as e:
                    logger.warning("Content update failed: %s", e)

            logger.info("Created Google Doc: %s", doc_url)
            return {
                "success": True,
                "doc_id": doc_id,
                "doc_url": doc_url,
            }

        except Exception as e:
            logger.error("Failed to create Google Doc: %s", e)
            # Fall back to markdown
            return self._export_markdown(job_title, proposal, profile_name, skills)

    def _export_markdown(
        self,
        job_title: str,
        proposal: str,
        profile_name: str,
        skills: list[str],
    ) -> dict:
        """
        Export proposal as local markdown file (fallback).
        """
        import re

        # Sanitize filename
        safe_title = re.sub(r'[^\w\s-]', '', job_title)[:50]
        safe_title = re.sub(r'\s+', '_', safe_title)
        filename = f"{profile_name}_{safe_title}_{datetime.now().strftime('%Y%m%d')}.md"

        filepath = self.output_dir / filename

        content = f"""# Proposal: {job_title}

**Profile:** {profile_name}
**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}

## Matching Skills
{', '.join(skills[:8])}

## Proposal

{proposal}

---

## Approach

{self._build_mermaid_diagram(job_title, skills)}

---
*Generated by Mekhani - Multi-platform Freelance Job Automation*
"""

        try:
            filepath.write_text(content, encoding="utf-8")
            logger.info("Exported markdown: %s", filepath)
            return {
                "success": True,
                "doc_id": None,
                "doc_url": str(filepath),
                "local_path": str(filepath),
            }
        except Exception as e:
            logger.error("Failed to export markdown: %s", e)
            return {
                "success": False,
                "error": str(e),
            }

    def create_batch(self, proposals: list[dict]) -> list[dict]:
        """Create docs for multiple proposals."""
        results = []
        for prop in proposals:
            result = self.create_doc(
                job_title=prop.get("job_title", "Untitled"),
                proposal=prop.get("proposal", ""),
                profile_name=prop.get("profile_name", "default"),
                skills=prop.get("skills", []),
            )
            results.append(result)
        return results


# CLI test
def test_docs():
    """Test docs generation."""
    generator = DocsGenerator()

    result = generator.create_doc(
        job_title="Senior Python Developer",
        proposal="I am an experienced Python developer with 5+ years of experience...",
        profile_name="default",
        skills=["Python", "FastAPI", "PostgreSQL", "Docker"],
    )

    print(f"Success: {result.get('success')}")
    if result.get("doc_url"):
        print(f"Doc URL: {result['doc_url']}")

    return result.get("success", False)