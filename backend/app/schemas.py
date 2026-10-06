from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class TelegramLogin(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    telegram_id: str = Field(pattern=r"^[1-9][0-9]{0,19}$")


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    timezone: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("name", "timezone")
    @classmethod
    def non_null(cls, value):
        if value is None:
            raise ValueError("Use an omitted field rather than null")
        return value

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Unknown IANA timezone")
        return value


class UserResolveRequest(BaseModel):
    system: str = Field(min_length=1, max_length=50)
    external_id: str = Field(min_length=1, max_length=300)
    name: str = Field(min_length=1, max_length=200)
    timezone: str = "Europe/Moscow"


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    timezone: str


class TrainingCreate(BaseModel):
    date: date
    environment: Literal["indoor", "outdoor", "unknown"] = "unknown"
    notes: str | None = None


class AttemptCreate(BaseModel):
    route_id: str | None = None
    name: str | None = None
    grade: str | None = None
    section_id: str | None = None
    attempts: int = Field(default=1, ge=1)
    result: Literal["send", "project", "attempted", "unknown"] = Field(
        default="unknown", deprecated=True, description="Legacy input. Use reached_top and clean_ascent.")
    reached_top: bool | None = None
    clean_ascent: bool | None = None
    falls: int | None = Field(default=None, ge=0)
    style: Literal["onsight", "flash", "redpoint", "unknown"] = "unknown"
    belay: Literal["lead", "top_rope", "auto_belay", "bouldering", "unknown"] = "unknown"
    feel: Literal["easy", "comfortable", "limit", "unknown"] = "unknown"
    notes: str | None = None
    is_test: bool = False


class FinishTraining(BaseModel):
    duration_minutes: int | None = Field(default=None, ge=1)
    physical_state: str | None = None
    notes: str | None = None


class AttemptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    sequence: int
    attempts: int
    reached_top: bool | None
    clean_ascent: bool | None
    style: str
    belay: str
    feel: str
    notes: str | None
    is_test: bool
    route_snapshot: dict


class TrainingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    user_id: str
    status: str
    local_date: date
    environment: str
    duration_minutes: int | None
    physical_state: str | None
    notes: str | None
    weather: dict | None
    version: int
    created_at: datetime
    completed_at: datetime | None
    attempts: list[AttemptResponse] = Field(default_factory=list)


class ToolCommand(BaseModel):
    payload: dict[str, Any]
