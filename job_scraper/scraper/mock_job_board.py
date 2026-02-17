"""Mock job board for testing without hitting real servers."""

import asyncio
from typing import Any

from loguru import logger


class MockJobBoard:
    """Mock job board with hardcoded job data for testing the LLM filter."""

    # 5 deterministic jobs designed to test filter logic:
    # 1. MATCH  - remote, B2B, English, 2+ yrs, high skillset overlap
    # 2. MATCH  - remote EU, no contract mention, English, 1+ yr, good overlap
    # 3. MATCH  - hybrid Warsaw, B2B, English, 3 yrs, high overlap
    # 4. REJECT - on-site only Berlin, employment contract, German required
    # 5. REJECT - remote but 5+ yrs experience required, low skillset overlap (React/frontend)
    JOBS = [
        {
            "title": "Backend Python Engineer",
            "company": "CloudScale",
            "location": "Remote",
            "description": (
                "We are looking for a Backend Python Engineer to join our growing team.\n\n"
                "Requirements:\n"
                "- 2+ years of experience with Python\n"
                "- Proficiency with Django or FastAPI for building REST APIs\n"
                "- PostgreSQL and database design\n"
                "- AWS services (EC2, S3, RDS)\n"
                "- Docker for containerization\n"
                "- Git version control\n\n"
                "Nice to have:\n"
                "- Kubernetes orchestration\n"
                "- CI/CD pipelines\n"
                "- Microservices architecture\n\n"
                "We offer B2B contract. English-speaking team."
            ),
        },
        {
            "title": "Platform Engineer",
            "company": "InfraOps",
            "location": "Remote (EU)",
            "description": (
                "Join our platform team to build and maintain cloud infrastructure.\n\n"
                "What we expect:\n"
                "- 1+ years of professional experience\n"
                "- Python scripting and automation\n"
                "- AWS or GCP cloud platform experience\n"
                "- Kubernetes cluster management\n"
                "- Terraform or CloudFormation for IaC\n"
                "- Linux administration basics\n"
                "- Monitoring tools (Prometheus, Grafana)\n\n"
                "Bonus:\n"
                "- Helm charts\n"
                "- Networking knowledge\n\n"
                "Communication in English."
            ),
        },
        {
            "title": "Python API Developer",
            "company": "FinTech Solutions",
            "location": "Hybrid (Warsaw, Poland)",
            "description": (
                "We need a Python developer to build and maintain our financial APIs.\n\n"
                "Requirements:\n"
                "- 3 years of Python development\n"
                "- FastAPI framework experience\n"
                "- Async programming with asyncio\n"
                "- Docker and Docker Compose\n"
                "- PostgreSQL, Redis\n"
                "- RESTful API design and OpenAPI/Swagger\n\n"
                "We offer:\n"
                "- B2B contract\n"
                "- Hybrid work model (2 days in Warsaw office)\n"
                "- Salary: 18,000 - 25,000 PLN net\n\n"
                "Languages: English (required), Polish (nice to have)."
            ),
        },
        {
            "title": "Senior Backend Developer",
            "company": "Deutsche Finanz AG",
            "location": "On-site, Berlin, Germany",
            "description": (
                "We are hiring a Senior Backend Developer for our Berlin office.\n\n"
                "Requirements:\n"
                "- 3+ years Python backend experience\n"
                "- Django and Django REST Framework\n"
                "- PostgreSQL, Redis\n"
                "- Docker, AWS\n"
                "- CI/CD pipelines\n\n"
                "Important:\n"
                "- Employment contract (Arbeitsvertrag) only\n"
                "- On-site presence required, no remote\n"
                "- German language required (C1 level minimum)\n"
                "- English is a plus"
            ),
        },
        {
            "title": "Senior Frontend Engineer",
            "company": "UIcraft",
            "location": "Remote",
            "description": (
                "Looking for a Senior Frontend Engineer to lead our UI team.\n\n"
                "Requirements:\n"
                "- 5+ years of frontend development\n"
                "- Expert React and TypeScript skills\n"
                "- Modern CSS, Tailwind, styled-components\n"
                "- State management (Redux, Zustand)\n"
                "- REST API consumption\n"
                "- Responsive and accessible design\n\n"
                "Nice to have:\n"
                "- Some Node.js / Express for BFF\n"
                "- GraphQL experience\n\n"
                "English-speaking team. B2B or employment contract available."
            ),
        },
    ]

    def __init__(
        self,
        browser: Any,
        view_duration: int = 20,
    ):
        """Initialize mock job board.

        Args:
            browser: Browser instance (unused in mock)
            view_duration: Seconds to simulate viewing each job
        """
        self.view_duration = view_duration
        self._job_counter = 0

    async def login(self) -> bool:
        """Mock login - no authentication needed for theprotocol.it."""
        logger.info("🎭 MOCK MODE: No login required")
        return True

    async def ensure_logged_in(self) -> bool:
        """Alias for login for compatibility."""
        return await self.login()

    async def navigate_to_jobs(self, search_params: dict[str, Any]) -> None:
        """Mock navigation to jobs page."""
        logger.info(f"🎭 MOCK MODE: Simulating job search with params: {search_params}")
        await asyncio.sleep(0.5)

    async def get_job_links(self, max_jobs: int = 100) -> list[str]:
        """Return hardcoded job links (one per mock job).

        Args:
            max_jobs: Maximum number of job links to return

        Returns:
            List of mock job URLs
        """
        count = min(max_jobs, len(self.JOBS))
        job_links = [
            f"https://example.com/jobs/view/{1000 + i}"
            for i in range(count)
        ]

        logger.info(f"🎭 MOCK MODE: Returning {count} hardcoded job links")
        return job_links

    async def view_job(self, job_url: str) -> dict[str, Any]:
        """Return hardcoded job data by URL index.

        Args:
            job_url: URL of the job posting

        Returns:
            Dictionary with job details
        """
        job_id = int(job_url.split("/")[-1])
        index = job_id - 1000

        if 0 <= index < len(self.JOBS):
            job = self.JOBS[index]
        else:
            return {"url": job_url, "error": f"Mock job not found for index {index}"}

        job_data = {
            "url": job_url,
            "title": job["title"],
            "company": job["company"],
            "location": job["location"],
            "description": job["description"],
        }

        view_time = min(self.view_duration, 3)
        logger.info(f"🎭 Viewing mock job: {job['title']} at {job['company']} ({view_time}s)")
        await asyncio.sleep(view_time)

        self._job_counter += 1
        return job_data
