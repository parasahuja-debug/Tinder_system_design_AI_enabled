"""
direct_msg — WebSocket chat between two matched users, with persisted history.

Why this is the one place the "gateway is the only thing that authenticates"
rule bends: nginx's `auth_request` (used by every other protected route) does
not compose with a WebSocket upgrade, and a browser cannot set an
`Authorization` header on a WebSocket connection at all. So this service
authenticates itself, at connect time: the client offers the JWT as the
second entry of the WebSocket subprotocol list (`new WebSocket(url, ['bearer',
token])`), which becomes the `Sec-WebSocket-Protocol` request header — a
normal HTTP header that survives nginx's proxy unmodified, and (unlike a
query param) never lands in a URL, so it never ends up in an access log,
browser history, or a Referer header. This service then makes one plain HTTP
call to auth-service's existing `/validate` endpoint (the same one nginx
calls internally for every other route) to resolve the real user_id — rather
than decoding the JWT itself, which would require duplicating JWT_SECRET into
this service's env and breaking the invariant stated in auth_service/
CLAUDE.md that auth_service is the only service that knows it.

Once the caller's identity is resolved, this service makes a second HTTP
call, to matcher-service's `GET /matches/{match_id}`, to confirm the match
exists and this caller is actually one of its two participants — see that
endpoint's docstring in matcher_service/main.py for why. Both checks happen
once, at connection time, not per message.
"""

import os
import time
import uuid

import httpx
from fastapi import FastAPI, Header, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from sqlalchemy import Column, DateTime, String, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.sql import func
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

WS_AUTH_FAILED = 4401  # custom close code (4000-4999 range is reserved for app use): bad/missing token
WS_FORBIDDEN = 4403  # custom close code: token is valid but caller isn't in this match

# --- Configuration from the environment ------------------------------------
# Same "read from env, not hardcoded" convention as every other service's
# DATABASE_URL, inlined here rather than a separate config.py to stay
# consistent with every existing service in the repo. These three URLs are
# new to this service specifically: it's the first service that talks to
# other services over HTTP rather than just reading the shared DB, so it
# needs to know where they live.
DATABASE_URL = os.environ["DATABASE_URL"]
AUTH_SERVICE_URL = os.environ.get("AUTH_SERVICE_URL", "http://auth-service:8002")
MATCHER_SERVICE_URL = os.environ.get("MATCHER_SERVICE_URL", "http://matcher-service:8004")
SESSION_SERVICE_URL = os.environ.get("SESSION_SERVICE_URL", "http://session-service:8006")

# --- Database wiring ---------------------------------------------------------
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class Message(Base):
    """One row per sent chat message.

    Why a generated uuid `id` rather than reusing some natural key (unlike
    Swipe in matcher_service, which reuses (swiper_id, target_id)): a message
    has no natural key of its own — the same two people can send arbitrarily
    many messages in the same match, so nothing about the row's content is
    unique on its own.
    """

    __tablename__ = "messages"

    id = Column(String, primary_key=True)  # uuid; a message has no natural key, see docstring above

    # Which chat thread this belongs to. Indexed because the only query this
    # service ever runs against history is "every message in this thread, in
    # order" (see get_history below) — without the index that's a full table
    # scan once message volume grows.
    match_id = Column(String, nullable=False, index=True)

    # Who sent it — always the user_id this service itself resolved via
    # auth-service's /validate at connect time, never taken from the message
    # payload the client sends. Same "identity comes from the trusted side,
    # never the body" rule every other service follows for X-User-Id.
    sender_id = Column(String, nullable=False)

    body = Column(String, nullable=False)  # the message text itself

    # server_default=func.now(), not a client-supplied timestamp: the DB
    # clock is the one source of truth for ordering, so two messages can
    # never claim the same "when" based on clock skew between two users'
    # browsers.
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# Build-week convention, same as every other service: no migration tool,
# each service creates its own tables on startup.
Base.metadata.create_all(bind=engine)

app = FastAPI(title="direct_msg")

# --- Observability (Day 6): generic request metrics, same pattern as every
# other service in this repo (see auth_service/main.py for the full walk-
# through of why each piece is here). Note: this only ever sees /chat/
# history, /health, and /metrics — the WebSocket route below never goes
# through HTTP middleware, so it can't appear in these two. -----------------
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


