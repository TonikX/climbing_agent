"""One-shot privileged migration. API and workers never run Alembic."""
import os
import subprocess
import sys

import psycopg
from psycopg import sql

from app.config import get_settings


def main():
    cfg = get_settings()
    runtime_password = os.environ["RUNTIME_DB_PASSWORD"]
    control_password = os.environ["CONTROL_DB_PASSWORD"]
    with psycopg.connect(host=cfg.db_host, port=cfg.db_port, dbname=cfg.db_name,
                        user=cfg.db_user, password=cfg.db_password.get_secret_value(), autocommit=True) as conn:
        for role, login, password in (("climbing_control", False, None),
                                      ("climbing_runtime", True, runtime_password),
                                      ("climbing_control_login", True, control_password)):
            if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone():
                conn.execute(sql.SQL("CREATE ROLE {} {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS").format(
                    sql.Identifier(role), sql.SQL("LOGIN" if login else "NOLOGIN")))
            if password:
                conn.execute(sql.SQL("ALTER ROLE {} PASSWORD {}").format(sql.Identifier(role), sql.Literal(password)))
            props = conn.execute("SELECT rolsuper, rolbypassrls, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname=%s", (role,)).fetchone()
            if any(props):
                raise RuntimeError("Runtime/control roles must not be privileged")
        conn.execute("GRANT climbing_control TO climbing_control_login")
    subprocess.run(["alembic", "upgrade", "head"], check=True)
    with psycopg.connect(host=cfg.db_host, port=cfg.db_port, dbname=cfg.db_name,
                        user=cfg.db_user, password=cfg.db_password.get_secret_value(), autocommit=True) as conn:
        for role in ("climbing_runtime", "climbing_control_login"):
            conn.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(cfg.db_name), sql.Identifier(role)))
            conn.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(role)))
        journal = ("training_sessions", "route_attempts", "training_sections", "training_gear", "gear", "locations", "sections", "routes", "idempotency_keys")
        for table in journal:
            conn.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON {} TO climbing_runtime,climbing_control_login").format(sql.Identifier(table)))
        conn.execute("GRANT SELECT ON users,external_refs TO climbing_runtime")
        conn.execute("GRANT UPDATE(name,timezone,test_mode_enabled) ON users TO climbing_runtime")
        conn.execute("GRANT SELECT,DELETE ON auth_sessions TO climbing_runtime")
        control = ("users", "auth_sessions", "external_refs", "access_requests", "telegram_updates", "jobs", "outbox", "usage", "audit_events", "deletion_records", "dialog_states", "update_receipts")
        for table in control:
            conn.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON {} TO climbing_control_login").format(sql.Identifier(table)))
        conn.execute("GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO climbing_control_login")
        operator = None if "--schema-only" in sys.argv else os.environ.get("ACCESS_APPROVER_TELEGRAM_ID")
        if operator:
            # Must be an existing, explicitly approved identity. Never bootstrap first-user admin.
            result = conn.execute("""UPDATE users SET role='admin' WHERE status='active' AND id IN
                (SELECT user_id FROM external_refs WHERE system='telegram' AND entity_type='user' AND external_id=%s)
                RETURNING id""", (operator,)).fetchone()
            if not result:
                raise RuntimeError("Verified approver must be explicitly approved in the migration manifest")


if __name__ == "__main__":
    main()
