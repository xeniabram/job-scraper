import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, field_validator


class Event(StrEnum):
        applied="applied"
        interview="interview"
        offer="offer"
        reject="reject"

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

class JobEvent(BaseModel):
    id: int
    date: str
    event: Event
    url: str
    title: str
    company: str


class JobWithEvents(BaseModel):
    url: str
    title: str
    company: str
    latest_event_date: str
    events: list[JobEvent]