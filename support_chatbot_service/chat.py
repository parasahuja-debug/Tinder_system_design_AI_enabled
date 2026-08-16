"""
chat — the model client, system prompts, and the tool-call loop.

This is where LangSmith tracing actually lives: wrap_openai wraps the client
instance itself (one line, below), so every call made through `chat_client`
is traced automatically — there's no separate "langsmith module" to speak
of, since there's no meaningful amount of LangSmith-specific logic beyond
that one wrap.
"""

import json
import logging

from langsmith.wrappers import wrap_openai
from openai import AsyncOpenAI

from config import OLLAMA_HOST, CHAT_MODEL
from mcp_tools import TOOL_SCHEMAS, TOOL_FUNCTIONS

# One line per actual tool invocation — the only way to tell "the model
# answered from a live lookup" apart from "the model produced a plausible-
# sounding answer with no tool call at all" from the outside, since a small
# local model's reply text alone doesn't reliably signal which happened.
logger = logging.getLogger("support_chatbot.chat")

# AsyncOpenAI, not the sync client: this endpoint runs entirely under
# async/await (the WebSocket itself, the MCP calls in mcp_tools.py), and a
# sync HTTP call here would block the whole event loop for every other
# connection. The api_key is a dummy string — Ollama's OpenAI-compat layer
# doesn't check it, but the SDK requires a non-empty value to construct the
# client at all.
chat_client = wrap_openai(AsyncOpenAI(base_url=f"{OLLAMA_HOST}/v1", api_key="ollama"))


def build_system_prompt(mode: str, recent_memories: list[str]) -> str:
    """Compose the system prompt for one connection.

    Two modes (plan decision #3), not a permission gate — just which
    framing and which tools the model gets, decided by which page the
    widget was opened from:
      - faq: app-info only, grounded in the retrieved README context (added
        by main.py's WS endpoint), no live-data tools at all.
      - companion: faq's guardrails plus supportive framing and the two
        live-data tools in mcp_tools.py.
    Both modes get the same no-write-capability guardrail (plan decision
    #4) stated explicitly, as defense in depth on top of the fact that no
    write-capable tool is ever defined in TOOL_SCHEMAS in the first place.
    Both modes also get recent_memories folded in, if any exist — long-term
    continuity isn't a companion-only feature (see plan decision #8).
    """
    base = (
        "You are the support assistant for this dating app. Answer questions about "
        "the app using only the app-information context you're given — never invent "
        "app behavior that isn't in that context. You cannot edit, delete, update, or "
        "otherwise take any action on this user's account, profile, matches, or "
        "messages — you have no such capability at all. If asked to do something like "
        "that, say plainly that you can only provide information and support, and "
        "point them to the relevant page in the app. Keep answers concise and warm."
    )

    if mode == "companion":
        base += (
            " This user is currently on Discover, Matches, or Chat, so you may also "
            "offer warm, genuine, supportive encouragement about their dating/matching "
            "experience — not just answer factual questions. You have two tools, "
            "get_match_count and get_profile_summary, which return this user's own "
            "real data; call them when it would help personalize your reply (e.g. they "
            "ask how they're doing, or greeting them by name would help). Never "
            "fabricate a match count or profile detail — call the tool instead."
        )
    else:
        base += (
            " Personal, supportive conversation grounded in this user's own match/"
            "profile data becomes available once they're active on Discover, Matches, "
            "or Chat — if this user asks something needing that (e.g. their match "
            "count), say so plainly rather than guessing or fabricating an answer."
        )

    if recent_memories:
        base += (
            "\n\nBrief background from recent conversations with this user (let this "
            "inform your tone; don't quote it back verbatim):\n- " + "\n- ".join(recent_memories)
        )

    return base


async def call_model(mode: str, user_id: str, messages: list[dict]) -> str:
    """One full turn against the chat model, including the tool-call round
    trip when the model asks for a live-data lookup (companion mode only —
    `tools` is omitted entirely in faq mode, not just left unused, so
    there's nothing for the model to call regardless of what the prompt
    says).

    Capped at a small fixed number of rounds, not looped indefinitely: a
    well-behaved model calls a tool once or twice per turn at most, and the
    cap exists purely to stop a misbehaving model from hammering the MCP
    session forever on a single user message.
    """
    tools = TOOL_SCHEMAS if mode == "companion" else None
    for _ in range(3):  # at most 2 tool round trips, then a required final answer
        response = await chat_client.chat.completions.create(model=CHAT_MODEL, messages=messages, tools=tools)
        choice = response.choices[0].message

        if not choice.tool_calls:
            return choice.content or ""

        # The model asked for one or more tool calls. Every one of them
        # runs through TOOL_FUNCTIONS — our own dispatch table, never SQL
        # the model wrote itself (plan decision #5) — then the results feed
        # back into `messages` so the next loop iteration can use them.
        messages.append({
            "role": "assistant",
            "content": choice.content,
            "tool_calls": [tc.model_dump() for tc in choice.tool_calls],
        })
        for tool_call in choice.tool_calls:
            fn = TOOL_FUNCTIONS.get(tool_call.function.name)
            result = await fn(user_id) if fn else {"error": "unknown tool"}
            logger.info("tool_call name=%s user_id=%s result=%s", tool_call.function.name, user_id, result)
            messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": json.dumps(result)})

    return "Sorry, I'm having trouble answering that right now."
