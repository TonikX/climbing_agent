from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


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
    result: Literal["send", "project", "attempted", "unknown"] = "unknown"
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
    result: str
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
