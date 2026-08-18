"""
session_service — thin presence registry: which users currently have a live
WebSocket connection to direct_msg.

Why this exists as its own service instead of living inside direct_msg's own
process: a WebSocket connection is a live socket, and only the process that
accepted it can actually push a message down it — so direct_msg always
physically holds the socket, no matter what. What session_service adds is a
place to look up "is user X online" that isn't tied to one specific
direct_msg process. Today there is exactly one direct_msg instance, so this
is almost redundant with a local dict inside direct_msg itself — but keeping
presence in its own service means that if direct_msg is ever run as multiple
replicas (a Day 8+ backlog idea, not this week), only this service's storage
needs to change (e.g. in-memory dict -> Redis), not the architecture. The
alternative — skip this service and track presence only inside direct_msg —
is simpler today but would have to be pulled back out into its own service
the moment direct_msg scales past one instance.

Not reachable through the gateway/nginx — direct_msg is the only caller, over
the compose-internal network, so there is no X-User-Id/auth_request model
here the way every gateway-facing service has. direct_msg has already
authenticated the caller itself (see direct_msg/main.py's module docstring
for how) before it ever tells us who connected.

State is a plain in-memory dict, same "doesn't survive a restart" tradeoff as
every other build-week service in this repo (no migration tool, no Redis this
week) — acceptable because a restart just means every connected user's
browser reconnects and re-registers, same as a real client already has to
handle a dropped Wi-Fi connection.
"""

import datetime
import time

from fastapi import FastAPI, Request, Response
from pydantic import BaseModel
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

app = FastAPI(title="session_service")

# --- Observability (Day 6): generic request metrics, same pattern as every
# other service in this repo (see auth_service/main.py for the full walk-
# through of why each piece is here) ------------------------------------
REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests received by this service",
    ["method", "path", "status"],
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "path"],
)


@app.middleware("http")
async def track_requests(request: Request, call_next):
    """Times every request and records it under the generic HTTP metrics."""
    start = time.perf_counter()
    response = await call_next(request)
    REQUEST_LATENCY.labels(request.method, request.url.path).observe(
        time.perf_counter() - start
    )
    REQUEST_COUNT.labels(request.method, request.url.path, response.status_code).inc()
    return response


@app.get("/metrics")
def metrics():
    """Serializes the in-memory counters/histograms for Prometheus to scrape.
    No auth: only the Prometheus container (internal compose network) calls this.
    """
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

# user_id -> ISO timestamp of when the current connection was registered.
# A dict, not a set, so /session/{user_id} can report *when* someone came
# online — useful for debugging ("did this client actually connect recently,
# or is this a stale entry left behind by a direct_msg crash that skipped
# the disconnect call?").
online_users: dict[str, str] = {}


class SessionRequest(BaseModel):
    """Body shape for connect/disconnect.

    Why the id travels in the body, not a header: unlike every gateway-facing
    service, there is no auth_request step in front of this one setting a
    trusted X-User-Id — direct_msg is the sole, already-authenticated caller,
    so it just tells us directly who came online or went offline.
    """

    user_id: str


@app.post("/session/connect")
def connect(req: SessionRequest):
    """Mark a user online. Called by direct_msg right after it accepts that
    user's WebSocket connection."""
    online_users[req.user_id] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return {"status": "connected", "user_id": req.user_id}


@app.post("/session/disconnect")
def disconnect(req: SessionRequest):
    """Mark a user offline. Called by direct_msg when that user's WebSocket
    closes (tab closed, network drop, etc.)."""
    # .pop with a default: disconnecting a user who was never registered (or
    # already removed) is a no-op, not an error — direct_msg's cleanup path
    # shouldn't have to first check whether connect() ever succeeded.
    online_users.pop(req.user_id, None)
    return {"status": "disconnected", "user_id": req.user_id}


@app.get("/session/{user_id}")
def get_status(user_id: str):
    """Look up whether a specific user currently has a live connection.

    Not called by direct_msg yet — Day 4's chat only needs match
    verification + persistence, not "is the other person online right now"
    — but this is the seam a future online-indicator/read-receipt feature
    would hang off of.
    """
    connected_at = online_users.get(user_id)
    return {"user_id": user_id, "online": connected_at is not None, "connected_at": connected_at}


@app.get("/health")
def health():
    """Liveness probe so compose/other tooling can tell the app is up."""
    return {"status": "ok"}
