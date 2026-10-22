from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.grades import normalize_grade
from app.route_input import route_name
from app.schemas import AttemptResponse


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @field_validator("grade", mode="before", check_fields=False)
    @classmethod
    def canonical_grade(cls, value):
        return normalize_grade(value) if isinstance(value, str) else value


class Claim(Strict):
    worker_id: str = Field(min_length=1, max_length=100)
    lane: Literal["fast", "ai", "delivery"]


class AttemptChanges(Strict):
    _route_name = field_validator("name", mode="before")(route_name)
    region: str | None = Field(default=None, min_length=1, max_length=200)
    sector: str | None = Field(default=None, min_length=1, max_length=200)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    grade: str | None = Field(default=None, min_length=1, max_length=30)
    reached_top: bool | None = None
    clean_ascent: bool | None = None
    style: Literal["onsight", "flash", "redpoint", "with_falls", "with_hangs", "top_rope", "unknown"] | None = None
    belay: Literal["lead", "top_rope", "auto_belay", "bouldering", "unknown"] | None = None
    falls: int | None = Field(default=None, ge=0, le=1000)
    hangs: int | None = Field(default=None, ge=0, le=1000)
    notes: str | None = Field(default=None, max_length=1000)
    is_test: bool | None = None


class Intent(Strict):
    _route_name = field_validator("name", mode="before")(route_name)
    kind: Literal["statistics", "attempt", "update_attempts", "delete_attempts", "clarify"]
    region: str | None = Field(default=None, min_length=1, max_length=200)
    sector: str | None = Field(default=None, min_length=1, max_length=200)
    training_scope: Literal["selected", "current", "last"] = "selected"
    target_numbers: list[int] = Field(default_factory=list, max_length=100)
    target_name: str | None = Field(default=None, max_length=200)
    target_all: bool = False
    target_last: bool = False
    changes: AttemptChanges | None = None
    scope: Literal["week", "month", "last_training", "current", "progress", "grades", "locations", "projects", "records"] = "week"
    date_from: date | None = None
    date_to: date | None = None
    grade: str | None = Field(default=None, max_length=30)
    name: str | None = Field(default=None, max_length=200)
    reached_top: bool | None = None
    clean_ascent: bool | None = None
    falls: int | None = Field(default=None, ge=0, le=1000)
    hangs: int | None = Field(default=None, ge=0, le=1000)
    style: Literal["onsight", "flash", "redpoint", "with_falls", "with_hangs", "top_rope", "unknown"] = "unknown"
    belay: Literal["lead", "top_rope", "auto_belay", "bouldering", "unknown"] = "unknown"
    attempts: int | None = Field(default=None, ge=1, le=100)
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


class AttemptPatch(AttemptChanges):
    expected_version: int = Field(ge=1)
    reached_top: bool | None = None
    clean_ascent: bool | None = None
    falls: int | None = Field(default=None, ge=0)
    hangs: int | None = Field(default=None, ge=0)
    style: Literal["onsight", "flash", "redpoint", "with_falls", "with_hangs", "top_rope", "unknown"] | None = None
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
    name_en: str | None = Field(default=None, min_length=1, max_length=200)
    name_native: str | None = Field(default=None, min_length=1, max_length=200)


class RouteWrite(Strict):
    _route_name = field_validator("name", mode="before")(route_name)
    section_id: str
    name: str = Field(min_length=1, max_length=200)
    name_en: str | None = Field(default=None, min_length=1, max_length=200)
    name_native: str | None = Field(default=None, min_length=1, max_length=200)
    grade: str | None = Field(default=None, max_length=30)


class GearPatch(Strict):
    brand: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=100)
    size: str | None = Field(default=None, max_length=50)
    notes: str | None = Field(default=None, max_length=1000)
    active: bool | None = None


class CatalogPatch(Strict):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    name_en: str | None = Field(default=None, min_length=1, max_length=200)
    name_native: str | None = Field(default=None, min_length=1, max_length=200)
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
    _route_name = field_validator("name", mode="before")(route_name)
    name: str = Field(min_length=1, max_length=200)
    grade: str | None = Field(default=None, max_length=30)
    route_id: str | None = None
    attempts: int = Field(default=1, ge=1)
    reached_top: bool | None = None
    clean_ascent: bool | None = None
    falls: int | None = Field(default=None, ge=0)
    hangs: int | None = Field(default=None, ge=0)
    style: Literal["onsight", "flash", "redpoint", "with_falls", "with_hangs", "top_rope", "unknown"] = "unknown"
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
    topRopeStyleAttemptsCount: int = 0
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


class PyramidPlaceDTO(BaseModel):
    id: str
    name: str
    region: str | None = None


class PyramidRouteDTO(BaseModel):
    name: str | None
    grade: str | None


class PyramidAscentDTO(BaseModel):
    trainingId: str
    date: date
    routeSessionKey: str
    route: PyramidRouteDTO
    location: PyramidPlaceDTO | None
    sector: PyramidPlaceDTO | None
    bucket: Literal["onsight", "flash", "redpoint", "top_rope", "other_clean", "not_clean"]
    style: str
    belay: str
    cleanAscent: bool | None
    reachedTop: bool | None
    attemptsCount: int
    attempts: list[AttemptResponse]


class PyramidPageDTO(BaseModel):
    items: list[PyramidAscentDTO]
    total: int
    nextOffset: int | None
