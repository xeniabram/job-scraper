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
    job_keywords: list[str] = Field(default_factory=list)
    matched_keywords: list[str] = Field(default_factory=list)
    unmatched_keywords: list[str] = Field(default_factory=list)
    match: bool
    skillset_match_percent: int = 0
    reason: str = Field(description="One concise sentence explaining the decision.")


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
        self.min_skillset_match = requirements.get("min_skillset_match", 70)
        self.profile_log = profile_log

        self.system_prompt = self._build_prompt_template()

    def _build_prompt_template(self) -> str:
        """Build compact deterministic prompt."""
        skillset = self.requirements.get("skillset", {})
        # Support both legacy flat list and new {strong, basic} dict formats
        if isinstance(skillset, list):
            strong_skills: list[str] = skillset
            basic_skills: list[str] = []
        else:
            strong_skills = skillset.get("strong", [])
            basic_skills = skillset.get("basic", [])

        years_of_experience = self.requirements.get("years_of_experience", 0)
        target_titles = self.requirements.get("target_titles", [])
        target_levels = self.requirements.get("target_levels", [])
        conditions = self.requirements.get("conditions", [])
        excluded_companies = self.requirements.get("excluded_companies", [])

        return f"""
You are a professional recruiter evaluating candidate fit. Use holistic judgment — not mechanical keyword counting.

CANDIDATE PROFILE:
Strong skills (expert level): {", ".join(strong_skills)}
Basic skills (familiar with, entry-level): {", ".join(basic_skills) if basic_skills else "none"}
Experience: {years_of_experience} years
Target titles: {", ".join(target_titles) if target_titles else "any"}
Target levels: {", ".join(target_levels) if target_levels else "any"}
Mandatory conditions: {", ".join(conditions) if conditions else "none"}
Excluded companies: {", ".join(excluded_companies) if excluded_companies else "none"}

STEP 1 — Extract non-trivial technical requirements into job_keywords.
Include: specific technologies, frameworks, tools, platforms, languages.
Exclude from job_keywords entirely:
  - Soft skills, spoken languages, location, contract type, vague phrases.
  - Ecosystem fundamentals implied by the candidate's existing stack.
    A Python developer implicitly knows: JSON, XML, REST/HTTP basics, PEP8, type hints, pip, virtualenv, basic Linux/shell, YAML, SQL syntax basics.
    A FastAPI/Django developer implicitly knows: MVC/MVT pattern, ORM concepts, HTTP verbs, middleware.
    Docker knowledge implies: containers, images, basic networking.
    Use common sense for similar cases.
  - Anything framed as "open to learn", "willing to learn", "would be a plus", "nice to have", "not required", "advantageous". These are not requirements.

STEP 2 — For each job_keyword decide whether the job asks for full proficiency or just familiarity:
  FULL        — "advanced", "strong", "expert", "extensive", "deep knowledge", "good knowledge",
                "practical/commercial experience", "proficient", or no qualifier at all.
  FAMILIARITY — "familiarity", "basic knowledge", "hands-on", "exposure to", "understanding of", "introductory".

STEP 3 — Match candidate skills:
  FULL requirement:        only STRONG candidate skills count as matched.
  FAMILIARITY requirement: both STRONG and BASIC candidate skills count as matched.

  matched_keywords must be a strict subset of job_keywords. Never invent keywords.

STEP 4 — Identify hard blockers.
A keyword is a hard blocker when ALL of these are true:
  1. It appears in job_keywords (not excluded in Step 1).
  2. The job demands it at FULL level.
  3. The candidate does not have it as a strong skill and it is not implied by their stack.
  4. It is a specialized technology that cannot be picked up quickly on the job.
If any hard blocker exists → match=false.

STEP 5 — Apply mandatory conditions:
  - If any mandatory condition is not satisfied → match=false.
  - If required experience clearly exceeds candidate's {years_of_experience} years → match=false.
  - If company is in the excluded list → match=false.
  - If job title is clearly outside target titles → match=false.

STEP 6 — Compute skillset_match_percent as: len(matched_keywords) / len(job_keywords) * 100.

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