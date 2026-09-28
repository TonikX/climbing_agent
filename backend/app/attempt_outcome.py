"""Normalize outcome facts and keep climbing terms internally consistent."""
import re

from fastapi import HTTPException


def has_nonclean_evidence(raw: dict, current=None) -> bool:
    falls = raw.get("falls", getattr(current, "falls", None))
    notes = raw.get("notes", getattr(current, "notes", None)) or ""
    # Remove explicit negations before looking for a fall, hang or rope rest.
    normalized = re.sub(
        r"без\s+(?:срыв|завис)\w*(?:\s+и\s+(?:срыв|завис)\w*)?", "", str(notes).lower())
    return bool((falls is not None and falls > 0) or re.search(
        r"срыв|сорв|завис|повис|с\s+перерыв", normalized))


def normalized_style(raw: dict, current=None) -> str:
    style = str(raw.get("style", getattr(current, "style", "unknown")) or "unknown")
    return "unknown" if style in ("onsight", "flash", "redpoint") and has_nonclean_evidence(raw, current) else style


def outcome(raw: dict, current=None) -> dict:
    top = getattr(current, "reached_top", None)
    clean = getattr(current, "clean_ascent", None)
    falls = raw.get("falls", getattr(current, "falls", None))
    if falls is not None and (type(falls) is not int or falls < 0):
        raise HTTPException(422, "falls must be a non-negative integer or null")
    if "result" in raw and raw["result"] not in ("send", "project", "attempted", "unknown"):
        raise HTTPException(422, "Unknown legacy result")
    if "result" in raw and not any(k in raw for k in ("reachedTop", "cleanAscent")):
        # Compatibility with older clients; send historically included hangs.
        top = True if raw["result"] == "send" else None
        clean = False if raw["result"] == "project" else None
    if "reachedTop" in raw:
        top = raw["reachedTop"]
    if "cleanAscent" in raw:
        clean = raw["cleanAscent"]
    style = raw.get("style", getattr(current, "style", "unknown"))
    clean_style = style in ("onsight", "flash", "redpoint")
    nonclean = has_nonclean_evidence(raw, current)
    if clean_style:
        clean = False if nonclean or raw.get("cleanAscent") is False else True
        top = True
    if any(value is not None and type(value) is not bool for value in (top, clean)):
        raise HTTPException(422, "reachedTop and cleanAscent must be boolean or null")
    if top is False or nonclean:
        clean = False
    if clean is True:
        top = True
    # Retain the historical value on edits for audit; readers use the two facts.
    legacy = raw.get("result") or getattr(current, "result", None)
    if legacy is None:
        legacy = "send" if clean is True else "project" if clean is False else "unknown"
    return {"reached_top": top, "clean_ascent": clean, "result": legacy}
