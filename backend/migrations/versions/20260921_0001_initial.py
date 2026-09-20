"""Initial climbing journal schema.

Revision ID: 20260921_0001
Revises:
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260921_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("timezone", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_table(
        "locations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("country", sa.String(2)),
        sa.Column("city", sa.String(200)),
        sa.Column("latitude", sa.Numeric(9, 6)),
        sa.Column("longitude", sa.Numeric(9, 6)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("type IN ('outdoor', 'gym')", name="ck_location_type"),
    )
    op.create_index("ix_locations_name", "locations", ["name"])

    op.create_table(
        "sections",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("location_id", sa.String(), sa.ForeignKey("locations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("type IN ('sector', 'zone', 'wall')", name="ck_section_type"),
        sa.UniqueConstraint("location_id", "type", "name", name="uq_section_location_type_name"),
    )
    op.create_index("ix_sections_location_id", "sections", ["location_id"])

    op.create_table(
        "routes",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("section_id", sa.String(), sa.ForeignKey("sections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("grade", sa.String(30)),
        sa.Column("color", sa.String(50)),
        sa.Column("route_number", sa.String(50)),
        sa.Column("setter", sa.String(200)),
        sa.Column("set_date", sa.Date()),
        sa.Column("removed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_routes_section_id", "routes", ["section_id"])
    op.create_index("ix_routes_name", "routes", ["name"])
    op.create_index("ix_routes_grade", "routes", ["grade"])

    op.create_table(
        "gear",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(30), nullable=False),
        sa.Column("brand", sa.String(100)),
        sa.Column("model", sa.String(100)),
        sa.Column("size", sa.String(50)),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("attributes", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "type IN ('shoes', 'rope', 'harness', 'belay_device', 'helmet', 'chalk', 'other')",
            name="ck_gear_type",
        ),
    )
    op.create_index("ix_gear_user_id", "gear", ["user_id"])

    op.create_table(
        "training_sessions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("primary_location_id", sa.String(), sa.ForeignKey("locations.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("timezone", sa.String(100), nullable=False),
        sa.Column("environment", sa.String(20), nullable=False),
        sa.Column("duration_minutes", sa.Integer()),
        sa.Column("physical_state", sa.Text()),
        sa.Column("notes", sa.Text()),
        sa.Column("weather", postgresql.JSONB()),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('active', 'completed')", name="ck_training_status"),
        sa.CheckConstraint("environment IN ('indoor', 'outdoor', 'unknown')", name="ck_training_environment"),
        sa.CheckConstraint("duration_minutes IS NULL OR duration_minutes > 0", name="ck_training_duration_positive"),
    )
    op.create_index("ix_training_sessions_user_id", "training_sessions", ["user_id"])
    op.create_index("ix_training_sessions_primary_location_id", "training_sessions", ["primary_location_id"])
    op.create_index(
        "uq_active_training_per_user", "training_sessions", ["user_id"], unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "training_sections",
        sa.Column("training_id", sa.String(), sa.ForeignKey("training_sessions.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("section_id", sa.String(), sa.ForeignKey("sections.id", ondelete="RESTRICT"), primary_key=True),
    )
    op.create_index("ix_training_sections_section_id", "training_sections", ["section_id"])
    op.create_table(
        "training_gear",
        sa.Column("training_id", sa.String(), sa.ForeignKey("training_sessions.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("gear_id", sa.String(), sa.ForeignKey("gear.id", ondelete="RESTRICT"), primary_key=True),
    )
    op.create_index("ix_training_gear_gear_id", "training_gear", ["gear_id"])

    op.create_table(
        "route_attempts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("training_id", sa.String(), sa.ForeignKey("training_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("route_id", sa.String(), sa.ForeignKey("routes.id", ondelete="SET NULL")),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("result", sa.String(20), nullable=False),
        sa.Column("style", sa.String(20), nullable=False),
        sa.Column("belay", sa.String(20), nullable=False),
        sa.Column("feel", sa.String(20), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("route_snapshot", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("attempts > 0", name="ck_attempt_count_positive"),
        sa.CheckConstraint("result IN ('send', 'project', 'attempted', 'unknown')", name="ck_attempt_result"),
        sa.CheckConstraint("style IN ('onsight', 'flash', 'redpoint', 'unknown')", name="ck_attempt_style"),
        sa.CheckConstraint("belay IN ('lead', 'top_rope', 'auto_belay', 'bouldering', 'unknown')", name="ck_attempt_belay"),
        sa.CheckConstraint("feel IN ('easy', 'comfortable', 'limit', 'unknown')", name="ck_attempt_feel"),
        sa.UniqueConstraint("training_id", "sequence", name="uq_attempt_sequence"),
    )
    op.create_index("ix_route_attempts_training_id", "route_attempts", ["training_id"])
    op.create_index("ix_route_attempts_route_id", "route_attempts", ["route_id"])

    op.create_table(
        "idempotency_keys",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("operation", sa.String(100), nullable=False),
        sa.Column("key", sa.String(200), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=False),
        sa.Column("response_body", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("user_id", "operation", "key", name="uq_idempotency_scope"),
    )
    op.create_index("ix_idempotency_keys_user_id", "idempotency_keys", ["user_id"])

    op.create_table(
        "external_refs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("system", sa.String(50), nullable=False),
        sa.Column("entity_type", sa.String(20), nullable=False),
        sa.Column("external_id", sa.String(300), nullable=False),
        sa.Column("url", sa.Text()),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("location_id", sa.String(), sa.ForeignKey("locations.id", ondelete="CASCADE")),
        sa.Column("section_id", sa.String(), sa.ForeignKey("sections.id", ondelete="CASCADE")),
        sa.Column("route_id", sa.String(), sa.ForeignKey("routes.id", ondelete="CASCADE")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("entity_type IN ('user', 'location', 'section', 'route')", name="ck_external_ref_type"),
        sa.CheckConstraint(
            "(entity_type = 'user' AND user_id IS NOT NULL AND location_id IS NULL AND section_id IS NULL AND route_id IS NULL) OR "
            "(entity_type = 'location' AND user_id IS NULL AND location_id IS NOT NULL AND section_id IS NULL AND route_id IS NULL) OR "
            "(entity_type = 'section' AND user_id IS NULL AND location_id IS NULL AND section_id IS NOT NULL AND route_id IS NULL) OR "
            "(entity_type = 'route' AND user_id IS NULL AND location_id IS NULL AND section_id IS NULL AND route_id IS NOT NULL)",
            name="ck_external_ref_owner",
        ),
        sa.UniqueConstraint("system", "entity_type", "external_id", name="uq_external_identity"),
    )
    for column in ("user_id", "location_id", "section_id", "route_id"):
        op.create_index(f"ix_external_refs_{column}", "external_refs", [column])


def downgrade() -> None:
    op.drop_table("external_refs")
    op.drop_table("idempotency_keys")
    op.drop_table("route_attempts")
    op.drop_table("training_gear")
    op.drop_table("training_sections")
    op.drop_table("training_sessions")
    op.drop_table("gear")
    op.drop_table("routes")
    op.drop_table("sections")
    op.drop_table("locations")
    op.drop_table("users")
