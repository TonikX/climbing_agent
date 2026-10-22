"""Plan/apply owner-scoped catalogue reconciliation; never combine or delete attempts.

Run inside the backend environment. Dry-run is the default. Applying requires a
saved, unchanged plan and a PostgreSQL backup made by the operator beforehand.
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.config import get_settings
from app.grades import normalize_grade
from app.route_input import route_name


# Reviewed spelling corrections, not a general fuzzy-merge rule. Grade conflicts
# still prevent a route merge, and a destination must be unique inside its area.
AREA_SPELLINGS = {
    "Gikbairi": "Geyikbayırı", "Гейкбаир": "Geyikbayırı", "Гейкбаири": "Geyikbayırı",
    "Гейкбоири, массив turkısh standart": "Geyikbayırı", "Тернаус": "Тырныауз",
}
SECTOR_SPELLINGS = {
    "Turkish standart": "Turkish Standard", "Турки Штандарт": "Turkish Standard",
    "Требенна Вест": "Trebenna West", "Японский сад": "Японский садик",
}
ROUTE_SPELLINGS = {
    "turkısh standart": "Turkish Standard", "Epoxy Propoxy": "Эпоксипропокси",
    "Я сделаль": "Ясделяль",
}


def key(value):
    return re.sub(r"[^\w]+", "", (value or "").casefold().replace("ı", "i").replace("ё", "е"))


def choose_route(source, candidates, grades):
    name = ROUTE_SPELLINGS.get(route_name(source["name"]), route_name(source["name"]))
    matches = [row for row in candidates if key(name) in
               {key(row.get(field)) for field in ("name", "name_en", "name_native")}]
    if not matches:
        return None, "no_exact_name"
    observed = {normalize_grade(grade) for grade in [source.get("grade"), *grades] if grade}
    compatible = [row for row in matches if not observed or
                  (row.get("grade") and observed == {normalize_grade(row["grade"])})]
    if len(compatible) != 1:
        return None, "grade_conflict" if not compatible else "ambiguous_name"
    return compatible[0], "unique_name_and_grade"


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def fetch(conn, query, params=()):
    return conn.execute(query, params).fetchall()


def journal(conn, uid):
    return {
        "trainings": fetch(conn, "SELECT * FROM training_sessions WHERE user_id=%s ORDER BY id", (uid,)),
        "attempts": fetch(conn, "SELECT a.* FROM route_attempts a JOIN training_sessions t ON t.id=a.training_id WHERE t.user_id=%s ORDER BY a.id", (uid,)),
        "sections": fetch(conn, "SELECT ts.* FROM training_sections ts JOIN training_sessions t ON t.id=ts.training_id WHERE t.user_id=%s ORDER BY ts.training_id,ts.section_id", (uid,)),
    }


def immutable(j):
    return {
        "trainings": [{k:v for k,v in row.items() if k not in ("version", "primary_location_id")} for row in j["trainings"]],
        "attempts": [{**{k:v for k,v in row.items() if k not in ("route_id", "route_snapshot")},
                      "snapshot": {k:v for k,v in (row["route_snapshot"] or {}).items() if k not in ("name", "areaId", "sectorId")}}
                     for row in j["attempts"]],
    }


def catalogue(conn, uid):
    return {
        "locations": fetch(conn, "SELECT * FROM locations WHERE owner_id=%s ORDER BY id", (uid,)),
        "sections": fetch(conn, "SELECT s.* FROM sections s JOIN locations l ON l.id=s.location_id WHERE l.owner_id=%s ORDER BY s.id", (uid,)),
        "routes": fetch(conn, "SELECT r.* FROM routes r JOIN sections s ON s.id=r.section_id JOIN locations l ON l.id=s.location_id WHERE l.owner_id=%s ORDER BY r.id", (uid,)),
    }


def make_plan(conn, uid):
    personal, j = catalogue(conn, uid), journal(conn, uid)
    public = fetch(conn, """SELECT l.* FROM locations l WHERE l.visibility='public' AND EXISTS
        (SELECT FROM external_refs e WHERE e.location_id=l.id AND e.system IN ('allclimb','8a.nu','thecrag')) ORDER BY l.id""")
    areas, sectors, routes, unresolved = [], [], [], []
    for old in personal["locations"]:
        expected = AREA_SPELLINGS.get(old["name"], old["name"])
        matches = [row for row in public if key(row["name"]) == key(expected) and
                   (not old["country"] or not row["country"] or old["country"] == row["country"])]
        if len(matches) == 1:
            areas.append({"old":old, "new":matches[0]})
    area_map = {row["old"]["id"]:row["new"] for row in areas}
    public_sectors = fetch(conn, "SELECT s.* FROM sections s JOIN locations l ON l.id=s.location_id WHERE l.visibility='public' ORDER BY s.id")
    public_routes = fetch(conn, "SELECT r.*,s.location_id FROM routes r JOIN sections s ON s.id=r.section_id JOIN locations l ON l.id=s.location_id WHERE l.visibility='public' ORDER BY r.id")
    old_sectors = {row["id"]:row for row in personal["sections"]}
    for old in personal["sections"]:
        area = area_map.get(old["location_id"])
        expected = SECTOR_SPELLINGS.get(old["name"], old["name"])
        matches = [row for row in public_sectors if area and row["location_id"] == area["id"] and key(expected) in
                   {key(row.get(field)) for field in ("name", "name_en", "name_native")}]
        if len(matches) == 1:
            sectors.append({"old":old, "new":matches[0]})
    for old in personal["routes"]:
        section = old_sectors[old["section_id"]]
        area = area_map.get(section["location_id"])
        linked = [row for row in j["attempts"] if row["route_id"] == old["id"] or
                  (row["route_id"] is None and (row["route_snapshot"] or {}).get("sectorId") == section["id"] and
                   key(route_name((row["route_snapshot"] or {}).get("name"))) == key(route_name(old["name"])))]
        grades = [(row["route_snapshot"] or {}).get("grade") for row in linked]
        candidates = [row for row in public_routes if area and row["location_id"] == area["id"]]
        dest, reason = choose_route(old, candidates, grades)
        if dest:
            allowed = {key(route_name(old["name"])), *(key(dest.get(field)) for field in ("name", "name_en", "name_native"))}
            if any((row["route_snapshot"] or {}).get("name") and
                   key(route_name(row["route_snapshot"]["name"])) not in allowed for row in linked):
                dest, reason = None, "snapshot_name_conflict"
        if dest:
            routes.append({"old":old, "new":dest, "old_area":section["location_id"], "reason":reason})
        else:
            unresolved.append({"id":old["id"], "name":old["name"], "grade":old["grade"], "sector":section["name"], "reason":reason})
    return {"version":1, "user_id":uid, "fingerprint":fingerprint({"catalogue":personal, "journal":j}),
            "locations":areas, "sections":sectors, "routes":routes, "unresolved":unresolved}


def alias(conn, uid, field, target, name):
    # field is chosen by code, never by a manifest or user input.
    conn.execute(f"""INSERT INTO catalog_aliases(id,owner_id,name,{field})
        SELECT 'alias_'||gen_random_uuid()::text,%s,%s,%s WHERE NOT EXISTS
        (SELECT FROM catalog_aliases WHERE owner_id=%s AND {field}=%s AND catalog_normalize(name)=catalog_normalize(%s))""",
        (uid,name,target,uid,target,name))


def apply_plan(conn, uid, plan):
    if plan["user_id"] != uid or plan["version"] != 1:
        raise ValueError("Wrong plan owner/version")
    conn.execute("SELECT id FROM users WHERE id=%s FOR UPDATE", (uid,))
    if not conn.execute("SELECT pg_try_advisory_xact_lock(718394139489) AS ok").fetchone()["ok"]:
        raise ValueError("Catalogue import is running; retry later")
    if conn.execute("SELECT count(*) AS n FROM jobs WHERE user_id=%s AND status IN ('pending','processing') AND payload->>'mutation'='true'", (uid,)).fetchone()["n"]:
        raise ValueError("Pending journal work; wait until it finishes")
    dialog = conn.execute("SELECT * FROM dialog_states WHERE user_id=%s FOR UPDATE", (uid,)).fetchone()
    if dialog and dialog["data"].get("form") not in ("attempt_manage",):
        raise ValueError("An input draft is open; finish/cancel it before reconciliation")
    current = make_plan(conn, uid)
    # Recompute rather than trusting hand-edited destinations in a manifest.
    if fingerprint(current) != fingerprint(plan):
        raise ValueError("Plan is stale or edited; generate a fresh plan")
    before = journal(conn, uid)
    affected, changed = set(), []
    for mapping in plan["routes"]:
        old, new = mapping["old"], mapping["new"]
        conn.execute("SELECT id FROM routes WHERE id=ANY(%s) ORDER BY id FOR SHARE", ([old["id"],new["id"]],))
        for attempt in before["attempts"]:
            snapshot = attempt["route_snapshot"] or {}
            matches = attempt["route_id"] == old["id"] or (attempt["route_id"] is None and
                snapshot.get("sectorId") == old["section_id"] and key(route_name(snapshot.get("name"))) == key(route_name(old["name"])))
            if not matches:
                continue
            snapshot = {**snapshot, "name":new["name"], "areaId":new["location_id"], "sectorId":new["section_id"]}
            conn.execute("UPDATE route_attempts SET route_id=%s,route_snapshot=%s WHERE id=%s AND training_id IN (SELECT id FROM training_sessions WHERE user_id=%s)",
                         (new["id"],Jsonb(snapshot),attempt["id"],uid))
            conn.execute("INSERT INTO training_sections(training_id,section_id) VALUES (%s,%s) ON CONFLICT DO NOTHING", (attempt["training_id"],new["section_id"]))
            affected.add(attempt["training_id"])
            changed.append(attempt["id"])
    for kind, field in (("locations","location_id"),("sections","section_id"),("routes","route_id")):
        for mapping in plan[kind]:
            old, new = mapping["old"], mapping["new"]
            alias(conn, uid, field, new["id"], old["name"])
            conn.execute(f"UPDATE catalog_aliases SET {field}=%s WHERE owner_id=%s AND {field}=%s", (new["id"],uid,old["id"]))
            if kind == "locations":
                rows = fetch(conn, "UPDATE training_sessions SET primary_location_id=%s WHERE user_id=%s AND primary_location_id=%s RETURNING id", (new["id"],uid,old["id"]))
                affected.update(row["id"] for row in rows)
            elif kind == "sections":
                for row in before["sections"]:
                    if row["section_id"] != old["id"]:
                        continue
                    if conn.execute("SELECT count(*) AS n FROM route_attempts WHERE training_id=%s AND route_snapshot->>'sectorId'=%s", (row["training_id"],old["id"])).fetchone()["n"]:
                        continue
                    conn.execute("INSERT INTO training_sections(training_id,section_id) VALUES (%s,%s) ON CONFLICT DO NOTHING", (row["training_id"],new["id"]))
                    conn.execute("DELETE FROM training_sections WHERE training_id=%s AND section_id=%s", (row["training_id"],old["id"]))
                    affected.add(row["training_id"])
    if affected:
        conn.execute("UPDATE training_sessions SET version=version+1 WHERE user_id=%s AND id=ANY(%s)", (uid,sorted(affected)))
        conn.execute("DELETE FROM dialog_states WHERE user_id=%s", (uid,))
    after = journal(conn, uid)
    if fingerprint(immutable(before)) != fingerprint(immutable(after)) or len(changed) != len(set(changed)):
        raise ValueError("Journal invariant failed; rollback required")
    # Retain unmatched private catalogue entries. Delete only mapped rows without
    # references; this never cascades through a personal tree.
    pruned = {"routes":0,"sections":0,"locations":0}
    for mapping in plan["routes"]:
        row = mapping["old"]
        result = conn.execute("""DELETE FROM routes r WHERE r.id=%s
            AND NOT EXISTS(SELECT FROM route_attempts a WHERE a.route_id=r.id OR
                (a.route_snapshot->>'sectorId'=%s AND catalog_normalize(a.route_snapshot->>'name')=catalog_normalize(%s)))
            AND NOT EXISTS(SELECT FROM external_refs e WHERE e.route_id=r.id)
            AND NOT EXISTS(SELECT FROM catalog_aliases a WHERE a.route_id=r.id)""", (row["id"],row["section_id"],row["name"]))
        pruned["routes"] += result.rowcount
    for mapping in plan["sections"]:
        result = conn.execute("""DELETE FROM sections s WHERE s.id=%s AND NOT EXISTS(SELECT FROM routes r WHERE r.section_id=s.id)
            AND NOT EXISTS(SELECT FROM training_sections ts WHERE ts.section_id=s.id)
            AND NOT EXISTS(SELECT FROM route_attempts a WHERE a.route_snapshot->>'sectorId'=s.id)
            AND NOT EXISTS(SELECT FROM catalog_aliases a WHERE a.section_id=s.id)
            AND NOT EXISTS(SELECT FROM external_refs e WHERE e.section_id=s.id)""", (mapping["old"]["id"],))
        pruned["sections"] += result.rowcount
    for mapping in plan["locations"]:
        result = conn.execute("""DELETE FROM locations l WHERE l.id=%s AND l.owner_id=%s
            AND NOT EXISTS(SELECT FROM sections s WHERE s.location_id=l.id)
            AND NOT EXISTS(SELECT FROM training_sessions t WHERE t.primary_location_id=l.id)
            AND NOT EXISTS(SELECT FROM route_attempts a WHERE a.route_snapshot->>'areaId'=l.id)
            AND NOT EXISTS(SELECT FROM catalog_aliases a WHERE a.location_id=l.id)
            AND NOT EXISTS(SELECT FROM external_refs e WHERE e.location_id=l.id)""", (mapping["old"]["id"],uid))
        pruned["locations"] += result.rowcount
    return {"attempts_relinked":len(changed), "trainings_updated":len(affected), "pruned":pruned,
            "routes_matched":len(plan["routes"]), "routes_unresolved":len(plan["unresolved"])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, help="Saved dry-run plan for rehearsal/apply")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply and not args.plan:
        parser.error("--apply requires --plan")
    cfg = get_settings()
    if not cfg.access_approver_telegram_id:
        parser.error("Verified owner Telegram ID is required")
    with psycopg.connect(host=cfg.db_host, port=cfg.db_port, dbname=cfg.db_name,
        user=cfg.db_control_user or cfg.db_user,
        password=(cfg.db_control_password or cfg.db_password).get_secret_value(), row_factory=dict_row) as conn:
        conn.execute("SET LOCAL lock_timeout='10s'")
        conn.execute("SET LOCAL statement_timeout='120s'")
        conn.execute("SET LOCAL jit=off")
        owner = conn.execute("""SELECT u.id FROM users u JOIN external_refs e ON e.user_id=u.id
            WHERE e.system='telegram' AND e.entity_type='user' AND e.external_id=%s AND u.status='active'""", (cfg.access_approver_telegram_id,)).fetchone()
        if not owner:
            raise ValueError("Verified active owner not found")
        uid = owner["id"]
        conn.execute("SELECT set_config('app.user_id',%s,true)", (uid,))
        if args.plan:
            plan = json.loads(args.plan.read_text(encoding="utf-8"))
            result = apply_plan(conn, uid, plan)
            if args.apply:
                conn.commit()
            else:
                conn.rollback()
            print(json.dumps({"committed":args.apply, **result}, ensure_ascii=False))
        else:
            print(json.dumps(make_plan(conn, uid), ensure_ascii=False, indent=2, default=str))
            conn.rollback()


if __name__ == "__main__":
    main()
