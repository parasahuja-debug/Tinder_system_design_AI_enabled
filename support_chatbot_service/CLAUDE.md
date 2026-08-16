# support_chatbot_service

RAG + memory support chatbot. Answers questions grounded in this repo's own
`README.md`, optionally offers supportive conversation grounded in the
caller's real match/profile data, and remembers a summarized version of past
sessions for up to a week. The one service in this repo that calls a model
at runtime — see main.py's module docstring and
`.claude/plans/breezy-beaming-rivest.md` for the design reasoning behind
every choice below.

## File layout
The one service here split across multiple files instead of a single
`main.py` — deliberate, since this service does meaningfully more than any
other single service in this repo:
`config.py` (env surface) → `models.py` (DB tables) → `rag.py` (README
chunking/embedding/retrieval) → `mcp_tools.py` (MCP session + the two named
live-data tools) → `memory.py` (mem0) → `chat.py` (Ollama client, prompts,
tool-call loop) → `main.py` (FastAPI app + the `/support/ws` endpoint only,
importing everything else).

## Endpoints
- `WS /support/ws` — the chat connection. Client must offer the JWT via the
  WebSocket subprotocol list (`new WebSocket(url, ['bearer', <token>])`),
  same trick `direct_msg` uses. Closes with code `4401` on bad/missing
  token. Once connected, the client's **first** JSON message must be
  `{"mode": "faq"}` or `{"mode": "companion"}` — anything else closes with
  `4400`. After that, send `{"message": "..."}`, receive `{"reply": "..."}`.
  Closing the socket ends that session; reopening starts a brand-new one —
  no history is replayed, only a mem0-summarized version of recent sessions
  (see Memory below).
- `GET /health` → `{status: ok}`

## Modes
Not a backend permission gate — just which system prompt and which tools
get used, decided entirely by which page the widget was opened from (the
frontend sends whichever mode; this service trusts it, since nothing
sensitive becomes reachable in companion mode that faq mode's user couldn't
already see elsewhere in the app):
- **faq**: app-info Q&A grounded in retrieved `README.md` chunks. No
  live-data tools at all — `tools` is omitted from the model call entirely,
  not just left unused.
- **companion**: faq's guardrails plus supportive framing, and the two
  live-data tools (`get_match_count`, `get_profile_summary`) below.

Both modes share one guardrail, stated in the system prompt and backed
architecturally: this service never defines a write-capable tool, in either
mode. There is no code path from a chat message to a database write
anywhere in this file.

## Tables (in shared DB)
- `doc_chunks(id, source, chunk_text, embedding vector(384))` — the RAG
  corpus. Cleared and re-embedded from `README.md` on every startup.
- `chatbot_messages(id, session_id, user_id, role, message, created_at)` —
  one row per message sent during a still-open WS connection. Write-only
  from the widget's perspective; exists for our own audit trail and as the
  transcript handed to mem0 when a session ends.
- mem0 also owns its own internal tables in this same database (via its
  pgvector vector-store adapter) — not modeled here, only ever touched
  through mem0's own Python API (`memory.add`/`get_all`/`delete`).

## Memory (two layers — see main.py for the full reasoning)
- **In-session**: plain Python list, scoped to one WS connection. Gone the
  moment the socket closes.
- **Long-term (mem0)**: on disconnect, the session's transcript is
  summarized into mem0, keyed by `user_id`. On connect, this user's mem0
  memories from the last 7 days are loaded and folded into the system
  prompt; anything older is pruned at that same moment (lazy retention, no
  scheduler).

## Talks to (service-to-service, not through the gateway)
- `auth-service` `GET /validate` — resolves a WS connection's token to a
  real user_id, same pattern as `direct_msg`.
- The project's **Postgres MCP server** (`npx -y
  @modelcontextprotocol/server-postgres`, spawned as a stdio subprocess at
  startup and kept open for this process's life) — the only path to the two
  named live-data tools. Every query it runs is fixed, parameterized SQL
  built by this service, never SQL the model wrote itself.
- **Ollama** (`OLLAMA_HOST`) — both the chat model (via its
  OpenAI-compatible endpoint, `openai` SDK wrapped with LangSmith's
  `wrap_openai`) and mem0's own LLM/embedder (via its native API).
- **LangSmith** (hosted, external) — tracing only, via `wrap_openai`. Traces
  include prompt/context/response/tool-calls; nothing else about this
  service depends on it being reachable.

## Env
`DATABASE_URL` (required). `README_PATH` (default `/app/README.md`, bind-
mounted from the repo root). `MCP_POSTGRES_URL` (default = `DATABASE_URL`).
`AUTH_SERVICE_URL` (default `http://auth-service:8002`). `OLLAMA_HOST`
(default `http://ollama:11434`). `LANGSMITH_API_KEY` (from `.env`, required
for tracing to actually send anywhere — the `langsmith` package reads
`LANGSMITH_API_KEY`/`LANGSMITH_TRACING`/`LANGSMITH_PROJECT` from the
environment itself, not from anything in this file).

Three model names, all set from `.env` (not hardcoded — see
`docker-compose.yml`), two different models for two different jobs:
`CHAT_MODEL` (default `llama3.2`) is the main chat model, needs to be fast
since every `/support/ws` turn goes through it. `MEM0_LLM_MODEL` (default
`mistral:7b-instruct-v0.3-q4_K_M`) is mem0's own extraction model,
deliberately *not* the same as `CHAT_MODEL` — found during Day 5
verification that `llama3.2`'s structured-JSON output for mem0's internal
prompt unreliably omitted a required field, causing mem0 to silently fail
to save anything (caught and logged by mem0 itself, not a crash — easy to
miss without checking deliberately). `mistral:7b-instruct` handles the same
prompt reliably, and since this call only happens once per closed session
(not per message), the extra size/latency is a fine tradeoff.
`MEM0_EMBED_MODEL` (default `nomic-embed-text`) is mem0's embedder, used
only for storing/retrieving memory vectors — unrelated to `rag.py`'s
`fastembed` embedder, which only ever embeds README chunks.

## Run standalone
```
pip install -r requirements.txt
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/tinder \
README_PATH=../README.md \
uvicorn main:app --port 8008
```
Needs, reachable: Postgres with the `vector` extension available (the
`pgvector/pgvector:pg16` image, per Day 1); `auth-service` at its default
URL (or override via env); Ollama at `OLLAMA_HOST` with all three models
already pulled (`ollama pull llama3.2 && ollama pull
mistral:7b-instruct-v0.3-q4_K_M && ollama pull nomic-embed-text`) — this
service does not pull models itself; Node.js on `PATH` (for the
`npx`-spawned MCP server — already satisfied inside the container via the
Dockerfile, needs installing separately for a bare standalone run).
