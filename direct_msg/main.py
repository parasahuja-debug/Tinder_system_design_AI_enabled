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

import asyncio
import json
import os
import time
import uuid

import httpx
import redis.asyncio as redis
from fastapi import FastAPI, Header, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from sqlalchemy import Column, DateTime, String, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.sql import func
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

# --- Chat fan-out via Redis Pub/Sub (Phase 2 of the production-scale plan) --
# Why this is needed: `connections` below only ever holds sockets for users
# connected to THIS process. Once direct_msg runs as multiple replicas, a
# message for a user connected to a DIFFERENT replica can't be delivered by
# checking a local dict alone — see chat()'s connect/disconnect logic and
# the message-send code below for how subscribe/publish routes around that.
# `redis.asyncio`, not the plain sync `redis` client session_service uses:
# this service is already fully async (FastAPI async routes, WebSocket
# handler), so the Redis client needs to be awaitable the same way httpx's
# AsyncClient already is.
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)
pubsub = redis_client.pubsub()
# Holds the running redis_listener task once start_redis_listener (below)
# creates it — a real reference has to live somewhere, since asyncio's event
# loop only holds a WEAK reference to tasks (see start_redis_listener's
# docstring for why that matters).
_redis_listener_task = None

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


async def redis_listener():
    """Runs forever in the background — the other half of the fan-out
    mechanism described in the module-level Redis comment above. Publishing
    (in the message-send loop below) is one side; this is the side that
    turns a received broadcast into a real push down a real local socket.

    2026-08-20: uses get_message() in a poll loop, not pubsub.listen()
    directly (see commented-out prior version below) — discovered via
    testing that listen() internally loops `while self.subscribed`, and
    this task starts at app boot, before any user has connected and
    therefore before any subscribe() call has ever happened. That means
    listen() sees self.subscribed == False at that exact moment, its loop
    body never runs even once, and the generator finishes immediately —
    silently, no exception, no log — ending this task before it ever does
    anything. get_message() handles "nothing subscribed yet" gracefully
    instead, simply returning None and letting the loop keep polling; this
    is redis-py's own documented recommendation for a long-lived listener
    whose subscriptions change over time, rather than being fixed upfront.
    """
    # Kept the broken version for history per standing rule:
    # async for message in pubsub.listen():
    #     if message["type"] != "message":
    #         continue  # listen() also yields subscribe/unsubscribe confirmations, not just real messages
    #     user_id = message["channel"].split(":", 1)[1]  # channel is "chat:<user_id>"
    #     recipient_ws = connections.get(user_id)
    #     if recipient_ws is not None:
    #         await recipient_ws.send_json(json.loads(message["data"]))
    while True:
        try:
            # ignore_subscribe_messages=True: get_message() filters out
            # subscribe/unsubscribe confirmations for us, unlike listen()
            # where that filtering had to be done by hand above.
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
        except RuntimeError:
            # redis-py raises this specific error ("pubsub connection not
            # set") whenever nobody is currently subscribed to anything —
            # true at startup (this loop starts before any user has ever
            # connected) and true again any time the last subscriber just
            # disconnected. Not a real failure, just "nothing to read yet";
            # sleep briefly and keep polling rather than letting it crash
            # this task, which is exactly what happened before this fix —
            # silently, since asyncio only logs an unhandled task exception
            # at garbage-collection time, and this task is never collected
            # (see start_redis_listener's module-level task reference).
            await asyncio.sleep(1.0)
            continue
        if message is None:
            continue  # nothing arrived within the timeout — keep polling
        user_id = message["channel"].split(":", 1)[1]  # channel is "chat:<user_id>"
        recipient_ws = connections.get(user_id)
        if recipient_ws is not None:
            await recipient_ws.send_json(json.loads(message["data"]))


@app.on_event("startup")
async def start_redis_listener():
    """Launches redis_listener once the app's event loop actually exists.
    Why a startup hook and not import time (unlike matcher_consumer's
    thread): asyncio.create_task() requires a running event loop, which
    doesn't exist yet at module import — uvicorn creates it afterward.
    matcher_consumer didn't have this constraint because confluent-kafka's
    consumer is synchronous, so a plain OS thread (no event loop needed)
    could start immediately at import time instead.

    2026-08-20: assigns the task to a module-level variable, not a bare
    asyncio.create_task(...) expression (see commented-out prior version
    below) — discovered via testing that Python's event loop only holds a
    WEAK reference to a task. A task nobody else references can be garbage
    collected mid-run, even before it finishes — exactly what a bare,
    unreferenced create_task() call risks.
    """
    # Kept for history per standing rule:
    # asyncio.create_task(redis_listener())
    global _redis_listener_task
    _redis_listener_task = asyncio.create_task(redis_listener())


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

    # Subscribe THIS process to this user's channel — from now until
    # disconnect (below), any process that publishes to "chat:<user_id>"
    # (including this one, on a different user's send) reaches this
    # process's redis_listener, which delivers it down the socket just
    # registered above. See the module-level Redis comment for the full
    # mechanism.
    await pubsub.subscribe(f"chat:{user_id}")

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
            # 2026-08-20: replaced — this only ever delivered if the
            # recipient's socket happened to be registered on THIS process,
            # which silently missed them if they were connected to a
            # different direct_msg replica. Superseded by the Redis publish
            # below. Kept for history per standing rule:
            # recipient_ws = connections.get(other_user_id)
            # if recipient_ws is not None:
            #     # Only push live if the other person's socket is registered
            #     # on *this* process right now — if they're not currently on
            #     # their Chat page for this match, the message still landed
            #     # in Postgres above; they'll see it via /chat/history on
            #     # their next visit, just not live.
            #     await recipient_ws.send_json(payload)
            # Publish unconditionally — whichever process (this one or a
            # different replica) is actually holding other_user_id's socket
            # is subscribed to this channel and will deliver it via its own
            # redis_listener (see the module-level Redis comment). If nobody
            # is subscribed right now (recipient not currently connected
            # anywhere), this is a no-op broadcast with no listener — same
            # "they'll see it via /chat/history next visit, just not live"
            # fallback as before, still true since the message already
            # landed in Postgres above regardless.
            await redis_client.publish(f"chat:{other_user_id}", json.dumps(payload))
    except WebSocketDisconnect:
        # Normal end-of-life for a chat session (tab closed, navigated away,
        # network dropped) — not an error condition worth logging loudly.
        pass
    finally:
        # Runs on every exit path (clean disconnect or otherwise) so a
        # connection never lingers in either registry after its socket is
        # actually gone.
        connections.pop(user_id, None)
        # Mirrors the subscribe() at connect time above — this process no
        # longer holds this user's socket, so it shouldn't keep receiving
        # broadcasts meant for them.
        await pubsub.unsubscribe(f"chat:{user_id}")
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
