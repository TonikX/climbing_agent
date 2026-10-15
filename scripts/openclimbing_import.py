"""Inspect the official OpenClimbing SQLite export and prepare a PostgreSQL plan.

No HTTP requests or database writes. Only climbing_features is read, never ticks
or identities. PostgreSQL remains the application database.
"""
import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import re
import sqlite3

SOURCE = "openstreetmap"
ATTRIBUTION = "© OpenStreetMap contributors; ODbL 1.0; extract: openclimbing.org"
COUNTRIES = {"RU": "Россия", "TR": "Турция"}


def key(row):
    kind, ident = row["osmType"], int(row["osmId"])
    if kind not in {"node", "way", "relation"} or ident <= 0:
        raise ValueError("Invalid OSM identity")
    return f"{kind}/{ident}"


def read_source(path):
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("PRAGMA query_only=ON")
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("Invalid SQLite source")
        connection.row_factory = sqlite3.Row
        columns = "type,osmType,osmId,name,nameRaw,parentId,countryCode,lat,lon,tags,members,gradeTxt"
        rows = [dict(row) for row in connection.execute(f"SELECT {columns} FROM climbing_features WHERE upper(countryCode) IN ('RU','TR')")]
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    finally:
        connection.close()
    return rows, version


def collect(rows):
    features = {}
    for row in rows:
        ident = key(row)
        if ident in features:
            raise ValueError("Duplicate OSM identity")
        row = dict(row)
        row["name"] = (row.get("name") or row.get("nameRaw") or "").strip()
        row["countryCode"] = row["countryCode"].upper()
        features[ident] = row
    skipped, records, aliases = [], {}, {}

    def skip(ident, reason):
        skipped.append({"osm_id": ident, "name": features[ident]["name"], "reason": reason})

    def chain(ident):
        result, seen = [], set()
        while ident:
            if ident in seen:
                raise ValueError("Cycle in OSM parent graph")
            seen.add(ident)
            row = features.get(ident)
            if row is None:
                return None
            if result and row["countryCode"] != features[result[0]]["countryCode"]:
                return None
            result.append(ident)
            ident = f"relation/{int(row['parentId'])}" if row["parentId"] is not None else None
        return result

    def add(kind, ident, parent=None, name=None):
        row = features[ident]
        value = dict(kind=kind, external_id=ident, name=name or row["name"], country=row["countryCode"],
                     parent=parent, grade="", raw_grade=row.get("gradeTxt") or "", grade_system="",
                     latitude=row["lat"], longitude=row["lon"], url="https://www.openstreetmap.org/"+ident)
        if not value["name"] or len(value["name"]) > 200:
            skip(ident, "missing_or_long_name")
            return None
        if not -90 <= float(value["latitude"]) <= 90 or not -180 <= float(value["longitude"]) <= 180:
            raise ValueError("Invalid coordinates")
        record_key = kind+":"+ident
        if record_key in records and records[record_key] != value:
            raise ValueError("Conflicting source hierarchy")
        records[record_key] = value
        return record_key

    for ident, row in features.items():
        if row["type"] not in {"area", "crag", "route"}:
            continue
        lineage = chain(ident)
        if not lineage:
            skip(ident, "missing_or_cross_country_parent")
            continue
        root = features[lineage[-1]]
        if root["type"] not in {"area", "crag"}:
            skip(ident, "route_without_verified_crag_or_area")
            continue
        if not root["name"]:
            skip(ident, "unnamed_root")
            continue
        if not add("location", lineage[-1]):
            skip(ident, "invalid_root")
            continue
        if row["type"] == "area":
            continue
        if row["type"] == "crag" and len(lineage) == 1:
            continue  # standalone crag is a location; create sector only if routes require it
        crags = [x for x in lineage if features[x]["type"] == "crag"]
        if not crags:
            skip(ident, "route_without_verified_sector")
            continue
        # A crag node contained in a crag relation can be its map anchor, not
        # another sector. Collapse only explicit membership, identical name and
        # coincident geometry; never a global name-only merge.
        canonical = crags[0]
        while True:
            child = features[canonical]
            parent_id = f"relation/{child['parentId']}" if child["parentId"] else None
            parent = features.get(parent_id)
            if not parent or parent["type"] != "crag" or child["name"].casefold() != parent["name"].casefold():
                break
            members = json.loads(parent.get("members") or "[]")
            explicit = any(m.get("type") == child["osmType"] and m.get("ref") == child["osmId"] for m in members)
            close = abs(child["lat"]-parent["lat"]) < .0002 and abs(child["lon"]-parent["lon"]) < .0002
            if not explicit or not close:
                break
            aliases[canonical] = parent_id
            canonical = parent_id
        sector_name = features[canonical]["name"]
        if not sector_name:
            skip(ident, "unnamed_sector")
            continue
        ancestor_crags = [features[x]["name"] for x in lineage[lineage.index(canonical)+1:-1] if features[x]["type"] == "crag"]
        if ancestor_crags:
            sector_name = " / ".join(reversed(ancestor_crags)) + " / " + sector_name
        section = add("section", canonical, "location:"+lineage[-1], sector_name)
        if not section or row["type"] != "route":
            continue
        route = add("route", ident, section)
        if route:
            tags = json.loads(row.get("tags") or "{}")
            french = tags.get("climbing:grade:french", "").strip()
            if french and re.fullmatch(r"[3-9][abc]?[+]?", french, re.I):
                records[route].update(grade=french.upper(), grade_system="french")
            else:
                records[route]["grade_system"] = ",".join(k.removeprefix("climbing:grade:") for k in tags if k.startswith("climbing:grade:"))
    # Fail on same-name sections under one parent unless explicitly collapsed.
    names = {}
    for record_key, record in records.items():
        if record["kind"] == "section":
            identity = (record["parent"], record["name"])
            if identity in names and names[identity] != record_key:
                raise ValueError("Ambiguous same-name sectors; explicit mapping required: "+str(identity))
            names[identity] = record_key
    return records, skipped, aliases


