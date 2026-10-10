from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Claim(Strict):
    worker_id: str = Field(min_length=1, max_length=100)
    lane: Literal["fast", "ai", "delivery"]


class Intent(Strict):
    kind: Literal["statistics", "attempt", "clarify"]
    scope: Literal["week", "month", "last_training", "current", "progress", "grades", "locations", "projects", "records"] = "week"
    date_from: date | None = None
    date_to: date | None = None
    grade: str | None = Field(default=None, max_length=30)
    name: str | None = Field(default=None, max_length=200)
    reached_top: bool | None = None
    clean_ascent: bool | None = None
    falls: int | None = Field(default=None, ge=0, le=1000)
    hangs: int | None = Field(default=None, ge=0, le=1000)
    style: Literal["onsight", "flash", "redpoint", "unknown"] = "unknown"
    belay: Literal["lead", "top_rope", "auto_belay", "bouldering", "unknown"] = "unknown"
    attempts: int = Field(default=1, ge=1, le=100)
    notes: str | None = Field(default=None, max_length=1000)
    is_test: bool = False
    continue_current_route: bool = False
    question: str | None = Field(default=None, max_length=500)


class Completion(Strict):
    worker_id: str = Field(min_length=1, max_length=100)
    intent: Intent | None = None
    tokens: int = Field(default=0, ge=0)
    telegram_message_id: int | None = Field(default=None, ge=1)


class Failure(Strict):
    worker_id: str = Field(min_length=1, max_length=100)
    code: str = Field(pattern=r"^[a-z0-9_]{1,80}$")
    retry_seconds: int = Field(default=0, ge=0, le=3600)


class TestMode(Strict):
    enabled: bool


class AttemptPatch(Strict):
    expected_version: int = Field(ge=1)
    reached_top: bool | None = None
    clean_ascent: bool | None = None
    falls: int | None = Field(default=None, ge=0)
    hangs: int | None = Field(default=None, ge=0)
    style: Literal["onsight", "flash", "redpoint", "unknown"] | None = None
    belay: Literal["lead", "top_rope", "auto_belay", "bouldering", "unknown"] | None = None
    notes: str | None = Field(default=None, max_length=1000)
    is_test: bool | None = None


class TrainingPatch(Strict):
    expected_version: int = Field(ge=1)
    duration_minutes: int | None = Field(default=None, ge=1)
    environment: Literal["indoor", "outdoor", "unknown"] | None = None
    physical_state: str | None = Field(default=None, max_length=1000)
    notes: str | None = Field(default=None, max_length=2000)


class GearWrite(Strict):
    type: Literal["shoes", "rope", "harness", "belay_device", "helmet", "chalk", "other"]
    brand: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=100)
    size: str | None = Field(default=None, max_length=50)
    notes: str | None = Field(default=None, max_length=1000)
    active: bool = True


class LocationWrite(Strict):
    name: str = Field(min_length=1, max_length=200)
    country: str | None = Field(default=None, max_length=200)
    type: Literal["gym", "outdoor"] = "outdoor"


class SectionWrite(Strict):
    location_id: str
    name: str = Field(min_length=1, max_length=200)


class RouteWrite(Strict):
    section_id: str
    name: str = Field(min_length=1, max_length=200)
    grade: str | None = Field(default=None, max_length=30)


class GearPatch(Strict):
    brand: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=100)
    size: str | None = Field(default=None, max_length=50)
    notes: str | None = Field(default=None, max_length=1000)
    active: bool | None = None


class CatalogPatch(Strict):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    grade: str | None = Field(default=None, max_length=30)
    country: str | None = Field(default=None, max_length=200)


class SummaryCreate(Strict):
    date: date
    routes: list["SummaryAttempt"] = Field(min_length=1, max_length=100)
    location_id: str | None = None
    section_id: str | None = None
    duration_minutes: int | None = Field(default=None, ge=1)
    notes: str | None = Field(default=None, max_length=2000)
    merge_into_active: bool = False
    expected_version: int | None = Field(default=None, ge=1)


class SummaryAttempt(Strict):
    name: str = Field(min_length=1, max_length=200)
    grade: str | None = Field(default=None, max_length=30)
    route_id: str | None = None
    attempts: int = Field(default=1, ge=1)
    reached_top: bool | None = None
    clean_ascent: bool | None = None
    falls: int | None = Field(default=None, ge=0)
    hangs: int | None = Field(default=None, ge=0)
    style: Literal["onsight", "flash", "redpoint", "unknown"] = "unknown"
    belay: Literal["lead", "top_rope", "auto_belay", "bouldering", "unknown"] = "unknown"
    notes: str | None = Field(default=None, max_length=1000)
    is_test: bool = False


class AccountBlock(Strict):
    blocked: bool


class StatisticsSummary(BaseModel):
    model_config = ConfigDict(extra="allow")
    routesCount: int = 0
    attemptsCount: int = 0
    completedRoutes: int = 0
    reachedTopRoutes: int = 0
    unknownCleanRoutes: int = 0
    activeProjects: int = 0
    onsightCount: int = 0
    flashCount: int = 0
    redpointCount: int = 0
    unknownStyleCount: int = 0
    leadAttemptsCount: int = 0
    topRopeAttemptsCount: int = 0
    autoBelayAttemptsCount: int = 0
    boulderingAttemptsCount: int = 0
    unknownBelayAttemptsCount: int = 0
    maxAttemptedGrade: str | None = None
    maxReachedTopGrade: str | None = None
    maxCompletedGrade: str | None = None


class StatisticsDTO(StatisticsSummary):
    scope: str | None = None
    training: StatisticsSummary | None = None
    summary: StatisticsSummary | None = None
    active: bool | None = None
    trainingsCount: int | None = None
    dateFrom: date | None = None
    dateTo: date | None = None
