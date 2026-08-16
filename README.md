# tinder — a Tinder-style microservice system (local build)

A dating-app backend + frontend built feature-by-feature as small services, to
exercise a realistic microservice architecture end to end: auth, profiles,
images, discovery/recommendation, swiping/matching, real-time chat, a support
chatbot, and an observability stack. Backend is Python + FastAPI (one service
per feature); the frontend is Angular; a single shared Postgres backs
everything; nginx is the only entrypoint clients talk to.

This README grows one section per build day and reflects what is **actually
built and verified**, not what is merely planned. (Day-by-day execution notes
live in `NOTES.md`.)

## Architecture

```
                 browser
                    │
                    ▼
        ┌──────────────────────┐
        │  gateway (nginx)     │  :8080  ← the only thing clients talk to
        │  routing + auth gate │
        └──────────┬───────────┘
       auth_request│ (runs before every protected route)
        ┌──────────▼───────────┐
        │  auth_service :8002  │  issues/verifies JWT, owns users table
        └──────────────────────┘
                    │ X-User-Id forwarded to every protected upstream
    ┌───────────────┼────────────────┬─────────────────────┐
    ▼                ▼                ▼                     ▼
┌───────────┐  ┌───────────┐  ┌───────────────┐  ┌───────────────────┐
│profile_svc│  │ image_svc │  │ matcher_svc   │  │ recommendation_svc│
│  :8001    │  │  :8003    │  │  :8004        │  │  :8005             │
└─────┬─────┘  └─────┬─────┘  └───────┬───────┘  └──────────┬──────────┘
      └──────────────┴────────────────┴─────────────────────┘
                             │
              ┌──────────────▼──────────────┐
              │  Postgres (tinder DB) :5432  │  single shared DB, pgvector image
              └───────────────────────────────┘
```

Every backend service is sealed inside the private compose network — only the
gateway publishes a host port. That is what makes the trust model safe: a client
cannot reach a service directly to forge headers.

`recommendation_service` is the one deliberate exception to "each service only
touches its own tables": its `/discover` candidate feed reads `profiles`,
`swipes`, and `images` directly (read-only) instead of calling
profile_service/matcher_service/image_service over HTTP — a bounding-box +
age/gender + "not already swiped" query is a SQL `WHERE`/`NOT IN` problem, and
doing it in SQL lets Postgres use its indexes instead of pulling every row
across the network and filtering in application code. Documented here, not a
hidden shortcut — same reasoning category as the support chatbot's planned
MCP-based Postgres access (Day 5).

### Auth model
- `auth_service` is the only service that knows `JWT_SECRET`. It issues signed
  JWTs on register/login and verifies them at `GET /validate`.
- nginx gates every protected route with `auth_request /auth/validate`. On
  success, `/validate` returns the user id in an `X-User-Id` **response header**;
  nginx captures it (`auth_request_set`) and forwards it to the upstream
  (`proxy_set_header X-User-Id`).
- Downstream services **trust `X-User-Id`** and never re-verify the token — they
  aren't reachable except through the gateway, so only the gateway can set it.

**The one exception:** `direct_msg`'s chat WebSocket (`/chat/ws/{match_id}`).
`auth_request` doesn't compose with a WebSocket upgrade, and a browser can't
attach an `Authorization` header to a WS handshake at all. So the JWT rides as
the second entry of the WebSocket subprotocol list instead (`new
WebSocket(url, ['bearer', token])` → the `Sec-WebSocket-Protocol` header,
which nginx forwards through untouched), and `direct_msg` authenticates the
connection itself with a plain HTTP call to `auth_service`'s existing
`/validate` — still never learning `JWT_SECRET` itself. See
`direct_msg/main.py`'s module docstring for the full reasoning.

## Services

