"""Canonical grade spelling shared by input, catalogue matching and statistics."""
import re


def normalize_grade(value: str | None) -> str | None:
    if value is None:
        return None
    value = re.sub(r"\s+", "", value.upper()).translate(str.maketrans("АВС", "ABC"))
    parts = value.split("/")
    if all(re.fullmatch(r"\d+[ABC]?\+?", part) for part in parts):
        value = "/".join(sorted(set(parts), key=lambda part: (int(re.match(r"\d+", part)[0]), part)))
    return value
