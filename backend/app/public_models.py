"""Durable ingress, work and delivery; no Telegram identity supplied by the model."""
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Identity, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base, new_id


class AccessRequest(Base):
    __tablename__ = "access_requests"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'approved', 'rejected')", name="ck_access_status"),
        Index("uq_pending_access_user", "user_id", unique=True, postgresql_where=text("status = 'pending'")),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("access"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[str | None] = mapped_column(String)


class DialogState(Base):
    __tablename__ = "dialog_states"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    state: Mapped[str] = mapped_column(String(30))
    data: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))


class TelegramUpdate(Base):
    __tablename__ = "telegram_updates"
    __table_args__ = (UniqueConstraint("bot_id", "update_id", name="uq_telegram_update"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("update"))
    bot_id: Mapped[str] = mapped_column(String(30))
    update_id: Mapped[int] = mapped_column(Integer)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    payload: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))


class UpdateReceipt(Base):
    __tablename__ = "update_receipts"
    # Payload-free deduplication survives raw-data retention and account deletion.
    bot_id: Mapped[str] = mapped_column(String(30), primary_key=True)
    update_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'processing', 'succeeded', 'failed', 'cancelled')", name="ck_job_status"),
        Index("ix_job_queue", "lane", "status", "available_at"),
        Index("ix_job_user_order", "user_id", "sequence"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("job"))
    sequence: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)
    update_id: Mapped[str | None] = mapped_column(ForeignKey("telegram_updates.id", ondelete="CASCADE"), unique=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    lane: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    training_id: Mapped[str | None] = mapped_column(String)
    expected_version: Mapped[int | None] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    worker_id: Mapped[str | None] = mapped_column(String(100))
    retries: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(80))
    result: Mapped[dict | None] = mapped_column(JSONB)
    reservation_day: Mapped[str | None] = mapped_column(String(10))


class Outbox(Base):
    __tablename__ = "outbox"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'processing', 'succeeded', 'failed', 'cancelled')", name="ck_outbox_status"),
        Index("ix_outbox_queue", "status", "available_at"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("outbox"))
    sequence: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    dedupe_key: Mapped[str] = mapped_column(String(200), unique=True)
    chat_id: Mapped[str] = mapped_column(String(30))
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger)
    access_request_id: Mapped[str | None] = mapped_column(ForeignKey("access_requests.id", ondelete="CASCADE"), index=True)
    payload: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    worker_id: Mapped[str | None] = mapped_column(String(100))
    retries: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(80))


class Usage(Base):
    __tablename__ = "usage"
    __table_args__ = (UniqueConstraint("scope", "day", name="uq_usage_day"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("usage"))
    scope: Mapped[str] = mapped_column(String)
    day: Mapped[str] = mapped_column(String(10))
    requests: Mapped[int] = mapped_column(Integer, default=0)
    audio_seconds: Mapped[int] = mapped_column(Integer, default=0)
    budget_units: Mapped[int] = mapped_column(Integer, default=0)
    tokens: Mapped[int] = mapped_column(Integer, default=0)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("audit"))
    actor_id: Mapped[str] = mapped_column(String)
    action: Mapped[str] = mapped_column(String(80))
    subject_id: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))


class DeletionRecord(Base):
    __tablename__ = "deletion_records"
    # Export to independent backup storage before restoring any database backup.
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("deletion"))
    identity_hash: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
