"""
support_chatbot_service — RAG + memory support chatbot for the app.

Why this service exists: no other service in this repo calls a model at
runtime — this is the one place a runtime component (not Claude Code itself)
does, both to answer questions grounded in this repo's own README.md and to
run guarded live-data lookups through the project's Postgres MCP server.

This is the one service split across multiple files (config.py, models.py,
rag.py, mcp_tools.py, memory.py, chat.py) rather than a single main.py like
every other service here — a deliberate deviation, since this service does
meaningfully more than any other single service in this repo. main.py itself
is just the FastAPI app, the WebSocket endpoint, and orchestration — every
concern it touches is implemented elsewhere and imported. See CLAUDE.md
(this directory) for the endpoint-level docs and
.claude/plans/breezy-beaming-rivest.md for the design reasoning behind every
choice below.
"""

import asyncio  # to_thread — keeps mem0's blocking calls off the event loop
import logging
import uuid  # fresh session_id per WebSocket connection

import httpx  # resolves the WS token via auth-service, same as direct_msg
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

# INFO, not the logging module's WARNING default — chat.py's tool-call log
# line (the only way to externally confirm a live-data tool actually fired,
# vs. the model just producing a plausible-sounding answer with no lookup
# at all) would otherwise be silently dropped.
logging.basicConfig(level=logging.INFO)

from config import AUTH_SERVICE_URL
# models must import before memory: models.py is what runs `CREATE
# EXTENSION IF NOT EXISTS vector` at import time (a plain module-level side
# effect, like every service's Base.metadata.create_all()), and memory.py's
# Memory.from_config(...) — also a module-level call — needs that extension
# to already exist before it can create its own vector column. Discovered
# via a real ImportError/UndefinedObject on first run, not anticipated.
from models import SessionLocal, ChatbotMessage
from rag import embed_readme, retrieve_context
from mcp_tools import start_mcp_session, stop_mcp_session
from memory import save_session_memory, load_recent_memories
from chat import build_system_prompt, call_model

app = FastAPI()

# Runs once, synchronously, at import time — same as every other service's
# Base.metadata.create_all() (models.py does that too, as an import-time
# side effect of importing it above). README.md doesn't change while this
# process is running, so there's no reason for this to be an event handler.
embed_readme()


@app.on_event("startup")
async def on_startup() -> None:
    # First service in this repo needing an async startup hook: every other
    # service's setup (create_all, this file's own embed_readme() above) is
    # synchronous and runs fine at plain module-import time. Spawning +
    # initializing the MCP subprocess is inherently async, so it has to
    # happen inside a running event loop, which only exists once uvicorn
    # actually starts serving.
    await start_mcp_session()


@app.on_event("shutdown")
async def on_shutdown() -> None:
    await stop_mcp_session()


WS_AUTH_FAILED = 4401  # same custom close code direct_msg uses: bad/missing token
WS_BAD_HANDSHAKE = 4400  # new here: connected fine, but the required {"mode": ...} first message was missing/invalid


