"""Build a review sheet or an SQL import plan from offline guidebook OCR.

No database connection. Only reviewed=yes rows can enter the SQL plan.
"""
import argparse
import csv
import hashlib
import re
from pathlib import Path
from guidebook_extract import write_csv

FIELDS = ["source_sha256", "page", "panel", "row_key", "area", "sector", "name",
          "grade_raw", "grade", "confidence", "reviewed", "notes"]
GRADE = re.compile(r"(?:[IVX]+[+-]?|[3-9][abcABC]?[+-]?)(?:[/,](?:[IVX]+[+-]?|[3-9][abcABC]?[+-]?))*$")


def grade_token(text):
    value = text.replace(" ", "")
    if re.fullmatch(r"[IVX1l+/,\-]+", value):
        value = value.replace("1", "I").replace("l", "I")
    return value


def candidates(directory):
    digest = (directory / "source.sha256").read_text().strip()
    result = []
    for path in sorted(directory.glob("page-*.csv")):
        with path.open(encoding="utf-8-sig", newline="") as stream:
            boxes = list(csv.DictReader(stream))
        for box in boxes:
            for key in ("x", "y", "width", "height", "confidence"):
                box[key] = float(box[key])
        groups = {(b["image"], b["panel"]) for b in boxes}
        for image, panel in sorted(groups):
            group = [b for b in boxes if (b["image"], b["panel"]) == (image, panel)]
            headers = sorted([b for b in group if b["zone"] == "header" and len(b["text"]) > 4], key=lambda b:(b["y"], b["x"]))
            area = headers[0]["text"] if headers else ""
            sector = " | ".join(b["text"] for b in headers if b["y"] > headers[0]["y"] + 30) if headers else ""
            titles = [b for b in group if b["text"].strip().upper() == "GRADE"]
            if not titles:
                titles = [b for b in group if b["text"].strip().upper() == "DERECE"]
            for title in titles:
                names = [b for b in group if re.sub(r"[^A-Z]", "", b["text"].upper()) in {"NAME", "NAAE", "ISIM", "ISM"}
                         and b["x"] < title["x"] and abs(b["y"]-title["y"]) < 60]
                name_x = max(names, key=lambda b:b["x"])["x"] if names else 0
                grades = sorted([b for b in group if b["y"] > title["y"] + 20
                                 and abs(b["x"]-title["x"]) < 50
                                 and GRADE.fullmatch(grade_token(b["text"]))], key=lambda b:b["y"])
                for ordinal, grade in enumerate(grades, 1):
                    parts = sorted([b for b in group if name_x-20 <= b["x"] < title["x"]-20
                                    and not b["text"].strip().isdigit()
                                    and abs(b["y"]-grade["y"]) < max(18, grade["height"]*.7)], key=lambda b:b["x"])
                    if not parts:
                        continue
                    key = f"{path.stem}:{image}:{panel}:{round(title['x'])}:{ordinal}"
                    result.append(dict(source_sha256=digest, page=grade["page"], panel=panel, row_key=key,
                                       area=area, sector=sector, name=" ".join(b["text"] for b in parts),
                                       grade_raw=grade["text"], grade="", confidence=min([grade["confidence"]]+[b["confidence"] for b in parts]),
                                       reviewed="no", notes="Verify area/sector/name and French grade against scan; no automatic UIAA conversion"))
    return result


def literal(value):
    if "\x00" in value:
        raise ValueError("NUL in SQL value")
    return "'" + value.replace("'", "''") + "'"