def quote(value):
    if "\x00" in str(value):
        raise ValueError("NUL in SQL")
    return "'"+str(value).replace("'", "''")+"'"


def make_sql(records, bindings):
    ids = {k: bindings.get(k, "".join([r["kind"], "_", hashlib.sha256((SOURCE+":"+k).encode()).hexdigest()[:32]])) for k,r in records.items()}
    lines = ["BEGIN;", "SET LOCAL standard_conforming_strings=on;", "SELECT pg_advisory_xact_lock(718394139489);",
             "CREATE TEMP TABLE openclimbing_guard(ok boolean NOT NULL CHECK(ok)) ON COMMIT DROP;",
             "-- "+ATTRIBUTION, "-- https://www.openstreetmap.org/copyright | https://opendatacommons.org/licenses/odbl/1-0/"]
    for record_key, row in sorted(records.items(), key=lambda x: ({"location":0,"section":1,"route":2}[x[1]["kind"]], x[0])):
        ident = ids[record_key]
        table = {"location":"locations", "section":"sections", "route":"routes"}[row["kind"]]
        if record_key in bindings:
            condition = ("visibility='public' AND owner_id IS NULL AND country="+quote(COUNTRIES[row["country"]])) if row["kind"] == "location" else "location_id="+quote(ids[row["parent"]])
            lines.append(f"INSERT INTO openclimbing_guard SELECT EXISTS(SELECT 1 FROM {table} WHERE id={quote(ident)} AND {condition});")
        elif row["kind"] == "location":
            values = [ident,"public","outdoor",row["name"],COUNTRIES[row["country"]]]
            lines.append("INSERT INTO locations(id,visibility,type,name,country,latitude,longitude) VALUES("+",".join(map(quote,values))+f",{float(row['latitude'])},{float(row['longitude'])}) ON CONFLICT(id) DO NOTHING;")
        elif row["kind"] == "section":
            lines.append("INSERT INTO sections(id,location_id,type,name) VALUES("+",".join(map(quote,[ident,ids[row["parent"]],"sector",row["name"]]))+") ON CONFLICT(id) DO NOTHING;")
        else:
            lines.append("INSERT INTO routes(id,section_id,name,grade) VALUES("+",".join(map(quote,[ident,ids[row["parent"]],row["name"]]))+","+(quote(row["grade"]) if row["grade"] else "NULL")+") ON CONFLICT(id) DO NOTHING;")
        # Existing deterministic IDs must still point to public source records.
        if row["kind"] == "location":
            guard = "visibility='public' AND owner_id IS NULL AND country="+quote(COUNTRIES[row["country"]])
        else:
            parent_column = "location_id" if row["kind"] == "section" else "section_id"
            guard = parent_column+"="+quote(ids[row["parent"]])
        lines.append(f"INSERT INTO openclimbing_guard SELECT EXISTS(SELECT 1 FROM {table} WHERE id={quote(ident)} AND {guard});")
        ref_id="external_ref_"+hashlib.sha256((SOURCE+":"+record_key).encode()).hexdigest()[:32]
        values=[ref_id,SOURCE,row["kind"],row["external_id"],row["url"],ident]
        lines.append("INSERT INTO external_refs(id,system,entity_type,external_id,url,"+row["kind"]+"_id) VALUES("+",".join(map(quote,values))+") ON CONFLICT(system,entity_type,external_id) DO NOTHING;")
        lines.append("INSERT INTO openclimbing_guard SELECT EXISTS(SELECT 1 FROM external_refs WHERE system="+quote(SOURCE)+" AND entity_type="+quote(row["kind"])+" AND external_id="+quote(row["external_id"])+" AND "+row["kind"]+"_id="+quote(ident)+");")
    lines.append("COMMIT;")
    return "\n".join(lines)+"\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("--output", type=Path, default=Path("output/catalog/openclimbing"))
    parser.add_argument("--bind", action="append", default=[], help="Reviewed kind:osmType/osmId=existing_public_id")
    args=parser.parse_args()
    rows,version=read_source(args.database)
    records,skipped,aliases=collect(rows)
    bindings={}
    for binding in args.bind:
        k,sep,value=binding.partition("=")
        if not sep or k not in records or records[k]["kind"] not in {"location","section"} or not re.fullmatch(r"(?:location|section)_[a-zA-Z0-9_-]+", value):
            parser.error("Invalid or unknown explicit binding")
        bindings[k]=value
    args.output.mkdir(parents=True,exist_ok=True)
    with args.database.open("rb") as stream: digest=hashlib.file_digest(stream,"sha256").hexdigest()
    report=[f"SQLite source schema version: {version}",f"SHA-256: {digest}",ATTRIBUTION,
            "Source: https://openclimbing.org/export", "Coverage: partial OSM catalogue; not a complete country guidebook", ""]
    for code in COUNTRIES:
        source_counts=Counter(r["type"] for r in rows if r["countryCode"].upper()==code)
        target_counts=Counter(r["kind"] for r in records.values() if r["country"]==code)
        report.append(f"{code}: source {dict(source_counts)}; planned {dict(target_counts)}")
    report += [f"Skipped: {len(skipped)}",f"Explicit member anchors collapsed: {len(aliases)}",f"French grades: {sum(bool(r['grade']) for r in records.values())}"]
    geyik_sectors={k for k,r in records.items() if r['kind']=='section' and r['parent']=='location:relation/18501782'}
    geyik_routes=[r for r in records.values() if r['kind']=='route' and r['parent'] in geyik_sectors]
    report.append(f"Geyikbayiri: {len(geyik_sectors)} sectors, {len(geyik_routes)} routes, {sum(bool(r['grade']) for r in geyik_routes)} French grades")
    for name,data in [("catalog.csv",list(records.values())),("skipped.csv",skipped),
                      ("aliases.csv",[dict(osm_id=k,target=v) for k,v in aliases.items()])]:
        if not data:continue
        with (args.output/name).open("w",encoding="utf-8-sig",newline="") as stream:
            writer=csv.DictWriter(stream,fieldnames=list(data[0]));writer.writeheader();writer.writerows(data)
    (args.output/"report.txt").write_text("\n".join(report)+"\n",encoding="utf-8")
    (args.output/"import.sql").write_text(make_sql(records,bindings),encoding="utf-8")
    print("\n".join(report))


if __name__ == "__main__":
    main()
