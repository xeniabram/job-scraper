import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, field_validator


class Event(StrEnum):
    scraped = "scraped"
    matched = "matched"
    rejected = "rejected"
    promoted_manually = "promoted_manually"
    rejected_manually = "rejected_manually"
    applied = "applied"

class JobDataBase(BaseModel):
    description: dict[str, Any]

    @field_validator("description", mode="before")
    @classmethod
    def _parse_json(cls, v: Any) -> Any:
        if isinstance(v, str):
            return json.loads(v)
        return v

class JobData(JobDataBase):
    url: str
    title: str
    company: str

    @property
    def row(self) -> tuple[str, str, str, str]:
        return (self.url, self.title, self.company, json.dumps(self.description))
    

class MatchedJob(JobDataBase):
    url: str
    title: str
    company: str
    match_pct: int = 0
    cv_about: str | None = None
    cv_keywords: str | None = None
    scraped_at: str | None = None


class RejectedJob(JobDataBase):
    url: str
    title: str
    company: str
    match_pct: int = 0
    reason: str = ""
    scraped_at: str | None = None


class DailyStatEntry(BaseModel):
    date: str
    scraped: int = 0
    matched: int = 0
    rejected: int = 0

class DailyStats(BaseModel):
    daily: list[DailyStatEntry]
    totals: DailyStatEntry