async def resolve_user_id(token: str) -> str | None:
    """Ask auth-service whether this token is valid, and if so, who it's
    for. Identical approach to direct_msg's resolve_user_id (see that
    module's docstring for the full reasoning on why this service doesn't
    decode the JWT itself) — duplicated here rather than shared, since these
    are two separate services/containers with no code-sharing mechanism in
    this repo.
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
    return resp.headers.get("x-user-id")


def _persist_message(session_id: str, user_id: str, role: str, message: str) -> None:
    """One row into chatbot_messages. Called for both the user's message and
    the model's reply, every turn — see ChatbotMessage's docstring (models.py)
    for what this table is actually for (it's never read back by the widget
    itself).
    """
    db = SessionLocal()
    try:
        db.add(ChatbotMessage(session_id=session_id, user_id=user_id, role=role, message=message))
        db.commit()
    finally:
        db.close()


@app.websocket("/support/ws")
async def support_chat(websocket: WebSocket) -> None:
    """The support-chat connection. Handshake sequence before any chat
    message can flow: (1) resolve the offered token to a real user_id, same
    subprotocol trick direct_msg uses, since auth_request can't gate a
    WebSocket and a browser can't set Authorization on one; (2) require the
    client's first JSON message to declare {"mode": "faq" | "companion"}
    (plan decision #3 — the frontend decides this from the current route,
    this service just trusts whichever it's told, since it isn't a security
    boundary).
    """
    offered = websocket.scope.get("subprotocols", [])
    well_formed = len(offered) == 2 and offered[0] == "bearer"

    # Accept before checking the token, not close()-before-accept — a close
    # *code* only reaches the client if the handshake completed first, same
    # reasoning direct_msg's docstring spells out for this exact pattern.
    await websocket.accept(subprotocol="bearer" if well_formed else None)

    if not well_formed:
        await websocket.close(code=WS_AUTH_FAILED)
        return
    token = offered[1]

    user_id = await resolve_user_id(token)
    if not user_id:
        await websocket.close(code=WS_AUTH_FAILED)
        return

    try:
        handshake = await websocket.receive_json()
    except WebSocketDisconnect:
        # Client disconnected while we were waiting for its handshake
        # message (e.g. a rapidly re-opened widget replacing a still-
        # connecting socket, or a tab closed mid-handshake) — the
        # connection is already gone, so there's nothing to close. Calling
        # close() here anyway raises a RuntimeError (ASGI protocol
        # violation: can't send after the connection already ended) —
        # found via a real crash in this exact race during Day 5
        # verification, not anticipated up front.
        return
    except Exception:
        await websocket.close(code=WS_BAD_HANDSHAKE)
        return

    mode = handshake.get("mode")
    if mode not in ("faq", "companion"):
        await websocket.close(code=WS_BAD_HANDSHAKE)
        return

    # Fresh per connection, never reused — this is what makes "close the
    # widget, reopen it" start a brand-new in-session context (plan
    # decision #7), independent of the long-term mem0 layer (decision #8).
    session_id = str(uuid.uuid4())

    # Loaded once, at connection time, not re-fetched per message — a
    # user's recent history doesn't change mid-conversation, so there's no
    # reason to hit mem0/Postgres again on every turn. This is the moment
    # the long-term layer actually surfaces: whatever get_all + the 7-day
    # prune (see memory.load_recent_memories's docstring) turns up gets
    # folded into the system prompt below, for the rest of this connection.
    #
    # asyncio.to_thread, not a plain call: load_recent_memories is a
    # synchronous function that does blocking I/O (psycopg2 queries, a
    # synchronous Ollama HTTP call via the `ollama` client) — called
    # directly, it would stall this process's single event loop for its
    # entire duration, delaying every *other* connection's WebSocket
    # handshake for however long it takes. Found via a real timeout on a
    # second connection while a prior session's mem0 save was still
    # running, not anticipated up front.
    recent_memories = await asyncio.to_thread(load_recent_memories, user_id)
    system_prompt = build_system_prompt(mode, recent_memories)

    # This connection's own turns only — plain {"role", "content"} dialogue,
    # never anything from a past session (plan decision #7). Tool-call
    # plumbing lives only in the throwaway `messages` list call_model
    # builds each turn, so it never pollutes this list or gets replayed
    # into future turns.
    conversation: list[dict] = []

    try:
        while True:
            data = await websocket.receive_json()
            question = (data.get("message") or "").strip()
            if not question:
                continue  # ignore empty/whitespace-only sends, same as direct_msg does for chat messages

            # Every call below that isn't already `await call_model(...)` is
            # a synchronous, blocking function (SQLAlchemy commits,
            # fastembed's CPU-bound embed()) — asyncio.to_thread for the
            # same reason as load_recent_memories/save_session_memory
            # above: called directly, each one would stall this process's
            # single event loop, delaying every other connection for
            # however long the DB write/embed takes, on *every* message
            # turn (more frequent than the once-per-connection memory
            # calls, so this matters even more in practice).
            await asyncio.to_thread(_persist_message, session_id, user_id, "user", question)
            conversation.append({"role": "user", "content": question})

            context_block = await asyncio.to_thread(retrieve_context, question)
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "system", "content": f"Relevant app documentation for this question:\n\n{context_block}"},
                *conversation,
            ]

            reply = await call_model(mode, user_id, messages)

            conversation.append({"role": "assistant", "content": reply})
            await asyncio.to_thread(_persist_message, session_id, user_id, "assistant", reply)

            await websocket.send_json({"reply": reply})
    except WebSocketDisconnect:
        # Normal end-of-life (widget closed, tab closed, navigated away) —
        # not an error condition, same as direct_msg's identical catch.
        pass
    finally:
        # This is the one and only place save_session_memory gets called —
        # a session's long-term memory is captured exactly once, when it
        # ends, from everything that was actually said in it (plan decision
        # #8). Skipped entirely if nothing was ever said (empty
        # conversation), so an accidental open-and-immediately-close never
        # writes a hollow memory.
        if conversation:
            # Same asyncio.to_thread reasoning as load_recent_memories
            # above — this is exactly the call whose blocking duration was
            # observed stalling a second user's connection attempt.
            await asyncio.to_thread(save_session_memory, user_id, conversation)


@app.get("/health")
def health():
    """Liveness probe so compose/other tooling can tell the app is up."""
    return {"status": "ok"}
