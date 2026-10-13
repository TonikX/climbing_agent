"""Pure parser of published HTML links; never executes scripts or AJAX tokens."""
import hashlib
import re
import unicodedata
from dataclasses import dataclass, field, replace
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit, parse_qsl, urlencode
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup

COUNTRIES = {"RU": "Россия", "TR": "Турция"}
ORIGIN = "https://allclimb.com"


def country(value):
    aliases = {"russia": "RU", "россия": "RU", "turkey": "TR", "türkiye": "TR", "турция": "TR"}
    code = aliases.get(value.casefold(), value.upper())
    if code not in COUNTRIES:
        raise ValueError("Only Russia (RU) and Turkey (TR) are supported")
    return code


def canonical_url(value, base=ORIGIN):
    parsed = urlsplit(urljoin(base, value))
    if parsed.scheme != "https" or parsed.hostname != "allclimb.com" or parsed.port not in (None, 443) or parsed.username or parsed.password:
        raise ValueError("Only HTTPS URLs on allclimb.com are accepted")
    segments = [unicodedata.normalize("NFC", unquote(s)) for s in parsed.path.split("/") if s]
    if any(s in (".", "..") or "/" in s or "\\" in s for s in segments):
        raise ValueError("Invalid source path")
    if len(segments) < 2 or segments[0] != "ru" or segments[1] not in ("guides", "list", "areas"):
        raise ValueError("Unsupported catalogue URL")
    path = "/" + "/".join(quote(s, safe="-_.~") for s in segments)
    if segments[1] != "areas":
        path += "/"
    query = parse_qsl(parsed.query, keep_blank_values=True)
    if any(k != "page" or not v.isdigit() or not 1 <= int(v) <= 10000 for k, v in query) or len(query) > 1:
        raise ValueError("Only an ordinary numeric page parameter is accepted")
    return urlunsplit(("https", "allclimb.com", path, urlencode(query), ""))


def parts(url):
    return [unquote(s) for s in urlsplit(url).path.split("/") if s][2:]


def guide_url(values):
    return canonical_url("/ru/guides/" + "/".join(quote(x, safe="-_.~") for x in values))


@dataclass(frozen=True)
class Record:
    kind: str
    url: str
    name: str
    country: str
    parent: str | None = None
    region: str | None = None
    grade: str | None = None

    @property
    def external_id(self):
        # URL-derived identity, not a fabricated native AllClimb identifier.
        return "url:" + hashlib.sha256(self.url.encode()).hexdigest()


def merge_record(old, new):
    if old is None or old == new:
        return new
    if replace(old, grade=None) != replace(new, grade=None) or (old.grade and new.grade and old.grade != new.grade):
        raise ValueError("Conflicting entries for the same source URL")
    return replace(new, grade=new.grade or old.grade)


@dataclass
class Page:
    records: dict[str, Record] = field(default_factory=dict)
    links: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add(self, record):
        if not record.name or len(record.name) > 200 or (record.grade and len(record.grade) > 30):
            raise ValueError("Invalid catalogue field length")
        key = record.kind + ":" + record.url
        self.records[key] = merge_record(self.records.get(key), record)


def parse_html(html, source_url, source_country):
    source_url = canonical_url(source_url)
    code = country(source_country)
    prefix = parts(source_url)
    if not prefix or urlsplit(source_url).path.split("/")[2] not in ("guides", "list"):
        raise ValueError("HTML input needs a country-reviewed region/area URL")
    soup = BeautifulSoup(html, "html.parser")
    page = Page()
    for link in soup.select('a[href]'):
        try:
            url = canonical_url(link["href"], source_url)
        except ValueError:
            continue
        path = parts(url)
        if urlsplit(url).path.split("/")[2] != "guides" or path[:len(prefix)] != prefix or not 2 <= len(path) <= 4:
            continue
        region, area = path[:2]
        parent = guide_url(path[:2])
        page.add(Record("location", parent, area, code, region=region))
        if len(path) >= 3:
            sector = guide_url(path[:3])
            page.add(Record("section", sector, path[2], code, parent=parent, region=region))
        if len(path) == 4:
            grade_tag = link.find("b")
            grade = grade_tag.get_text(" ", strip=True) if grade_tag else None
            clone = BeautifulSoup(str(link), "html.parser")
            for child in clone.select("b, span, i, img"):
                child.decompose()
            label = re.sub(r"^\s*\d+\.\s*", "", clone.get_text(" ", strip=True)).strip()
            name = label if "news-preview-title" in link.get("class", []) and label else path[3]
            page.add(Record("route", guide_url(path), name, code, parent=sector, region=region, grade=grade))
        elif url not in page.links:
            page.links.append(url)
    for link in soup.select('a[rel~="next"]'):
        url = canonical_url(link.get("href", ""), source_url)
        if parts(url)[:len(prefix)] == prefix:
            page.links.append(url)
    if soup.select(".load-more, [onclick*='loadMore'], [onclick*='moreButtonPressed']"):
        page.warnings.append("ajax_continuation_not_fetched")
    if not page.records:
        raise ValueError("No supported catalogue entries in HTML; empty result is not a successful import")
    return page


def parse_sitemap(xml, area_countries):
    """Sitemap has area URLs, not the whole route catalogue. Country is reviewed input."""
    if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
        raise ValueError("XML entities are not accepted")
    root = ET.fromstring(xml)
    page = Page(warnings=["sitemap_only_area_names", "country_from_reviewed_mapping"])
    mapping = {unicodedata.normalize("NFC", name).casefold(): country(code) for name, code in area_countries.items()}
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] != "loc" or not node.text:
            continue
        try:
            url = canonical_url(node.text.strip())
        except ValueError:
            continue
        if urlsplit(url).path.split("/")[2] != "areas":
            continue
        path = parts(url)
        if len(path) != 1 or not path[0].endswith("_скалолазный_район"):
            continue
        name = path[0].removesuffix("_скалолазный_район")
        if name.casefold() in mapping:
            page.add(Record("location", url, name, mapping[name.casefold()]))
    if not page.records:
        raise ValueError("No sitemap areas match the reviewed country mapping")
    return page