# Business metric, not a generic HTTP one: the plan asks for chat message
# counts specifically. Since messages flow entirely through the WebSocket
# route (which bypasses HTTP middleware, see above), this has no generic
# fallback to ride along on — it's incremented by hand inside the message
# loop below, right after a message is actually persisted.
CHAT_MESSAGE_COUNT = Counter("chat_messages_total", "Total chat messages persisted")

# user_id -> the live WebSocket this process is holding for them right now.
# This is the actual socket registry — distinct from session_service's
# online/offline bookkeeping (see this module's docstring and session_
# service/main.py for why those are two different things). Only entries for
# users currently connected to *this* direct_msg process ever appear here,
# which is exactly the limitation session_service exists to eventually
# paper over if this service is ever run as more than one instance.
connections: dict[str, WebSocket] = {}


async def resolve_user_id(token: str) -> str | None:
    """Ask auth-service whether this token is valid, and if so, who it's for.

    Why an HTTP call instead of decoding the JWT locally: see this module's
    docstring — direct_msg deliberately does not know JWT_SECRET. Returns
    None on any failure (expired/invalid token, auth-service unreachable);
    the caller (the WebSocket endpoint) is responsible for closing the
    connection when this comes back empty.
    """
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                f"{AUTH_SERVICE_URL}/validate",
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.RequestError:
            return None
    if resp.status_code != 200:
        return None
    # /validate puts the id on an X-User-Id *response header* (see auth_
    # service/main.py) precisely so nginx's auth_request_set can grab it —
    # we're reusing that same response shape here, just reading it ourselves
    # instead of nginx doing it for us.
    return resp.headers.get("x-user-id")


async def verify_match(match_id: str, user_id: str) -> dict | None:
    """Ask matcher-service whether this match exists and this user is in it.

    Returns the match row ({match_id, user_a_id, user_b_id}) on success so
    the caller can also learn who "the other participant" is, or None on any
    failure (no such match, user isn't a participant, matcher-service
    unreachable) — same "collapse every failure reason into one refusal"
    shape as resolve_user_id above, for the same reason: the WebSocket
    endpoint only needs "can this connection proceed?", not which of several
    reasons it can't.
    """
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(f"{MATCHER_SERVICE_URL}/matches/{match_id}", params={"user_id": user_id})
        except httpx.RequestError:
            return None
    if resp.status_code != 200:
        return None
    return resp.json()


