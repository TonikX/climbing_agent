from datetime import date, datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4()}"


class Base(DeclarativeBase):
    pass


class TrainingStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("user"))
    name: Mapped[str] = mapped_column(String(200))
    timezone: Mapped[str] = mapped_column(String(100), default="Europe/Moscow")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    external_refs: Mapped[list["ExternalRef"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class ExternalRef(Base):
    __tablename__ = "external_refs"
    __table_args__ = (UniqueConstraint("system", "external_id", name="uq_external_identity"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("external_ref"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    system: Mapped[str] = mapped_column(String(50))
    external_id: Mapped[str] = mapped_column(String(300))
    user: Mapped[User] = relationship(back_populates="external_refs")


class TrainingSession(Base):
    __tablename__ = "training_sessions"
    __table_args__ = (
        Index("uq_active_training_per_user", "user_id", unique=True, postgresql_where=text("status = 'active'")),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("training"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20), default=TrainingStatus.ACTIVE.value)
    local_date: Mapped[date] = mapped_column(Date)
    environment: Mapped[str] = mapped_column(String(20), default="unknown")
    duration_minutes: Mapped[int | None] = mapped_column(Integer)
    physical_state: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    weather: Mapped[dict | None] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[list["RouteAttempt"]] = relationship(back_populates="training", cascade="all, delete-orphan")


class RouteAttempt(Base):
    __tablename__ = "route_attempts"
    __table_args__ = (UniqueConstraint("training_id", "sequence", name="uq_attempt_sequence"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("attempt"))
    training_id: Mapped[str] = mapped_column(ForeignKey("training_sessions.id", ondelete="CASCADE"), index=True)
    route_id: Mapped[str | None] = mapped_column(String)
    sequence: Mapped[int] = mapped_column(Integer)
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    result: Mapped[str] = mapped_column(String(20), default="unknown")
    style: Mapped[str] = mapped_column(String(20), default="unknown")
    belay: Mapped[str] = mapped_column(String(20), default="unknown")
    feel: Mapped[str] = mapped_column(String(20), default="unknown")
    notes: Mapped[str | None] = mapped_column(Text)
    route_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    training: Mapped[TrainingSession] = relationship(back_populates="attempts")
