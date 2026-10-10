"""Normalize outcome facts and keep climbing terms internally consistent."""
import re

from fastapi import HTTPException


def has_nonclean_evidence(raw: dict, current=None) -> bool:
    falls = raw.get("falls", getattr(current, "falls", None))
    hangs = raw.get("hangs", getattr(current, "hangs", None))
    notes = raw.get("notes", getattr(current, "notes", None)) or ""
    # Remove explicit negations before looking for a fall, hang or rope rest.
    normalized = re.sub(
        r"без\s+(?:срыв|завис)\w*(?:\s+и\s+(?:срыв|завис)\w*)?", "", str(notes).lower())
    normalized = re.sub(
        r"\b(?:срыв|завис)\w*(?:\s+и\s+(?:срыв|завис)\w*)?\s+не\s+было\b|"
        r"\bне\s+было\s+(?:срыв|завис)\w*(?:\s+и\s+(?:срыв|завис)\w*)?|"
        r"\bне\s+(?:сорв|завис|повис)\w*", "", normalized)
    return bool((falls is not None and falls > 0) or (hangs is not None and hangs > 0) or re.search(
        r"срыв|сорв|завис|повис|с\s+перерыв", normalized))


def normalized_style(raw: dict, current=None) -> str:
    style = str(raw.get("style", getattr(current, "style", "unknown")) or "unknown")
    return "unknown" if style in ("onsight", "flash", "redpoint") and outcome(raw, current)["clean_ascent"] is not True else style


def outcome(raw: dict, current=None) -> dict:
    if "hangs" in raw and raw["hangs"] is not None and (type(raw["hangs"]) is not int or raw["hangs"] < 0):
        raise HTTPException(422, "hangs must be a non-negative integer or null")
    if any(key in raw and raw[key] is not None and type(raw[key]) is not bool
           for key in ("reachedTop", "cleanAscent")):
        raise HTTPException(422, "reachedTop and cleanAscent must be boolean or null")
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
        if "cleanAscent" not in raw:
            clean = True
        if "reachedTop" not in raw:
            top = True
    if top is False or nonclean:
        clean = False
    if clean is True:
        top = True
    # Retain the historical value on edits for audit; readers use the two facts.
    legacy = raw.get("result") or getattr(current, "result", None)
    if legacy is None:
        legacy = "send" if clean is True else "project" if clean is False else "unknown"
    return {"reached_top": top, "clean_ascent": clean, "result": legacy}