| Service | Port | Owns | Status |
|---|---|---|---|
| `gateway/` (nginx) | 8080 | routing + auth gate | ✅ Day 1 |
| `auth_service/` | 8002 | credentials, JWT issue/verify | ✅ Day 1 |
| `profile_service/` | 8001 | profile fields (own + by-id lookup) | ✅ Day 2, extended Day 3 |
| `image_service/` | 8003 | image upload to disk, own + by-id/by-user viewing | ✅ Day 2, extended Day 3 |
| `matcher_service/` | 8004 | swipes, match detection | ✅ Day 3 |
| `recommendation_service/` | 8005 | candidate feed (bounding-box + age/gender) | ✅ Day 3 |
| `session_service/` | 8006 | presence registry (user→online, in-memory) | ✅ Day 4 |
| `direct_msg/` | 8007 | websocket chat + message persistence | ✅ Day 4 |
| `support_chatbot_service/` | 8008 | RAG + memory + live DB via MCP | ✅ Day 5 |
| `observability/` | — | Prometheus + Grafana | ⏳ Day 6 |
| `frontend/` (Angular) | 4200 | one page per feature | ✅ Day 1–4 (auth, profile/images, discover/matches, chat), more to come |

## Running it

```bash
docker compose up -d --build      # db, auth, profile, image, matcher, recommendation, session, direct-msg, ollama, support-chatbot-service, gateway, pgweb
docker compose ps                 # all should be Up (db healthy)
```

Everything goes through the gateway at `http://localhost:8080`.

### Try the auth boundary (Day 1)
```bash
# unauthenticated protected route → 401
curl -i http://localhost:8080/profile

# register (returns a JWT, also logs you in)
curl -XPOST http://localhost:8080/auth/register \
  -H 'content-type: application/json' \
  -d '{"email":"a@b.c","password":"pw123"}'

# login → { "access_token": "...", "token_type": "bearer" }
TOKEN=$(curl -s -XPOST http://localhost:8080/auth/login \
  -H 'content-type: application/json' \
  -d '{"email":"a@b.c","password":"pw123"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

# authenticated, no profile yet → 404 (expected: profile_service does a
# real lookup, not an echo — this is the "create a profile first" state)
curl http://localhost:8080/profile -H "Authorization: Bearer $TOKEN"
```

### Try profile + images (Day 2)
```bash
# create a profile — lat/long feed Day 3's bounding-box search, gender/age
# feed its filters
curl -XPOST http://localhost:8080/profile -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"name":"Ada","age":28,"gender":"female","state":"Maharashtra","city":"Mumbai","lat":19.076,"long":72.8777,"bio":"hi"}'

# upload a photo (multipart, not JSON — image_service parses it as UploadFile)
curl -XPOST http://localhost:8080/images -H "Authorization: Bearer $TOKEN" \
  -F "file=@/path/to/photo.jpg;type=image/jpeg"

# list your own photos' metadata (ids + urls, never the bytes)
curl http://localhost:8080/images -H "Authorization: Bearer $TOKEN"

# fetch one photo's actual bytes — any logged-in user can view any photo by
# id (not just its owner), since a live profile's photos are meant to be
# visible to whoever's browsing candidates; only uploading stays owner-only
curl http://localhost:8080/images/<image_id> -H "Authorization: Bearer $TOKEN" -o photo.jpg
```

### Try discovery + matching (Day 3)
```bash
# candidate feed — bounding box around your own lat/long, excludes anyone
# you've already swiped on; min_age/max_age/gender are optional query params
curl http://localhost:8080/discover -H "Authorization: Bearer $TOKEN"

# swipe on a candidate — matched:true only once BOTH sides have liked
curl -XPOST http://localhost:8080/swipe -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"target_id":"<candidate-user-id>","direction":"like"}'

# list your matches (just ids — the frontend enriches each with a
# GET /profile/<id> + GET /images/user/<id> lookup to show name/photo)
curl http://localhost:8080/matches -H "Authorization: Bearer $TOKEN"
```

### Try messaging (Day 4)
```bash
# two users, mutual like -> match (same flow as Day 3)
TOKEN_A=... # register/login as above
TOKEN_B=...
curl -XPOST http://localhost:8080/swipe -H "Authorization: Bearer $TOKEN_A" \
  -H 'content-type: application/json' -d '{"target_id":"<B-user-id>","direction":"like"}'
curl -XPOST http://localhost:8080/swipe -H "Authorization: Bearer $TOKEN_B" \
  -H 'content-type: application/json' -d '{"target_id":"<A-user-id>","direction":"like"}'
MATCH_ID=$(curl -s http://localhost:8080/matches -H "Authorization: Bearer $TOKEN_A" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)[0]["match_id"])')

# message history (plain HTTP, normal auth_request-protected route)
curl http://localhost:8080/chat/history/$MATCH_ID -H "Authorization: Bearer $TOKEN_A"

# the live chat itself needs a WebSocket-capable client — curl can't do this
# part. wscat's -H flag doesn't set Sec-WebSocket-Protocol the way this
# service expects; use its -s/--subprotocol flag (or a browser, which is what
# the frontend actually does) to offer ['bearer', '<token>']:
wscat -c ws://localhost:8080/chat/ws/$MATCH_ID -s "bearer,$TOKEN_A"
# then type: {"body": "hello"}
```

