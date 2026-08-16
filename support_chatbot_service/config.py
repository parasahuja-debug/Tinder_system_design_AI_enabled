"""
config — every environment-derived value this service reads, in one place.

Why a dedicated file rather than each module reading os.environ directly
(every other service in this repo just does `os.environ["DATABASE_URL"]`
inline): this is the one service split across multiple files, so without a
single source of truth, the same env var could easily end up read (and
defaulted) slightly differently in two places. Fixed policy constants that
aren't env-derived (EMBEDDING_DIM, RETRIEVAL_TOP_K, MEMORY_RETENTION_DAYS,
...) deliberately live next to the code that uses them instead of here —
this file is strictly "what comes from the environment."
"""

import os

DATABASE_URL = os.environ["DATABASE_URL"]

# Bind-mounted from the repo root (see docker-compose.yml), same pattern as
# image_service's image_store mount — the container always reads whatever
# README.md currently says, no rebuild needed to pick up doc edits.
README_PATH = os.environ.get("README_PATH", "/app/README.md")

# Reuses this service's own DATABASE_URL as the connection string for the
# Postgres MCP server by default — no separate value needed since it's the
# same DB, same credentials, this service already talks to via SQLAlchemy.
MCP_POSTGRES_URL = os.environ.get("MCP_POSTGRES_URL", DATABASE_URL)

AUTH_SERVICE_URL = os.environ.get("AUTH_SERVICE_URL", "http://auth-service:8002")

# Bare Ollama API, no /v1 — mem0 talks to Ollama natively; chat.py appends
# /v1 itself for the OpenAI-compatible path the chat client uses instead.
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://ollama:11434")

# All three model names below are also set explicitly in docker-compose.yml
# (sourced from the root .env) — the os.environ.get() defaults here are a
# fallback for a bare standalone run, not the primary way to change them.
# Retuning which model does what is a one-line .env edit + container
# restart, no code change or rebuild needed.

# The main chat model — every /support/ws turn goes through this, so it
# needs to be fast. llama3.2, not the originally-planned llama3.1:8b: same
# well-documented Ollama tool-calling support, smaller (2GB vs 4.7GB), and
# — the actual deciding factor, found during Day 5 verification — one of
# the models already sitting on this machine's host Ollama installation,
# which the `ollama` compose service now bind-mounts directly (see
# docker-compose.yml) instead of downloading a fresh model from inside the
# container.
CHAT_MODEL = os.environ.get("CHAT_MODEL", "llama3.2")

# mem0's LLM, deliberately NOT the same as CHAT_MODEL — separate model for
# a separate job. mem0 asks its LLM to return structured JSON (a list of
# memory actions, each needing an "event" field); llama3.2 unreliably
# omitted that field, causing mem0 to silently fail to save anything (found
# during Day 5 verification — the failure was caught and logged by mem0
# itself, not a crash, which is exactly why it went unnoticed until this
# was checked deliberately). mistral:7b-instruct handles the same prompt
# reliably. This call only happens once per closed session, not per
# message, so the extra size/latency is a fine tradeoff for a model that
# actually gets the structured output right.
MEM0_LLM_MODEL = os.environ.get("MEM0_LLM_MODEL", "mistral:7b-instruct-v0.3-q4_K_M")

# Ollama's small dedicated embedding model, used only by mem0 — separate
# from fastembed (rag.py), which only ever embeds README chunks.
MEM0_EMBED_MODEL = os.environ.get("MEM0_EMBED_MODEL", "nomic-embed-text")
