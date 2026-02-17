"""LLM-powered job filtering."""

import json
from typing import Any

import ollama
from loguru import logger


class JobFilter:
    """Filter job postings using local LLM."""

    def __init__(
        self,
        model: str,
        requirements: dict[str, Any],
        host: str,
    ):
        """Initialize job filter.

        Args:
            model: Ollama model name (e.g., 'llama3.2:latest', 'llama2')
            requirements: Job requirements from config
            host: Ollama API host
        """
        self.model = model
        self.requirements = requirements
        self.client = ollama.Client(host=host)
        self.min_skillset_match = requirements.get("min_skillset_match", 70)

        self._build_prompt_template()

    def _build_prompt_template(self) -> None:
        """Build the prompt template from requirements."""
        skillset = self.requirements.get("skillset", [])
        years_of_experience = self.requirements.get("years_of_experience", 0)
        target_titles = self.requirements.get("target_titles", [])
        target_levels = self.requirements.get("target_levels", [])
        conditions = self.requirements.get("conditions", [])
        excluded_companies = self.requirements.get("excluded_companies", [])

        skillset_section = "\n".join(f"- {skill}" for skill in skillset)
        titles_section = ", ".join(target_titles) if target_titles else "any"
        levels_section = ", ".join(target_levels) if target_levels else "any"
        conditions_section = "\n".join(f"- {cond}" for cond in conditions)

        # Build excluded companies section
        if excluded_companies:
            excluded_section = "\n".join(f"- {company}" for company in excluded_companies)
            excluded_check = f"""
Company exclusion check: REJECT if the company name matches or contains any of these (case-insensitive):
{excluded_section}
"""
        else:
            excluded_check = ""

        self.prompt_template = f"""You are a job filter assistant. Follow each step precisely.

=== STEP 1: TOKENIZE THE JOB POSTING ===
Extract every technical skill, tool, technology, methodology, and framework from the job posting as a flat keyword list.
Include: programming languages, frameworks, tools, platforms, practices, methodologies.
Example output: ["Python", "Django REST Framework", "PostgreSQL", "AWS", "CI/CD", "Agile"]

=== STEP 2: SKILLSET MATCHING ===
The candidate has ALL of these skills (each line is a separate skill they possess):
{skillset_section}

For each keyword from Step 1, check if ANY candidate skill is semantically related.
Use intelligent matching — skills in the same technology ecosystem count as related.

Examples of smart matching:
- Candidate has "Python" → matches: Python 3.x, PEP8, pip, Flask, type hints, Celery, asyncio
- Candidate has "Docker/Kubernetes" → matches: containers, Docker Compose, K8s, pods
- Candidate has "AWS" → matches: EC2, S3, Lambda
- Candidate has "FastAPI or Django" → matches: Django REST Framework, Pydantic, ASGI, WSGI
- Candidate has "Backend development" → matches: REST API, microservices, server-side, API design, backend
- Scrum ↔ Agile ↔ Kanban (same methodology family)
- SQL ↔ PostgreSQL ↔ MySQL ↔ databases (same domain)

Mark each job keyword as COVERED or NOT COVERED.

=== STEP 3: CHECK ALL CONDITIONS ===
ALL of the following must be satisfied. If ANY fails, reject the job and explain which condition failed.
{excluded_check}
Experience: the candidate has {years_of_experience} years. If the job requires MORE, reject.
If the job posting does not mention experience requirements, it passes this check.

Job scope: target titles are [{titles_section}], target levels are [{levels_section}].
If the job title or role clearly does not match any target title, reject.
However, if no seniority level is mentioned in the posting, the job still passes this check.

Additional conditions:
{conditions_section}

=== JOB POSTING ===
Title: {{title}}
Company: {{company}}
Location: {{location}}
Seniority: {{seniority}}
Work mode: {{work_mode}}
Salary: {{salary}}
Technologies (required): {{technologies}}
Technologies (optional): {{technologies_optional}}
Requirements:
{{requirements}}
Nice-to-have:
{{requirements_optional}}
Responsibilities:
{{responsibilities}}

=== RESPOND WITH ONLY THIS JSON, NO OTHER TEXT ===
{{{{
  "job_keywords": ["keyword1", "keyword2"],
  "matched_keywords": ["keyword1"],
  "unmatched_keywords": ["keyword2"],
  "match": true or false,
  "reason": "human readable explanation of the decision"
}}}}"""

    async def filter_job(self, job_data: dict[str, Any]) -> dict[str, Any]:
        """Filter a job posting using the LLM.

        Args:
            job_data: Job data with title, company, description, etc.

        Returns:
            Dictionary with match result, skillset %, reason, etc.
        """
        if "error" in job_data:
            return {
                "match": False,
                "skillset_match_percent": 0,
                "reason": f"Could not analyze job: {job_data['error']}",
            }

        contracts = job_data.get("contracts", [])
        salary = (
            "; ".join(
                f"{c.get('salary', '')} {c.get('units', '')} {c.get('period', '')} | {c.get('type', '')}".strip()
                for c in contracts
            )
            if contracts
            else "not specified"
        )

        def fmt_list(items: list[str]) -> str:
            return "\n".join(f"  - {i}" for i in items) if items else "  none"

        prompt = self.prompt_template.format(
            title=job_data.get("title", "Unknown"),
            company=job_data.get("company", "Unknown"),
            location=job_data.get("location", "Unknown"),
            seniority=job_data.get("seniority", "not specified"),
            work_mode=job_data.get("work_mode", "not specified"),
            salary=salary,
            technologies=", ".join(job_data.get("technologies", [])) or "not specified",
            technologies_optional=", ".join(job_data.get("technologies_optional", [])) or "none",
            requirements=fmt_list(job_data.get("requirements", [])),
            requirements_optional=fmt_list(job_data.get("requirements_optional", [])),
            responsibilities=fmt_list(job_data.get("responsibilities", [])),
        )

        try:
            logger.debug(f"Filtering job: {job_data.get('title', 'Unknown')}")

            response = self.client.chat(  # pyright: ignore[reportUnknownMemberType]
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                stream=False,
                options={"temperature": 0.1},
            )

            content = response["message"]["content"]

            start_idx = content.find("{")
            end_idx = content.rfind("}") + 1

            if start_idx != -1 and end_idx > start_idx:
                json_str = content[start_idx:end_idx]
                result = json.loads(json_str)

                if "match" in result and "reason" in result:
                    result.setdefault("job_keywords", [])
                    result.setdefault("matched_keywords", [])
                    result.setdefault("unmatched_keywords", [])

                    # Calculate match percentage from keyword lists
                    total = len(result["job_keywords"])
                    covered = len(result["matched_keywords"])
                    pct = round(covered / total * 100) if total > 0 else 0
                    result["skillset_match_percent"] = pct

                    # Enforce minimum skillset threshold
                    if pct < self.min_skillset_match:
                        result["match"] = False
                        result["reason"] = (
                            f"Skillset match {pct}% below {self.min_skillset_match}% threshold. "
                            f"{result['reason']}"
                        )

                    logger.info(
                        f"Job '{job_data.get('title', 'Unknown')}': "
                        f"{'MATCH' if result['match'] else 'REJECT'} "
                        f"(skillset: {pct}% [{covered}/{total}] | "
                        f"covered: {result['matched_keywords']} | "
                        f"gaps: {result['unmatched_keywords']})"
                    )
                    return result

            logger.warning("Could not parse LLM response, defaulting to reject")
            return {
                "match": False,
                "skillset_match_percent": 0,
                "reason": "Could not parse LLM response",
            }

        except Exception as e:
            logger.error(f"Error filtering job: {e}")
            return {
                "match": False,
                "skillset_match_percent": 0,
                "reason": f"LLM error: {str(e)}",
            }

    def check_model_available(self) -> bool:
        """Check if the specified model is available in Ollama.

        Returns:
            True if model is available, False otherwise
        """
        try:
            models = self.client.list()
            available_models = [m.model for m in models.models]

            for available in available_models:
                if available and self.model in available:
                    logger.info(f"Model '{self.model}' is available")
                    return True

            logger.warning(f"Model '{self.model}' not found. Available models: {available_models}")
            logger.info(f"You can download it with: ollama pull {self.model}")
            return False

        except Exception as e:
            logger.error(f"Could not connect to Ollama: {e}")
            logger.info("Make sure Ollama is running: https://ollama.ai")
            return False
