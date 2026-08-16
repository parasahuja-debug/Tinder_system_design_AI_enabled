"""
memory — mem0-backed long-term memory, independent of rag.py's embedder.

mem0 needs its own LLM (to extract/summarize a closed session) and its own
embedder (to store/retrieve those memories semantically) — both point at the
same local Ollama server the chat itself uses (plan decisions #8/#9), but
this is a separate config from rag.py's fastembed: RAG-over-README and
long-term-memory are unrelated concerns that just happen to each need *an*
embedding model. mem0 persists into this same Postgres via its pgvector
vector-store adapter — its own internal tables, never ours to define, same
relationship every other service already has to this shared DB.

mem0's LLM is MEM0_LLM_MODEL, deliberately not the same model chat.py uses
for the main conversation (CHAT_MODEL) — see config.py's comment on
MEM0_LLM_MODEL for why: found during Day 5 verification that the smaller
chat model's structured-JSON output wasn't reliable enough for mem0's own
internal extraction prompt.
"""

from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from mem0 import Memory

from config import DATABASE_URL, OLLAMA_HOST, MEM0_LLM_MODEL, MEM0_EMBED_MODEL

MEM0_EMBED_DIMS = 768  # nomic-embed-text's output size; must match what the pgvector config below declares
MEMORY_RETENTION_DAYS = 7  # plan decision #8: memories older than this are pruned, not kept indefinitely


def _parse_db_url(url: str) -> dict:
    """Break DATABASE_URL into the pieces mem0's pgvector config wants
    individually, rather than hardcoding a second copy of host/user/
    password/dbname — one source of truth for how to reach this database,
    same as every other service's single DATABASE_URL env var.
    """
    parsed = urlparse(url)
    return {
        "host": parsed.hostname,
        "port": parsed.port,
        "user": parsed.username,
        "password": parsed.password,
        "dbname": parsed.path.lstrip("/"),
    }


# NOTE: mem0's exact config key names (llm/embedder provider config shapes,
# pgvector field names) are written here from best current knowledge of
# mem0's API, not verified against the actually-installed mem0ai==0.1.34 —
# the plan flagged this explicitly as something to pin during the
# verification pass (docker compose up + a real mem0.add/get_all call),
# since guessing risks silent drift from whatever the installed version
# expects.
memory = Memory.from_config({
    "llm": {
        "provider": "ollama",
        "config": {"model": MEM0_LLM_MODEL, "ollama_base_url": OLLAMA_HOST},
    },
    "embedder": {
        "provider": "ollama",
        "config": {"model": MEM0_EMBED_MODEL, "ollama_base_url": OLLAMA_HOST},
    },
    "vector_store": {
        "provider": "pgvector",
        "config": {**_parse_db_url(DATABASE_URL), "embedding_model_dims": MEM0_EMBED_DIMS},
    },
})


def save_session_memory(user_id: str, transcript: list[dict]) -> None:
    """Summarize a just-ended chat session into mem0, keyed by user_id.

    Called once, from main.py's WS endpoint, when a connection closes —
    transcript is that session's messages as [{"role": "user"|"assistant",
    "content": ...}, ...]. mem0 runs its own extraction internally, via the
    Ollama LLM configured above, rather than this service writing its own
    summarization prompt — using mem0 instead of hand-rolling this step is
    the whole point of plan decision #8.
    """
    memory.add(transcript, user_id=user_id)


def load_recent_memories(user_id: str) -> list[str]:
    """This user's mem0 memories from the last 7 days, as plain text —
    injected into the system prompt (chat.py's build_system_prompt) so a
    returning user gets continuity of "how things have been going" without
    the raw prior transcript ever being replayed. This is the long-term
    layer; it's distinct from the in-session transcript in
    models.ChatbotMessage, which never survives past its own connection
    (plan decision #7 vs #8).

    Retention is enforced lazily, right here, rather than via a scheduler:
    anything older than MEMORY_RETENTION_DAYS is deleted before the
    remaining memories are returned — same "don't build a background job
    you don't need yet" call this repo already made for session_service's
    in-memory map and doc_chunks' startup re-embed.
    """
    all_memories = memory.get_all(user_id=user_id)
    # mem0's get_all has returned either a plain list or {"results": [...]}
    # across versions — handle both rather than assuming one, since this
    # exact shape is one of the things flagged for a real check against the
    # installed version during verification.
    records = all_memories.get("results", all_memories) if isinstance(all_memories, dict) else all_memories

    cutoff = datetime.now(timezone.utc) - timedelta(days=MEMORY_RETENTION_DAYS)
    keep, stale = [], []
    for record in records:
        created_at = datetime.fromisoformat(record["created_at"])
        (stale if created_at < cutoff else keep).append(record)

    for record in stale:
        memory.delete(memory_id=record["id"])

    return [record["memory"] for record in keep]
