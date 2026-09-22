from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import (
    Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Index, Integer,
    Numeric, String, Table, Text, UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4()}"


class Base(DeclarativeBase):
    pass


class TrainingStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"


training_sections = Table(
    "training_sections", Base.metadata,
    Column("training_id", ForeignKey("training_sessions.id", ondelete="CASCADE"), primary_key=True),
    Column("section_id", ForeignKey("sections.id", ondelete="RESTRICT"), primary_key=True, index=True),
)

training_gear = Table(
    "training_gear", Base.metadata,
    Column("training_id", ForeignKey("training_sessions.id", ondelete="CASCADE"), primary_key=True),
    Column("gear_id", ForeignKey("gear.id", ondelete="RESTRICT"), primary_key=True, index=True),
)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("user"))
    name: Mapped[str] = mapped_column(String(200))
    timezone: Mapped[str] = mapped_column(String(100), default="Europe/Moscow")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    external_refs: Mapped[list["ExternalRef"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    gear: Mapped[list["Gear"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Location(Base):
    __tablename__ = "locations"
    __table_args__ = (CheckConstraint("type IN ('outdoor', 'gym')", name="ck_location_type"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("location"))
    type: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(200), index=True)
    country: Mapped[str | None] = mapped_column(String(2))
    city: Mapped[str | None] = mapped_column(String(200))
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), onupdate=text("now()")
    )
    sections: Mapped[list["Section"]] = relationship(back_populates="location", cascade="all, delete-orphan")
    external_refs: Mapped[list["ExternalRef"]] = relationship(back_populates="location", cascade="all, delete-orphan")


class Section(Base):
    __tablename__ = "sections"
    __table_args__ = (
        CheckConstraint("type IN ('sector', 'zone', 'wall')", name="ck_section_type"),
        UniqueConstraint("location_id", "type", "name", name="uq_section_location_type_name"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("section"))
    location_id: Mapped[str] = mapped_column(ForeignKey("locations.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), onupdate=text("now()")
    )
    location: Mapped[Location] = relationship(back_populates="sections")
    routes: Mapped[list["Route"]] = relationship(back_populates="section", cascade="all, delete-orphan")
    external_refs: Mapped[list["ExternalRef"]] = relationship(back_populates="section", cascade="all, delete-orphan")


class Route(Base):
    __tablename__ = "routes"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("route"))
    section_id: Mapped[str] = mapped_column(ForeignKey("sections.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    grade: Mapped[str | None] = mapped_column(String(30), index=True)
    color: Mapped[str | None] = mapped_column(String(50))
    route_number: Mapped[str | None] = mapped_column(String(50))
    setter: Mapped[str | None] = mapped_column(String(200))
    set_date: Mapped[date | None] = mapped_column(Date)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), onupdate=text("now()")
    )
    section: Mapped[Section] = relationship(back_populates="routes")
    external_refs: Mapped[list["ExternalRef"]] = relationship(back_populates="route", cascade="all, delete-orphan")


class Gear(Base):
    __tablename__ = "gear"
    __table_args__ = (CheckConstraint(
        "type IN ('shoes', 'rope', 'harness', 'belay_device', 'helmet', 'chalk', 'other')",
        name="ck_gear_type",
    ),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("gear"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(30))
    brand: Mapped[str | None] = mapped_column(String(100))
    model: Mapped[str | None] = mapped_column(String(100))
    size: Mapped[str | None] = mapped_column(String(50))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    notes: Mapped[str | None] = mapped_column(Text)
    attributes: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), onupdate=text("now()")
    )
    user: Mapped[User] = relationship(back_populates="gear")


class TrainingSession(Base):
    __tablename__ = "training_sessions"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'completed')", name="ck_training_status"),
        CheckConstraint("environment IN ('indoor', 'outdoor', 'unknown')", name="ck_training_environment"),
        CheckConstraint("duration_minutes IS NULL OR duration_minutes > 0", name="ck_training_duration_positive"),
        Index("uq_active_training_per_user", "user_id", unique=True, postgresql_where=text("status = 'active'")),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("training"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    primary_location_id: Mapped[str | None] = mapped_column(ForeignKey("locations.id", ondelete="SET NULL"), index=True)
    status: Mapped[str] = mapped_column(String(20), default=TrainingStatus.ACTIVE.value)
    local_date: Mapped[date] = mapped_column(Date)
    timezone: Mapped[str] = mapped_column(String(100))
    environment: Mapped[str] = mapped_column(String(20), default="unknown")
    duration_minutes: Mapped[int | None] = mapped_column(Integer)
    physical_state: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    weather: Mapped[dict | None] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), onupdate=text("now()")
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[list["RouteAttempt"]] = relationship(back_populates="training", cascade="all, delete-orphan")
    sections: Mapped[list[Section]] = relationship(secondary=training_sections)
    gear: Mapped[list[Gear]] = relationship(secondary=training_gear)


class RouteAttempt(Base):
    __tablename__ = "route_attempts"
    __table_args__ = (
        CheckConstraint("result IN ('send', 'project', 'attempted', 'unknown')", name="ck_attempt_result"),
        CheckConstraint("style IN ('onsight', 'flash', 'redpoint', 'unknown')", name="ck_attempt_style"),
        CheckConstraint("belay IN ('lead', 'top_rope', 'auto_belay', 'bouldering', 'unknown')", name="ck_attempt_belay"),
        CheckConstraint("feel IN ('easy', 'comfortable', 'limit', 'unknown')", name="ck_attempt_feel"),
        CheckConstraint("attempts > 0", name="ck_attempt_count_positive"),
        UniqueConstraint("training_id", "sequence", name="uq_attempt_sequence"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("attempt"))
    training_id: Mapped[str] = mapped_column(ForeignKey("training_sessions.id", ondelete="CASCADE"), index=True)
    route_id: Mapped[str | None] = mapped_column(ForeignKey("routes.id", ondelete="SET NULL"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    result: Mapped[str] = mapped_column(String(20), default="unknown")
    style: Mapped[str] = mapped_column(String(20), default="unknown")
    belay: Mapped[str] = mapped_column(String(20), default="unknown")
    feel: Mapped[str] = mapped_column(String(20), default="unknown")
    notes: Mapped[str | None] = mapped_column(Text)
    is_test: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    route_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    training: Mapped[TrainingSession] = relationship(back_populates="attempts")
    route: Mapped[Route | None] = relationship()


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (UniqueConstraint("user_id", "operation", "key", name="uq_idempotency_scope"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("idempotency"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    operation: Mapped[str] = mapped_column(String(100))
    key: Mapped[str] = mapped_column(String(200))
    request_hash: Mapped[str] = mapped_column(String(64))
    response_status: Mapped[int] = mapped_column(Integer)
    response_body: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))


class ExternalRef(Base):
    __tablename__ = "external_refs"
    __table_args__ = (
        CheckConstraint("entity_type IN ('user', 'location', 'section', 'route')", name="ck_external_ref_type"),
        CheckConstraint(
            "(entity_type = 'user' AND user_id IS NOT NULL AND location_id IS NULL AND section_id IS NULL AND route_id IS NULL) OR "
            "(entity_type = 'location' AND user_id IS NULL AND location_id IS NOT NULL AND section_id IS NULL AND route_id IS NULL) OR "
            "(entity_type = 'section' AND user_id IS NULL AND location_id IS NULL AND section_id IS NOT NULL AND route_id IS NULL) OR "
            "(entity_type = 'route' AND user_id IS NULL AND location_id IS NULL AND section_id IS NULL AND route_id IS NOT NULL)",
            name="ck_external_ref_owner",
        ),
        UniqueConstraint("system", "entity_type", "external_id", name="uq_external_identity"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("external_ref"))
    system: Mapped[str] = mapped_column(String(50))
    entity_type: Mapped[str] = mapped_column(String(20))
    external_id: Mapped[str] = mapped_column(String(300))
    url: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    location_id: Mapped[str | None] = mapped_column(ForeignKey("locations.id", ondelete="CASCADE"), index=True)
    section_id: Mapped[str | None] = mapped_column(ForeignKey("sections.id", ondelete="CASCADE"), index=True)
    route_id: Mapped[str | None] = mapped_column(ForeignKey("routes.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    user: Mapped[User | None] = relationship(back_populates="external_refs")
    location: Mapped[Location | None] = relationship(back_populates="external_refs")
    section: Mapped[Section | None] = relationship(back_populates="external_refs")
    route: Mapped[Route | None] = relationship(back_populates="external_refs")
