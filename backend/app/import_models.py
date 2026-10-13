"""Public catalogue import reports, separate from users and their journals."""
from datetime import datetime

from sqlalchemy import DateTime, String, Text, CheckConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base, new_id


class CatalogImportRun(Base):
    __tablename__ = "catalog_import_runs"
    __table_args__ = (CheckConstraint("status IN ('running','partial','succeeded','failed','interrupted')", name="ck_catalog_import_status"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("import"))
    source: Mapped[str] = mapped_column(String(50), default="allclimb")
    status: Mapped[str] = mapped_column(String(20), default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    report: Mapped[dict] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
