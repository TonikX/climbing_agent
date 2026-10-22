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
    style = raw.get("style", getattr(current, "style", None))
    style_evidence = (style == "with_falls" and ("style" in raw or raw.get("falls") != 0)) or (
        style == "with_hangs" and ("style" in raw or raw.get("hangs") != 0))
    return bool(style_evidence or
        (falls is not None and falls > 0) or (hangs is not None and hangs > 0) or re.search(
        r"срыв|сорв|завис|повис|с\s+перерыв", normalized))


def normalized_style(raw: dict, current=None) -> str:
    style = str(raw.get("style", getattr(current, "style", "unknown")) or "unknown")
    if style not in ("onsight", "flash", "redpoint", "with_falls", "with_hangs", "unknown"):
        raise HTTPException(422, "Unknown style; top_rope belongs in belay")
    if raw.get("falls", getattr(current, "falls", 0)):
        return "with_falls"
    if raw.get("hangs", getattr(current, "hangs", 0)):
        return "with_hangs"
    if style in ("with_falls", "with_hangs") and outcome(raw, current)["clean_ascent"] is True:
        return "unknown"
    return "unknown" if style in ("onsight", "flash", "redpoint") and outcome(raw, current)["clean_ascent"] is not True else style


def validated_belay(raw: dict, current=None) -> str:
    value = raw.get("belay", getattr(current, "belay", None))
    if value not in ("lead", "top_rope", "auto_belay", "bouldering"):
        raise HTTPException(422, "Specify belay: lead, top_rope, auto_belay or bouldering")
    return value


def outcome(raw: dict, current=None, *, require_complete=True) -> dict:
    if "hangs" in raw and raw["hangs"] is not None and (type(raw["hangs"]) is not int or raw["hangs"] < 0):
        raise HTTPException(422, "hangs must be a non-negative integer or null")
    if any(key in raw and raw[key] is not None and type(raw[key]) is not bool
           for key in ("reachedTop", "cleanAscent")):
        raise HTTPException(422, "reachedTop and cleanAscent must be boolean or null")
    if require_complete and any(key in raw and raw[key] is None for key in ("reachedTop", "cleanAscent")):
        raise HTTPException(422, "reachedTop and cleanAscent cannot be null")
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
    if clean_style and not nonclean and raw.get("reachedTop") is not False and raw.get("cleanAscent") is not False:
        if "cleanAscent" not in raw:
            clean = True
        if "reachedTop" not in raw:
            top = True
    if raw.get("cleanAscent") is True and raw.get("reachedTop") is not False and not nonclean:
        top = True
    if top is False or nonclean:
        clean = False
    if clean is True:
        top = True
    if require_complete and (top is None or clean is None):
        missing = [key for key, value in (("reachedTop", top), ("cleanAscent", clean)) if value is None]
        raise HTTPException(422, "Specify " + ", ".join(missing))
    # Retain the historical value on edits for audit; readers use the two facts.
    legacy = raw.get("result") or getattr(current, "result", None)
    if legacy is None:
        legacy = "send" if clean is True else "project" if clean is False else "unknown"
    return {"reached_top": top, "clean_ascent": clean, "result": legacy}
