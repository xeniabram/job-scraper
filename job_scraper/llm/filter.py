"""LLM-powered job filtering."""

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger
from openai import AsyncOpenAI
from pydantic import BaseModel, Field


class JobMatch(BaseModel):
    critical_reqs: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    match: bool
    reason: str = Field(description="One sentence explaining the decision.")

    @property
    def skillset_match_percent(self) -> int:
        """Coverage percentage for storage/display — not used for match decision."""
        if not self.critical_reqs:
            return 100
        covered = max(0, len(self.critical_reqs) - len(self.missing))
        return round(covered / len(self.critical_reqs) * 100)


class CvOptimized(BaseModel):
    about_me: str = ""
    keywords: str = ""


class JobFilter:
    """Filter job postings using OpenAI."""

    def __init__(
        self,
        model: str,
        requirements: dict[str, Any],
        api_key: str,
        profile_log: Path | None = None,
    ):
        self.model = model
        self.requirements = requirements
        self.client = AsyncOpenAI(api_key=api_key)
        self.profile_log = profile_log

        self.system_prompt = self._build_prompt_template()

    def _build_prompt_template(self) -> str:
        """Build short, delegating prompt."""
        skillset = self.requirements.get("skillset", {})
        if isinstance(skillset, list):
            strong_skills: list[str] = skillset
            basic_skills: list[str] = []
        else:
            strong_skills = skillset.get("strong", [])
            basic_skills = skillset.get("basic", [])

        years_of_experience = self.requirements.get("years_of_experience", 0)
        target_levels = self.requirements.get("target_levels", [])
        conditions = self.requirements.get("conditions", [])
        excluded_companies = self.requirements.get("excluded_companies", [])

        return f"""You decide if a candidate can realistically pass recruitment for this job.

CANDIDATE:
Strong skills: {", ".join(strong_skills)}
Basic skills (familiar): {", ".join(basic_skills) if basic_skills else "none"}
Experience: {years_of_experience} years
Target levels: {", ".join(target_levels) if target_levels else "any"}
Required conditions: {"; ".join(conditions) if conditions else "none"}
Excluded companies: {", ".join(excluded_companies) if excluded_companies else "none"}

INSTRUCTIONS:
1. critical_reqs — extract only real technical requirements.
   INCLUDE: languages, frameworks, databases, cloud/infra tools, specific platforms.
   EXCLUDE: JSON, XML, REST/HTTP, YAML, PEP8, Agile/Scrum/Jira, soft skills,
   spoken languages, "nice to have"/"plus"/"optional" items,
   vague terms ("clean code", "best practices", "ability to learn").

2. Semantic matching — do not list skills the candidate implicitly has:
   Python → REST basics, HTTP, pip, basic Linux, YAML
   FastAPI/Django → ORM, HTTP verbs
   Docker → containers, images, basic networking
   Apply similar logic for comparable stacks.

3. missing = items from critical_reqs the candidate lacks. Must be a strict subset of critical_reqs.

4. match = true only when ALL hold:
   • missing is empty
   • job's seniority is within target levels (reject Senior-only roles)
   • all required conditions are satisfied
   • company is not excluded

5. reason — one sentence with the key deciding factor.

Return ONLY valid JSON."""
    

    async def filter_job(self, job_data: dict[str, Any]) -> JobMatch:
        """Filter a job posting using the LLM.

        Args:
            job_data: Job data with title, company, description, etc.

        Returns:
            Dictionary with match result, skillset %, reason, etc.
        """
        if "error" in job_data:
            return JobMatch(
                match=False,
                reason=f"Could not analyze job: {job_data['error']}",
            )
        contracts = job_data.get("contracts", [])
        salary = (
            "; ".join(
                f"{c.get('salary', '')} {c.get('units', '')} {c.get('period', '')} | {c.get('type', '')}".strip()
                for c in contracts
            )
            if contracts
            else "not specified"
        )

        prompt_payload = {
            "job": {
                "title": job_data.get("title"),
                "company": job_data.get("company"),
                "location": job_data.get("location"),
                "seniority": job_data.get("seniority"),
                "work_mode": job_data.get("work_mode"),
                "salary": salary,
                "technologies_required": job_data.get("technologies", []),
                "technologies_optional": job_data.get("technologies_optional", []),
                "requirements": job_data.get("requirements", []),
                "nice_to_have": job_data.get("requirements_optional", []),
                "responsibilities": job_data.get("responsibilities", []),
            }
        }
        
        logger.debug(f"Filtering job: {job_data.get('title', 'Unknown')}")

        t0 = time.perf_counter()
        response = await self.client.responses.parse(
            model=self.model,
            input=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": json.dumps(prompt_payload)},
            ],
            text_format=JobMatch,
        )
        duration = time.perf_counter() - t0

        if self.profile_log is not None:
            usage = getattr(response, "usage", None)
            entry = {
                "ts": datetime.now(UTC).isoformat(),
                "job": job_data.get("title", ""),
                "company": job_data.get("company", ""),
                "model": self.model,
                "duration_s": round(duration, 3),
                "input_tokens": getattr(usage, "input_tokens", None),
                "output_tokens": getattr(usage, "output_tokens", None),
            }
            with self.profile_log.open("a") as f:
                f.write(json.dumps(entry) + "\n")

        if response.output_parsed is None:
            logger.warning("Could not parse LLM response, defaulting to reject")
            logger.warning(response.output)
            return JobMatch(
                match=False,
                reason="Could not parse LLM response",
            )

        result = response.output_parsed

        logger.info(
            f"Job '{job_data.get('title', 'Unknown')}': "
            f"{'MATCH' if result.match else 'REJECT'} "
            f"(critical: {result.critical_reqs} | missing: {result.missing} | {result.reason})"
        )
        return result

    async def optimize_cv(
        self,
        job_data: dict[str, Any],
        cv_config: Any,  # CvOptimizationConfig
    ) -> CvOptimized:
        """Rewrite CV sections to maximize keyword overlap with a specific job.

        Detects the job's language and selects the matching base CV section.

        Args:
            job_data: Scraped job data dict.
            cv_config: CvOptimizationConfig with base about_me and keywords per language.

        Returns:
            CvOptimized with rewritten about_me and keywords in the job's language.
        """
        # Detect language: Polish diacritics in requirements/title → Polish
        probe = " ".join(
            [job_data.get("title", "")]
            + (job_data.get("requirements") or [])[:3]
        )
        is_polish = any(c in probe for c in "ąęóśźżćńłĄĘÓŚŹŻĆŃŁ")
        base = cv_config.pl if is_polish else cv_config.en
        lang_label = "Polish" if is_polish else "English"

        system_prompt = f"""You are a CV optimization engine. You rewrite CV sections to maximize
keyword overlap with a specific job posting while staying strictly truthful
(do not invent skills or experiences not present in the base text).

The job post is in {lang_label}. Write your output in {lang_label}.

Rules:
1. Reorder and rephrase sentences so the most relevant technologies and
   responsibilities appear first.
2. Replace generic phrasing with job-specific terminology where the meaning
   is identical (e.g. "messaging systems" → "RabbitMQ / NATS" if those are
   in the base text).
3. Add keywords from the job.
4. Keep the about_me to roughly the same length as the input (±20%).
5. Append any newly incorporated technical keywords to the keywords string
   (comma-separated, no duplicates).
Return ONLY valid JSON."""

        payload = {
            "job": {
                "title": job_data.get("title"),
                "company": job_data.get("company"),
                "technologies_required": job_data.get("technologies", []),
                "technologies_optional": job_data.get("technologies_optional", []),
                "requirements": job_data.get("requirements", []),
                "responsibilities": job_data.get("responsibilities", []),
            },
            "base_cv": {
                "about_me": base.about_me,
                "keywords": base.keywords,
            },
        }

        response = await self.client.responses.parse(
            model=self.model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(payload)},
            ],
            text_format=CvOptimized,
        )

        if response.output_parsed is None:
            logger.warning("Could not parse CV optimization response, returning base CV")
            return CvOptimized(about_me=base.about_me, keywords=base.keywords)

        logger.debug(f"CV optimized for: {job_data.get('title', 'Unknown')} ({lang_label})")
        return response.output_parsed