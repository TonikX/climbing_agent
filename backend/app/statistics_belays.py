"""Reached route sessions, independently counted for each belay type."""

def ascents_by_belay(attempts):
    """One recorded reached attempt is one ascent, even if its route repeats."""
    result = {key: dict(total=0, clean=0, nonClean=0, unknownClean=0)
              for key in ("lead", "top_rope", "auto_belay", "bouldering", "unknown")}
    for attempt in attempts:
        if attempt.is_test or attempt.reached_top is not True:
            continue
        counts = result.get(attempt.belay, result["unknown"])
        counts["total"] += 1
        field = "clean" if attempt.clean_ascent is True else "nonClean" if attempt.clean_ascent is False else "unknownClean"
        counts[field] += 1
    return result


def reached_by_belay(attempts):
    result = {}
    for belay in ("lead", "top_rope", "auto_belay", "bouldering", "unknown"):
        groups = {}
        for attempt in attempts:
            key = attempt.belay if attempt.belay in ("lead", "top_rope", "auto_belay", "bouldering") else "unknown"
            if not attempt.is_test and key == belay and attempt.reached_top is True:
                groups.setdefault(attempt.route_session_key or attempt.id, []).append(attempt)
        clean = sum(any(a.clean_ascent is True for a in group) for group in groups.values())
        nonclean = sum(not any(a.clean_ascent is True for a in group) and
                       any(a.clean_ascent is False for a in group) for group in groups.values())
        result[belay] = {"total":len(groups), "clean":clean, "nonClean":nonclean,
                         "unknownClean":len(groups)-clean-nonclean}
    return result
