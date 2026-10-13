"""CLI for a later job: reviewed HTML snapshots or respectful public GET crawling."""
import argparse
import asyncio
from collections import Counter, deque
from pathlib import Path
import json
import time
from urllib.robotparser import RobotFileParser

import httpx

from app.allclimb_html import ORIGIN, canonical_url, country, parse_html, parse_sitemap, merge_record

USER_AGENT = "ClimbingJournalImporter/1.0 (AI-assisted; public climbing catalogue)"
MAX_BYTES = 2_000_000


class PublicHtmlClient:
    def __init__(self, client, delay=2):
        self.client, self.delay, self.last_request = client, max(2, delay), 0
        self.robots = None

    async def _read(self, url):
        await asyncio.sleep(max(0, self.delay - (time.monotonic() - self.last_request)))
        self.last_request = time.monotonic()
        async with self.client.stream("GET", url) as response:
            if response.status_code in (401, 403, 429):
                raise RuntimeError(f"Source denied GET: HTTP {response.status_code}; stop, do not retry or bypass")
            response.raise_for_status()
            if response.is_redirect:
                raise RuntimeError("Redirect requires source review; not followed automatically")
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > MAX_BYTES:
                    raise ValueError("Source document exceeds 2 MB")
            return bytes(body)

    async def get(self, url):
        url = canonical_url(url)
        if self.robots is None:
            raw = await self._read(ORIGIN + "/robots.txt")
            if b"user-agent:" not in raw.lower():
                raise RuntimeError("Cannot verify robots.txt rules; catalogue fetch stopped")
            self.robots = RobotFileParser()
            self.robots.parse(raw.decode("utf-8", errors="strict").splitlines())
            # This tool is AI-assisted: respect explicit AI crawler restrictions too.
            agents = (USER_AGENT, "GPTBot", "ChatGPT-User", "OAI-SearchBot")
            if not all(self.robots.can_fetch(agent, url) for agent in agents):
                raise RuntimeError("robots.txt prohibits this AI-assisted catalogue fetch")
            delays = [self.robots.crawl_delay(agent) or 0 for agent in agents]
            self.delay = max(self.delay, *delays)
        if not all(self.robots.can_fetch(agent, url) for agent in (USER_AGENT, "GPTBot", "ChatGPT-User", "OAI-SearchBot")):
            raise RuntimeError("robots.txt prohibits this catalogue URL")
        return await self._read(url)


async def collect(args):
    records, documents, warnings = {}, [], []
    def accept(page, url, mode):
        for key, value in page.records.items():
            records[key] = merge_record(records.get(key), value)
        warnings.extend(page.warnings)
        documents.append({"url": url, "mode": mode, "records": len(page.records)})
    for code, url, path in args.html:
        value = Path(path).read_bytes()
        if len(value) > MAX_BYTES:
            raise ValueError("HTML snapshot exceeds 2 MB")
        accept(parse_html(value, url, code), canonical_url(url), "saved_html")
    if args.sitemap_file:
        mapping = {}
        for value in args.area_country:
            name, separator, code = value.rpartition("=")
            if not separator or not name:
                raise ValueError("Use --area-country 'Name=RU' or 'Name=TR'")
            mapping[name] = country(code)
        value = Path(args.sitemap_file).read_bytes()
        if len(value) > MAX_BYTES:
            raise ValueError("Sitemap snapshot exceeds 2 MB")
        accept(parse_sitemap(value, mapping), "https://allclimb.com/sitemap.xml", "saved_sitemap")
    queue = deque((country(code), canonical_url(url)) for code, url in args.seed)
    seen = set()
    if queue:
        async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=False) as client:
            fetcher = PublicHtmlClient(client, args.delay)
            while queue and len(seen) < args.max_pages:
                code, url = queue.popleft()
                if url in seen:
                    continue
                seen.add(url)
                page = parse_html(await fetcher.get(url), url, code)
                accept(page, url, "public_get")
                queue.extend((code, link) for link in page.links if link not in seen)
    if queue:
        warnings.append("page_limit_reached")
    if not records:
        raise ValueError("No catalogue input: specify --html, --sitemap-file or --seed")
    counts = dict(Counter(record.kind for record in records.values()))
    return records, {"coverage": "partial_html", "counts": counts, "countries": sorted({r.country for r in records.values()}),
                     "documents": documents, "warnings": sorted(set(warnings))}


async def run(args):
    if args.apply:
        from sqlalchemy.ext.asyncio import create_async_engine
        from app.config import get_settings
        from app.allclimb_store import import_catalog
        settings = get_settings()
        if not settings.db_password.get_secret_value():
            raise ValueError("Database credentials are required for --apply")
        engine = create_async_engine(settings.database_url, hide_parameters=True, pool_size=1, max_overflow=0)
        try:
            result = await import_catalog(engine, lambda: collect(args))
        finally:
            await engine.dispose()
    else:
        _, result = await collect(args)
        result["status"] = "dry_run_partial"
    print(json.dumps(result, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--html", nargs=3, action="append", default=[], metavar=("COUNTRY", "SOURCE_URL", "FILE"))
    parser.add_argument("--sitemap-file")
    parser.add_argument("--area-country", action="append", default=[])
    parser.add_argument("--seed", nargs=2, action="append", default=[], metavar=("COUNTRY", "URL"))
    parser.add_argument("--max-pages", type=int, choices=range(1, 501), default=100, metavar="1..500")
    parser.add_argument("--delay", type=float, default=2)
    parser.add_argument("--apply", action="store_true", help="Write public catalogue and report to PostgreSQL")
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except (ValueError, RuntimeError, httpx.HTTPError) as exc:
        parser.exit(1, str(exc) + "\n")


if __name__ == "__main__":
    main()
