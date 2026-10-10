"""Public access, durable queues, private catalogue and row security.

Existing users/catalogue require an explicit operator-reviewed migration manifest.
"""
import json
import os

from alembic import op
import sqlalchemy as sa

revision = "20261010_0012"
down_revision = "20261005_0011"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    users = set(conn.execute(sa.text("SELECT id FROM users")).scalars())
    locations = set(conn.execute(sa.text("SELECT id FROM locations")).scalars())
    manifest = json.loads(os.environ.get("PUBLIC_MIGRATION_MANIFEST") or "{}")
    approved = set(manifest.get("approved_user_ids", []))
    owners = manifest.get("location_owners", {})
    if users and ("approved_user_ids" not in manifest or approved - users):
        raise RuntimeError("Review approved_user_ids in PUBLIC_MIGRATION_MANIFEST first")
    if set(owners) != locations or any(uid not in users for uid in owners.values()):
        raise RuntimeError("Every existing location needs an explicitly reviewed owner; shared locations require reconciliation")
    references = conn.execute(sa.text("""
        SELECT primary_location_id AS location_id,user_id FROM training_sessions WHERE primary_location_id IS NOT NULL
        UNION SELECT s.location_id,t.user_id FROM training_sections x
            JOIN sections s ON s.id=x.section_id JOIN training_sessions t ON t.id=x.training_id
        UNION SELECT s.location_id,t.user_id FROM route_attempts a JOIN routes r ON r.id=a.route_id
            JOIN sections s ON s.id=r.section_id JOIN training_sessions t ON t.id=a.training_id
    """)).all()
    if any(owners[lid] != uid for lid, uid in references):
        raise RuntimeError("Shared catalogue must be reconciled into private copies before migration; history must remain readable")
    op.drop_constraint("ck_user_status", "users", type_="check")
    op.create_check_constraint("ck_user_status", "users", "status IN ('pending_approval', 'active', 'blocked')")
    op.alter_column("users", "status", server_default="pending_approval")
    conn.execute(sa.text("UPDATE users SET status='pending_approval' WHERE status <> 'blocked'"))
    for uid in approved:
        conn.execute(sa.text("UPDATE users SET status='active' WHERE id=:uid AND status <> 'blocked'"), {"uid": uid})
    conn.execute(sa.text("DELETE FROM auth_sessions"))
    op.add_column("users", sa.Column("role", sa.String(20), nullable=False, server_default="user"))
    op.add_column("users", sa.Column("last_fast_job_at", sa.DateTime(timezone=True)))
    op.add_column("users", sa.Column("last_ai_job_at", sa.DateTime(timezone=True)))
    op.create_check_constraint("ck_user_role", "users", "role IN ('user', 'support', 'admin')")
    op.add_column("route_attempts", sa.Column("hangs", sa.Integer()))
    op.create_check_constraint("ck_attempt_hangs", "route_attempts", "hangs IS NULL OR hangs >= 0")
    op.create_check_constraint("ck_attempt_clean_hangs", "route_attempts", "clean_ascent IS NOT TRUE OR hangs IS NULL OR hangs=0")
    op.create_index("ix_training_user_date", "training_sessions", ["user_id", "local_date"])
    op.create_index("ix_attempt_training_test", "route_attempts", ["training_id", "is_test"])
    op.add_column("locations", sa.Column("owner_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE")))
    op.add_column("locations", sa.Column("visibility", sa.String(20), nullable=False, server_default="private"))
    op.create_index("ix_locations_owner_id", "locations", ["owner_id"])
    for lid, uid in owners.items():
        conn.execute(sa.text("UPDATE locations SET owner_id=:uid WHERE id=:lid"), {"uid": uid, "lid": lid})
    op.create_check_constraint("ck_location_visibility", "locations",
                               "(visibility='private' AND owner_id IS NOT NULL) OR (visibility='public' AND owner_id IS NULL)")
    from app.public_models import AccessRequest, TelegramUpdate, Job, Outbox, Usage, AuditEvent, DeletionRecord, DialogState, UpdateReceipt
    for model in (AccessRequest, TelegramUpdate, Job, Outbox, Usage, AuditEvent, DeletionRecord, DialogState, UpdateReceipt):
        model.__table__.create(conn)
    # The control role may only bypass row scopes on identity/queue tables, not journal.
    # Provision the non-login role before migration; runtime logins are its members.
    if not conn.scalar(sa.text("SELECT EXISTS(SELECT FROM pg_roles WHERE rolname='climbing_control')")):
        raise RuntimeError("Provision climbing_control before migration; see docs/public-deployment.md")
    uid = "nullif(current_setting('app.user_id', true), '')"
    active = f"EXISTS(SELECT FROM users u WHERE u.id={uid} AND u.status='active')"
    scopes = {
        "users": f"id={uid}", "auth_sessions": f"user_id={uid} AND {active}",
        "gear": f"user_id={uid} AND {active}", "training_sessions": f"user_id={uid} AND {active} AND (primary_location_id IS NULL OR EXISTS(SELECT FROM locations l WHERE l.id=primary_location_id))",
        "idempotency_keys": f"user_id={uid} AND {active}",
        "route_attempts": f"EXISTS(SELECT FROM training_sessions t WHERE t.id=training_id AND t.user_id={uid}) AND (route_id IS NULL OR EXISTS(SELECT FROM routes r WHERE r.id=route_id))",
        "training_sections": f"EXISTS(SELECT FROM training_sessions t WHERE t.id=training_id AND t.user_id={uid}) AND EXISTS(SELECT FROM sections s WHERE s.id=section_id)",
        "training_gear": f"EXISTS(SELECT FROM training_sessions t WHERE t.id=training_id AND t.user_id={uid}) AND EXISTS(SELECT FROM gear g WHERE g.id=gear_id AND g.user_id={uid})",
    }
    for table, scope in scopes.items():
        conn.execute(sa.text(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY'))
        conn.execute(sa.text(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY'))
        conn.execute(sa.text(f'CREATE POLICY own_rows ON {table} USING ({scope}) WITH CHECK ({scope})'))
    for table in ("users", "auth_sessions"):
        conn.execute(sa.text(f'CREATE POLICY control_rows ON {table} TO climbing_control USING (true) WITH CHECK (true)'))
    cat_scopes = {
        "locations": (f"owner_id={uid} AND {active}", f"visibility='public' OR (owner_id={uid} AND {active})"),
        "sections": (f"EXISTS(SELECT FROM locations l WHERE l.id=location_id AND l.owner_id={uid})",
                     f"EXISTS(SELECT FROM locations l WHERE l.id=location_id AND (l.visibility='public' OR l.owner_id={uid}))"),
        "routes": (f"EXISTS(SELECT FROM sections s JOIN locations l ON l.id=s.location_id WHERE s.id=section_id AND l.owner_id={uid})",
                   f"EXISTS(SELECT FROM sections s JOIN locations l ON l.id=s.location_id WHERE s.id=section_id AND (l.visibility='public' OR l.owner_id={uid}))"),
    }
    for table, (write, read) in cat_scopes.items():
        conn.execute(sa.text(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY'))
        conn.execute(sa.text(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY'))
        conn.execute(sa.text(f'CREATE POLICY catalog_read ON {table} FOR SELECT USING ({read})'))
        for verb in ("INSERT", "UPDATE", "DELETE"):
            clause = f"WITH CHECK ({write})" if verb == "INSERT" else f"USING ({write})"
            if verb == "UPDATE":
                clause += f" WITH CHECK ({write})"
            conn.execute(sa.text(f'CREATE POLICY catalog_{verb.lower()} ON {table} FOR {verb} {clause}'))
    # Cross-user source references cannot disclose either identity or private catalogue.
    scope = f"user_id={uid} OR location_id IN (SELECT id FROM locations) OR section_id IN (SELECT id FROM sections) OR route_id IN (SELECT id FROM routes)"
    conn.execute(sa.text("ALTER TABLE external_refs ENABLE ROW LEVEL SECURITY"))
    conn.execute(sa.text("ALTER TABLE external_refs FORCE ROW LEVEL SECURITY"))
    conn.execute(sa.text(f"CREATE POLICY refs_read ON external_refs FOR SELECT USING ({scope})"))
    conn.execute(sa.text("CREATE POLICY identity_control ON external_refs TO climbing_control USING (entity_type='user') WITH CHECK (entity_type='user')"))
    for table in ("access_requests", "telegram_updates", "jobs", "outbox", "usage", "audit_events", "deletion_records", "dialog_states", "update_receipts"):
        conn.execute(sa.text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
        conn.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
        conn.execute(sa.text(f"CREATE POLICY control_only ON {table} TO climbing_control USING (true) WITH CHECK (true)"))


def downgrade():
    raise RuntimeError("Public data requires a compatible forward migration; do not roll back to a shared catalogue")
