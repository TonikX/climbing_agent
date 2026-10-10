"""Bounded, payload-free request metrics. Identifiers never become metric labels."""
import logging
import time
from collections import defaultdict, deque
from uuid import uuid4

from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

samples = deque(maxlen=10000)
log = logging.getLogger("api")


async def requests(request, call_next):
    request_id, start = uuid4().hex, time.monotonic()
    request.state.request_id = request_id
    try:
        response = await call_next(request)
    except Exception as exc:
        log.error("request_failed request_id=%s code=%s", request_id, type(exc).__name__)
        response = JSONResponse(status_code=409 if isinstance(exc, IntegrityError) else 503,
                                content={"detail": "Request could not be committed", "request_id": request_id})
    response.headers["X-Request-ID"] = request_id
    response.headers["Cache-Control"] = "no-store"
    route = getattr(request.scope.get("route"), "path", "unmatched")
    elapsed = (time.monotonic()-start)*1000
    samples.append((route, response.status_code, elapsed))
    if response.status_code >= 500 or elapsed > 500:
        log.warning("request request_id=%s route=%s status=%s ms=%.0f", request_id, route, response.status_code, elapsed)
    return response


def metrics():
    groups = defaultdict(list)
    for route, status, elapsed in list(samples):
        groups[(route, status)].append(elapsed)
    return [{"route": route, "status": status, "count": len(values),
             "p95_ms": sorted(values)[int((len(values)-1)*0.95)]} for (route, status), values in groups.items()]
