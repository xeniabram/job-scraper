"""LLM-powered job filtering."""

import json
from typing import Any

from loguru import logger
from openai import AsyncOpenAI
from pydantic import BaseModel, Field


class JobMatch(BaseModel):
    job_keywords: list[str] = Field(default_factory=list)
    matched_keywords: list[str] = Field(default_factory=list)
    unmatched_keywords: list[str] = Field(default_factory=list)
    match: bool
    skillset_match_percent: int = 0
    reason: str


class JobFilter:
    """Filter job postings using OpenAI."""

    def __init__(
        self,
        model: str,
        requirements: dict[str, Any],
        api_key: str,
    ):
        """Initialize job filter.

        Args:
            model: OpenAI model name (e.g., 'gpt-4o-mini', 'gpt-4o')
            requirements: Job requirements from config
            api_key: OpenAI API key
        """
        self.model = model
        self.requirements = requirements
        self.client = AsyncOpenAI(api_key=api_key)
        self.min_skillset_match = requirements.get("min_skillset_match", 70)

        self.system_prompt = self._build_prompt_template()

    def _build_prompt_template(self) -> str:
        """Build compact deterministic prompt."""
        skillset = self.requirements.get("skillset", [])
        years_of_experience = self.requirements.get("years_of_experience", 0)
        target_titles = self.requirements.get("target_titles", [])
        target_levels = self.requirements.get("target_levels", [])
        conditions = self.requirements.get("conditions", [])
        excluded_companies = self.requirements.get("excluded_companies", [])

        return f"""
        You are a deterministic job filtering engine.

        CANDIDATE PROFILE:
        Skills: {", ".join(skillset)}
        Experience: {years_of_experience} years
        Target titles: {", ".join(target_titles) if target_titles else "any"}
        Target levels: {", ".join(target_levels) if target_levels else "any"}
        Additional required conditions: {", ".join(conditions) if conditions else "none"}
        Excluded companies: {", ".join(excluded_companies) if excluded_companies else "none"}

        RULES:

        1) Extract only technical skills/tools/frameworks from the job.
        Exclude location, contract type, soft skills, spoken languages, vague phrases.

        2) Perform semantic matching.
        Technologies from the same ecosystem count as related.

        3) matched_keywords MUST be a strict subset of job_keywords.
        Never invent new keywords.

        4) ALL candidate conditions are mandatory.
        If ANY condition fails → match=false.

        5) Reject if:
        - required experience > candidate experience
        - job title clearly outside target titles
        - company is excluded

        Return ONLY valid JSON.
        """
    

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
                skillset_match_percent=0,
                reason=f"Could not analyze job: {job_data['error']}"
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

        response = await self.client.responses.parse(
            model=self.model,
            input=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": json.dumps(prompt_payload)},
            ],
            text_format=JobMatch,
        )

        if response.output_parsed is None:
            logger.warning("Could not parse LLM response, defaulting to reject")
            logger.warning(response.output)
            return JobMatch(
                match=False,
                reason="Could not parse LLM response",
            )

        result = response.output_parsed


        # Calculate match percentage from keyword lists
        total = len(result.job_keywords)
        covered = len(result.matched_keywords)
        if covered > total:
            logger.warning(
                f"LLM returned {covered} matched keywords but only {total} job keywords — capping"
            )
            covered = total
        pct = round(covered / total * 100) if total > 0 else 0
        result.skillset_match_percent = pct

        # Enforce minimum skillset threshold
        if pct < self.min_skillset_match:
            result.match = False
            result.reason = (
                f"Skillset match {pct}% below {self.min_skillset_match}% threshold. "
                f"{result.reason}"
            )

        logger.info(
            f"Job '{job_data.get('title', 'Unknown')}': "
            f"{'MATCH' if result.match else 'REJECT'} "
            f"(skillset: {pct}% [{covered}/{total}] | "
            f"covered: {result.matched_keywords} | "
            f"gaps: {result.unmatched_keywords})"
        )
        return result