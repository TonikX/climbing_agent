"""Opt-in acceptance fixture/HTTP load. Refuses to seed a non-test database."""
import argparse
import asyncio
import hashlib
import json
import os
import time
from collections import Counter

import httpx
from sqlalchemy import text

from app.config import get_settings


def token(index):
    return hashlib.sha256(f"isolated-load-test:{index}".encode()).hexdigest()


async def seed():
    cfg = get_settings()
    if not cfg.db_name.endswith("_load_test") or os.environ.get("CONFIRM_ISOLATED_LOAD_TEST") != "yes":
        raise ValueError("Only an explicitly confirmed *_load_test database can be seeded")
    from app.db import engine
    async with engine.begin() as conn:
        if await conn.scalar(text("SELECT count(*) FROM training_sessions")):
            raise ValueError("Use an empty isolated test database")
        await conn.execute(text("""INSERT INTO users(id,name,timezone,status,role)
            SELECT 'load_user_'||n,'Load user','Europe/Moscow','active','user' FROM generate_series(1,10000) n"""))
        await conn.execute(text("""INSERT INTO training_sessions(id,user_id,status,local_date,timezone,environment,version)
            SELECT 'load_training_'||n,'load_user_'||(((n-1)/10)+1),'completed',CURRENT_DATE-(n%28),
                   'Europe/Moscow','indoor',1 FROM generate_series(1,100000) n"""))
        await conn.execute(text("""INSERT INTO route_attempts(id,training_id,sequence,attempts,result,reached_top,clean_ascent,
                falls,hangs,style,belay,feel,is_test,route_session_key,route_snapshot)
            SELECT 'load_attempt_'||n,'load_training_'||(((n-1)/10)+1),((n-1)%10)+1,1,'send',true,true,
                0,0,CASE n%3 WHEN 0 THEN 'onsight' WHEN 1 THEN 'flash' ELSE 'redpoint' END,
                CASE n%2 WHEN 0 THEN 'lead' ELSE 'top_rope' END,'unknown',false,'load_route_'||n,
                jsonb_build_object('name','Load route','grade',CASE n%2 WHEN 0 THEN '6B+' ELSE '6B/6B+' END)
            FROM generate_series(1,1000000) n"""))
        for n in range(1, 101):
            await conn.execute(text("""INSERT INTO auth_sessions(id,user_id,token_hash,expires_at)
                VALUES (:id,:uid,:hash,now()+interval '4 hours')"""), {"id": f"load_auth_{n}", "uid": f"load_user_{n}",
                "hash": hashlib.sha256(token(n).encode()).hexdigest()})
        await conn.execute(text("ANALYZE"))
    await engine.dispose()
    print("Seeded 10000 users, 100000 trainings, 1000000 attempts; 100 test sessions")


async def run(args):
    statuses, latencies = Counter(), []
    locks = [asyncio.Lock() for _ in range(100)]
    versions = [1]*100
    semaphore = asyncio.Semaphore(100)
    async with httpx.AsyncClient(base_url=args.url, timeout=15,
                                 limits=httpx.Limits(max_connections=100, max_keepalive_connections=100)) as client:
        async def request(index):
            n = index % 100
            headers = {"Authorization": "Bearer "+token(n+1)}
            started = time.monotonic()
            try:
                async with semaphore:
                    if index % 5 == 0:
                        async with locks[n]:
                            response = await client.patch(f"/api/v1/trainings/load_training_{n*10+1}", headers=headers,
                                json={"expected_version": versions[n], "notes": "Synthetic load test"})
                            if response.status_code == 200:
                                versions[n] = response.json()["version"]
                    else:
                        response = await client.get("/api/v1/statistics/month", headers=headers)
                statuses[response.status_code] += 1
            except httpx.HTTPError:
                statuses["transport_error"] += 1
            latencies.append((time.monotonic()-started)*1000)
        start, tasks, index = time.monotonic(), set(), 0
        while time.monotonic()-start < args.seconds:
            task = asyncio.create_task(request(index))
            tasks.add(task)
            task.add_done_callback(tasks.discard)
            index += 1
            await asyncio.sleep(max(0, start+index/args.rps-time.monotonic()))
        await asyncio.gather(*tasks)
    values = sorted(latencies)
    report = {"seconds": args.seconds, "target_rps": args.rps, "users": 100, "responses": dict(statuses),
              "p95_ms": values[int((len(values)-1)*0.95)] if values else None}
    print(json.dumps(report, indent=2))
    if statuses.get(200, 0) != len(values) or not values or report["p95_ms"] > 500:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", action="store_true")
    parser.add_argument("--url", default="http://api:8000")
    parser.add_argument("--seconds", type=int, default=1800)
    parser.add_argument("--rps", type=int, default=20)
    args = parser.parse_args()
    if args.seconds <= 0 or not 1 <= args.rps <= 50:
        parser.error("Use positive duration and 1..50 rps")
    asyncio.run(seed() if args.seed else run(args))