### Try the support chatbot (Day 5)
The `ollama` service bind-mounts your host's own `~/.ollama` directory (see
`docker-compose.yml`), so if you already have these three models pulled
locally, there's nothing to do — the container sees them immediately, no
download. Two different models for two different jobs, not one for both
(see `support_chatbot_service/CLAUDE.md`'s Env section for why). If you
don't have them yet, one-time setup after the first `docker compose up`:
```bash
docker compose exec ollama ollama pull llama3.2
docker compose exec ollama ollama pull mistral:7b-instruct-v0.3-q4_K_M
docker compose exec ollama ollama pull nomic-embed-text
```

Same WS auth trick as `/chat/ws` (the JWT rides as the
`Sec-WebSocket-Protocol` subprotocol) — but the **first message** after
connecting must declare a mode, since support_chatbot_service has no
history endpoint to call first:
```bash
# faq mode — app-info only, grounded in README.md, no live-data tools
wscat -c ws://localhost:8080/support/ws -s "bearer,$TOKEN"
# then: {"mode": "faq"}
# then: {"message": "what is this app?"}
# try a live-data question here too — it should decline rather than guess:
# {"message": "how many matches do I have?"}

# companion mode — same as faq, plus supportive framing and two live-data
# tools (get_match_count, get_profile_summary)
wscat -c ws://localhost:8080/support/ws -s "bearer,$TOKEN"
# then: {"mode": "companion"}
# then: {"message": "how many matches do I have?"}
```
Closing the connection ends that session — reopening starts fresh, with no
raw transcript replayed. A summarized version persists via mem0 for 7 days
and gets folded into the next session's context, so a returning user gets
continuity of "how things have been going" without the bot ever quoting a
prior conversation back verbatim. See `support_chatbot_service/CLAUDE.md`
for the full architecture (both modes, the two-layer memory, the
MCP-guarded live-data tools, why Ollama instead of Claude here).

### Inspecting the database
- **Browser (Studio-like):** pgweb at `http://localhost:8081` (auto-connected to
  the `tinder` DB).
- **Desktop client** (pgAdmin/DBeaver/TablePlus): host `localhost`, port `5432`,
  database `tinder`, user/password `postgres`/`postgres`.

## Data store
One shared Postgres (`pgvector/pgvector:pg16` image, chosen up front because the
Day-5 chatbot stores embeddings via the `pgvector` extension). Each service owns
its own tables in the single `tinder` database and creates them on startup — no
migration tool this build week (Alembic is backlog). `support_chatbot_service`
owns `doc_chunks`/`chatbot_messages` directly (SQLAlchemy, same as every other
service) and, additionally, mem0's own internal tables — created and managed by
the `mem0` library itself via its `pgvector` vector-store adapter, never
modeled by us — same single Postgres instance, just a library-owned table set
instead of a hand-rolled one.

## Local model
`support_chatbot_service` runs on local models (Ollama: `llama3.2` for
chat/tool-calling, `mistral:7b-instruct` for mem0's own memory-extraction
step, `nomic-embed-text` for mem0's embeddings) rather than the Claude API —
a high-frequency, low-stakes workload like a support/FAQ chat doesn't need
to spend Claude tokens. LangSmith still traces every chat call
(`wrap_openai`, since Ollama exposes an OpenAI-compatible endpoint) — going
local swaps which client gets wrapped, not whether tracing happens at all.

## Repo conventions
See `CLAUDE.md` (repo-wide) and each service's own `CLAUDE.md`. Dev tooling lives
under `.claude/`: a Postgres MCP server for DB inspection (`.mcp.json`), a
post-edit syntax hook, a `/test` command, a `fastapi-endpoint` skill (how every
backend route in this repo is written/wired), and a `run-tinder` skill (launches
the Angular dev server and drives it headlessly via Playwright — screenshots,
form fills, login flows — for verifying frontend changes without a human at a
browser).