@app.websocket("/chat/ws/{match_id}")
async def chat(websocket: WebSocket, match_id: str):
    """The live chat connection for one match, one connected user per socket.

    Handshake sequence before any message can flow: (1) pull the JWT out of
    the offered subprotocols, (2) resolve it to a real user_id via
    auth-service, (3) confirm that user_id is a participant in this match_id
    via matcher-service. Any failure closes the connection with a custom
    code and returns — the message loop (added next) never even starts.
    """
    # uvicorn parses the raw Sec-WebSocket-Protocol header into this list for
    # us, split on commas, available even before accept().
    offered = websocket.scope.get("subprotocols", [])
    well_formed = len(offered) == 2 and offered[0] == "bearer"

    # Accept the handshake before we've even checked the token, rather than
    # close()-ing beforehand. This looks backwards but isn't: a WS close
    # *code* (our WS_AUTH_FAILED/WS_FORBIDDEN below) is only ever delivered
    # to the client if the handshake actually completed first — reject
    # before accept() and every client (browsers included) just sees a bare
    # "connection failed" with no distinguishable reason. Completing the
    # handshake first costs one extra round-trip for the failure case, in
    # exchange for the frontend actually being able to tell "bad token" from
    # "not your match" apart. Echoing "bearer" back is also what makes this a
    # spec-correct subprotocol negotiation when the offer was well-formed.
    await websocket.accept(subprotocol="bearer" if well_formed else None)

    if not well_formed:
        # Not our expected ["bearer", "<token>"] shape at all.
        await websocket.close(code=WS_AUTH_FAILED)
        return
    token = offered[1]

    user_id = await resolve_user_id(token)
    if not user_id:
        await websocket.close(code=WS_AUTH_FAILED)
        return

    match = await verify_match(match_id, user_id)
    if not match:
        await websocket.close(code=WS_FORBIDDEN)
        return
    # Whichever column isn't the caller is the other participant — same
    # ternary matcher_service's own /matches endpoint uses.
    other_user_id = match["user_b_id"] if match["user_a_id"] == user_id else match["user_a_id"]

    connections[user_id] = websocket

    # Tell session_service this user is online. Best-effort: presence
    # tracking is a nice-to-have (see session_service's own docstring for
    # why it's not load-bearing yet), so a failed call here shouldn't tear
    # down a chat connection that otherwise works fine.
    async with httpx.AsyncClient() as client:
        try:
            await client.post(f"{SESSION_SERVICE_URL}/session/connect", json={"user_id": user_id})
        except httpx.RequestError:
            pass

    try:
        # One iteration per message the browser sends. This loop is what
        # keeps the connection alive from the server's side — it only ends
        # when the client disconnects (caught below) or the process stops.
        while True:
            data = await websocket.receive_json()
            body = (data.get("body") or "").strip()
            if not body:
                continue  # ignore empty/whitespace-only sends rather than persisting blank rows

            message = Message(id=str(uuid.uuid4()), match_id=match_id, sender_id=user_id, body=body)
            db = SessionLocal()
            try:
                db.add(message)
                db.commit()
                db.refresh(message)  # pulls back the DB-assigned created_at so we can echo the real value
            finally:
                db.close()
            CHAT_MESSAGE_COUNT.inc()  # business metric: a message was actually persisted

            payload = {
                "id": message.id,
                "match_id": message.match_id,
                "sender_id": message.sender_id,
                "body": message.body,
                "created_at": message.created_at.isoformat(),
            }
            # Echo back to the sender too, not just the recipient: the UI
            # renders the server-persisted version (real id, real DB
            # timestamp) instead of trusting its own optimistic guess.
            await websocket.send_json(payload)
            recipient_ws = connections.get(other_user_id)
            if recipient_ws is not None:
                # Only push live if the other person's socket is registered
                # on *this* process right now — if they're not currently on
                # their Chat page for this match, the message still landed
                # in Postgres above; they'll see it via /chat/history on
                # their next visit, just not live.
                await recipient_ws.send_json(payload)
    except WebSocketDisconnect:
        # Normal end-of-life for a chat session (tab closed, navigated away,
        # network dropped) — not an error condition worth logging loudly.
        pass
    finally:
        # Runs on every exit path (clean disconnect or otherwise) so a
        # connection never lingers in either registry after its socket is
        # actually gone.
        connections.pop(user_id, None)
        async with httpx.AsyncClient() as client:
            try:
                await client.post(f"{SESSION_SERVICE_URL}/session/disconnect", json={"user_id": user_id})
            except httpx.RequestError:
                pass


@app.get("/chat/history/{match_id}")
async def get_history(match_id: str, x_user_id: str = Header(default=None)):
    """Return every persisted message for a match, oldest first.

    Unlike the WebSocket endpoint above, this route goes through the gateway
    normally — it's a plain HTTP GET, so nginx's auth_request protects it
    like /profile, /discover, etc., and x_user_id arrives as the trusted
    header. But auth_request only proves "this is some logged-in user," not
    "this user belongs to this match" — so this still calls verify_match,
    the same authorization check the WebSocket handshake uses, before
    returning anything. Without it, any authenticated user could read any
    match's history just by guessing a match_id in the URL.
    """
    if not x_user_id:
        raise HTTPException(status_code=401, detail="Missing X-User-Id from gateway")

    if not await verify_match(match_id, x_user_id):
        raise HTTPException(status_code=403, detail="Not a participant in this match")

    db = SessionLocal()
    try:
        messages = (
            db.query(Message)
            .filter(Message.match_id == match_id)
            .order_by(Message.created_at.asc())  # oldest first: a chat thread reads top-to-bottom
            .all()
        )
        return [
            {
                "id": m.id,
                "match_id": m.match_id,
                "sender_id": m.sender_id,
                "body": m.body,
                "created_at": m.created_at,
            }
            for m in messages
        ]
    finally:
        db.close()


@app.get("/health")
def health():
    """Liveness probe so compose/other tooling can tell the app is up."""
    return {"status": "ok"}
