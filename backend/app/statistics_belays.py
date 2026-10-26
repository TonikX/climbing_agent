"""Reached route sessions, independently counted for each belay type."""
def reached_by_belay(attempts):
    result = {}
    for belay in ("lead", "top_rope"):
        groups = {}
        for attempt in attempts:
            if not attempt.is_test and attempt.belay == belay and attempt.reached_top is True:
                groups.setdefault(attempt.route_session_key or attempt.id, []).append(attempt)
        clean = sum(any(a.clean_ascent is True for a in group) for group in groups.values())
        nonclean = sum(not any(a.clean_ascent is True for a in group) and
                       any(a.clean_ascent is False for a in group) for group in groups.values())
        result[belay] = {"total":len(groups), "clean":clean, "nonClean":nonclean,
                         "unknownClean":len(groups)-clean-nonclean}
    return result
