"""
mcp_tools — the one path to guarded live-data lookups.

Spawns the project's Postgres MCP server (same package .mcp.json already
uses for Claude Code, just now also a runtime dependency of this service)
and exposes exactly two named, backend-defined, parameterized queries as
tools the chat model can call — never a generic passthrough SQL tool (plan
decision #5). See main.py for where start_mcp_session/stop_mcp_session get
wired into FastAPI's startup/shutdown, since that wiring needs the `app`
object, which lives there.
"""

import json
import re
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from config import MCP_POSTGRES_URL

# Set once by start_mcp_session() at app startup, read by every tool call
# below. Module-level rather than app.state purely because these calls
# happen from deep inside the model's tool-call loop (chat.py), not from a
# request handler with easy access to the FastAPI app object.
_mcp_exit_stack: AsyncExitStack | None = None
_mcp_session: ClientSession | None = None


async def start_mcp_session() -> None:
    """Spawn the project's Postgres MCP server and open one long-lived
    session against it, kept alive for this process's lifetime (plan
    decision #6) rather than reconnecting per request.
    """
    global _mcp_exit_stack, _mcp_session
    _mcp_exit_stack = AsyncExitStack()
    server_params = StdioServerParameters(
        command="npx",
        args=["-y", "@modelcontextprotocol/server-postgres", MCP_POSTGRES_URL],
    )
    read, write = await _mcp_exit_stack.enter_async_context(stdio_client(server_params))
    _mcp_session = await _mcp_exit_stack.enter_async_context(ClientSession(read, write))
    await _mcp_session.initialize()


async def stop_mcp_session() -> None:
    """Close the subprocess + session on shutdown — the spawned `npx`
    process holds its own Postgres connection independent of this service's
    SQLAlchemy engine, so without this a container restart would leak
    orphaned node processes and stale DB connections.
    """
    if _mcp_exit_stack is not None:
        await _mcp_exit_stack.aclose()


# auth_service only ever issues uuid4 ids (see auth_service/main.py) — used
# below to validate a user_id is shaped like a real one before it's ever
# allowed into a SQL string.
_USER_ID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


def _validate_user_id(user_id: str) -> str:
    """Refuse to build a query with anything that isn't UUID-shaped.

    Why validate instead of parameter-binding: the MCP Postgres server's
    `query` tool takes one plain SQL string, no separate bind-params API —
    so the injection guard has to live on our side, before the string is
    ever built (plan decision #5). This is the one place user_id touches
    SQL text in this service.
    """
    if not _USER_ID_PATTERN.match(user_id):
        raise ValueError(f"user_id {user_id!r} is not a valid UUID — refusing to build a query with it")
    return user_id


async def _run_readonly_query(sql: str) -> list[dict]:
    """Execute one fixed SQL statement through the MCP Postgres server's own
    `query` tool, and return the rows as plain dicts.

    This is the only function in this service that talks to `_mcp_session`
    — every named tool below builds its SQL here and calls through this one
    chokepoint. None of them ever accept SQL from the model itself; the
    model only ever calls a named tool by name (plan decision #5).
    """
    result = await _mcp_session.call_tool("query", {"sql": sql})
    return json.loads(result.content[0].text)


async def get_match_count(user_id: str) -> dict:
    """How many matches this user has, total.

    The model calls this by name, with no arguments of its own — main.py's
    WS endpoint always supplies user_id from the connection's own trusted
    X-User-Id, never from anything in the chat message. Exists for
    companion mode specifically: "why haven't I matched with anyone" or
    "how am I doing" deserves a reply grounded in the real number, not the
    model guessing.
    """
    uid = _validate_user_id(user_id)
    rows = await _run_readonly_query(
        f"SELECT COUNT(*) AS match_count FROM matches WHERE user_a_id = '{uid}' OR user_b_id = '{uid}'"
    )
    return {"match_count": rows[0]["match_count"] if rows else 0}


async def get_profile_summary(user_id: str) -> dict:
    """This user's own name/age/city.

    Same no-argument, server-supplied-user_id shape as get_match_count
    above. Exists so a companion-mode reply can open with "hi Ada" instead
    of addressing the user generically. Deliberately narrow — no bio, no
    lat/long — this is a personalization detail, not a reason to hand the
    model the user's full profile.
    """
    uid = _validate_user_id(user_id)
    rows = await _run_readonly_query(f"SELECT name, age, city FROM profiles WHERE id = '{uid}'")
    return rows[0] if rows else {"error": "no profile yet"}


# OpenAI-style tool schema, no parameters on either tool: the model only
# ever decides *whether* and *which* tool to call — user_id is always
# supplied by main.py's WS endpoint from the connection's own trusted
# identity, never accepted as a tool argument from the model (plan decision
# #5). Dispatch table maps a tool-call's name straight to the async
# function that actually runs it.
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_match_count",
            "description": "Get the current user's total match count on this dating app.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_profile_summary",
            "description": "Get the current user's own name, age, and city from their profile.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]
TOOL_FUNCTIONS = {"get_match_count": get_match_count, "get_profile_summary": get_profile_summary}
