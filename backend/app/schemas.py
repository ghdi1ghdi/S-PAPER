from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator


class Schedule(BaseModel):
    kind: Literal["daily", "weekly", "hours", "days"] = "daily"
    time: str = "09:00"
    weekday: int = Field(0, ge=0, le=6)
    interval: int = Field(1, ge=1, le=365)

    @field_validator("time")
    @classmethod
    def valid_time(cls, value):
        datetime.strptime(value, "%H:%M")
        if len(value) != 5:
            raise ValueError("HH:MM 형식")
        return value


class SearchOptions(BaseModel):
    sort: Literal["auto", "relevance", "recent"] = "auto"
    year_from: int | None = Field(None, ge=1500, le=2200)
    year_to: int | None = Field(None, ge=1500, le=2200)
    overlap_days: int = Field(30, ge=1, le=365)

    @model_validator(mode="after")
    def dates(self):
        if self.year_from and self.year_to and self.year_from > self.year_to:
            raise ValueError("시작 연도가 종료 연도보다 큽니다")
        return self


class SubscriptionInput(BaseModel):
    topic: str = Field(min_length=1, max_length=500)
    keywords: list[str] = Field(default_factory=list, max_length=50)
    enabled_sources: list[Literal["google_scholar", "arxiv"]] = Field(default_factory=lambda: ["google_scholar", "arxiv"], min_length=1)
    queries: dict[Literal["google_scholar", "arxiv"], str] = Field(default_factory=dict)
    schedule: Schedule = Field(default_factory=Schedule)
    timezone: str = "Asia/Seoul"
    papers_per_cycle: int = Field(10, ge=1, le=100)
    search_options: SearchOptions = Field(default_factory=SearchOptions)

    @field_validator("topic")
    @classmethod
    def topic_clean(cls, v):
        if not v.strip():
            raise ValueError("주제 필요")
        return v.strip()

    @field_validator("keywords")
    @classmethod
    def keywords_clean(cls, values):
        out = []
        for v in values:
            v = " ".join(v.split())
            if len(v) > 200:
                raise ValueError("키워드 최대 200자")
            if v and v.casefold() not in [x.casefold() for x in out]:
                out.append(v)
        return out

    @field_validator("queries")
    @classmethod
    def queries_clean(cls, v):
        if any(len(x) > 2000 for x in v.values()):
            raise ValueError("검색어 최대 2000자")
        return {k: x.strip() for k, x in v.items() if x.strip()}

    @field_validator("timezone")
    @classmethod
    def timezone_valid(cls, v):
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("유효한 IANA 시간대가 필요합니다")
        return v


class SummaryData(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    research_question: str | None
    methods: str | None
    key_findings: list[str]
    limitations: list[str]
    takeaway: str | None

    def readable(self):
        parts = [("연구 목적", self.research_question), ("방법", self.methods),
                 ("결과", " ".join(self.key_findings)), ("한계", " ".join(self.limitations)), ("핵심", self.takeaway)]
        return "\n".join(f"{k}: {v}" for k, v in parts if v)