def sql_plan(rows, location_id):
    approved = [r for r in rows if r["reviewed"].casefold() == "yes"]
    if not approved:
        raise ValueError("No reviewed=yes records; OCR cannot be imported without review")
    if len({r["area"] for r in approved}) != 1:
        raise ValueError("Reviewed batch must contain exactly one area")
    seen = set()
    lines = ["BEGIN;", "SET LOCAL standard_conforming_strings = on;",
             "SELECT pg_advisory_xact_lock(718394139489);",
             "CREATE TEMP TABLE guidebook_import_guard(ok boolean NOT NULL CHECK(ok)) ON COMMIT DROP;",
             "INSERT INTO guidebook_import_guard SELECT EXISTS (SELECT 1 FROM locations WHERE id="+literal(location_id)+
             " AND name="+literal(approved[0]["area"])+" AND visibility='public' AND owner_id IS NULL AND country='Турция');"]
    for row in approved:
        if not re.fullmatch(r"[a-f0-9]{64}", row["source_sha256"]):
            raise ValueError("Invalid document hash")
        if not row["name"].strip() or not row["sector"].strip() or not row["area"].strip():
            raise ValueError("Missing reviewed area/sector/name")
        if row["grade"] and not re.fullmatch(r"[3-9][ABC]?(?:\+)?(?:/[3-9][ABC]?(?:\+)?)?", row["grade"]):
            raise ValueError("Grade must be reviewed French notation, e.g. 6B+")
        if len(row["name"]) > 200 or len(row["sector"]) > 200:
            raise ValueError("Name exceeds database column size")
        identity = row["source_sha256"]+":"+row["row_key"]
        if identity in seen:
            raise ValueError("Duplicate source row")
        seen.add(identity)
        route_id = "route_"+hashlib.sha256(identity.encode()).hexdigest()[:32]
        section_id = "section_"+hashlib.sha256((location_id+":"+row["sector"]).encode()).hexdigest()[:32]
        ext = "sha256:"+identity
        if len(ext) > 300:
            raise ValueError("Source identity exceeds column size")
        lines += [f"-- PDF page {int(row['page'])}, panel {int(row['panel'])}",
                  "INSERT INTO sections(id,location_id,type,name) VALUES("+",".join(map(literal,[section_id,location_id,"sector",row["sector"]]))+") ON CONFLICT(location_id,type,name) DO NOTHING;",
                  "INSERT INTO routes(id,section_id,name,grade) SELECT "+literal(route_id)+",id,"+literal(row["name"])+","+(literal(row["grade"]) if row["grade"] else "NULL")+
                  " FROM sections WHERE location_id="+literal(location_id)+" AND type='sector' AND name="+literal(row["sector"])+
                  " ON CONFLICT(id) DO UPDATE SET name=EXCLUDED.name,grade=COALESCE(EXCLUDED.grade,routes.grade),section_id=EXCLUDED.section_id;",
                  "INSERT INTO external_refs(id,system,entity_type,external_id,route_id) VALUES("+
                  ",".join(map(literal,["ref_"+hashlib.sha256(ext.encode()).hexdigest()[:32],"guidebook_antalya_2023","route",ext,route_id]))+") ON CONFLICT(system,entity_type,external_id) DO NOTHING;"]
    lines.append("COMMIT;")
    return "\n".join(lines)+"\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--reviewed", type=Path, help="Reviewed CSV; otherwise generate candidates.csv")
    parser.add_argument("--location-id", help="Explicit existing public Turkish location for this reviewed batch")
    args = parser.parse_args()
    if args.reviewed:
        if not args.location_id:
            parser.error("SQL plan requires --location-id; prepare one area per batch")
        with args.reviewed.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        expected_hash = (args.directory / "source.sha256").read_text().strip()
        if any(r["source_sha256"] != expected_hash for r in rows):
            parser.error("Reviewed CSV belongs to a different source PDF")
        if len({r["area"] for r in rows if r["reviewed"].casefold() == "yes"}) != 1:
            parser.error("Reviewed batch must contain exactly one area")
        (args.directory / "import-reviewed.sql").write_text(sql_plan(rows, args.location_id), encoding="utf-8")
    else:
        rows = candidates(args.directory)
        write_csv(args.directory / "candidates.csv", rows, FIELDS)
        print(f"Candidates: {len(rows)}; all require visual review")


if __name__ == "__main__":
    main()
