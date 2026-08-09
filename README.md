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
                    │ X-User-Id forwarded to upstreams
        ┌──────────▼───────────┐
        │ profile_service :8001│  trusts X-User-Id, owns profiles table
        └──────────┬───────────┘
                   ▼
        ┌──────────────────────┐
        │  Postgres (tinder DB)│  :5432  single shared DB, pgvector image
        └──────────────────────┘
```

Every backend service is sealed inside the private compose network — only the
gateway publishes a host port. That is what makes the trust model safe: a client
cannot reach a service directly to forge headers.

### Auth model
- `auth_service` is the only service that knows `JWT_SECRET`. It issues signed
  JWTs on register/login and verifies them at `GET /validate`.
- nginx gates every protected route with `auth_request /auth/validate`. On
  success, `/validate` returns the user id in an `X-User-Id` **response header**;
  nginx captures it (`auth_request_set`) and forwards it to the upstream
  (`proxy_set_header X-User-Id`).
- Downstream services **trust `X-User-Id`** and never re-verify the token — they
  aren't reachable except through the gateway, so only the gateway can set it.

## Services

| Service | Port | Owns | Status |
|---|---|---|---|
| `gateway/` (nginx) | 8080 | routing + auth gate | ✅ Day 1 |
| `auth_service/` | 8002 | credentials, JWT issue/verify | ✅ Day 1 |
| `profile_service/` | 8001 | profile fields | 🚧 stub + verify endpoint (full on Day 2) |
| `image_service/` | — | image upload to disk | ⏳ Day 2 |
| `recommendation_service/` | — | candidate feed | ⏳ Day 3 |
| `matcher_service/` | — | swipes, match detection | ⏳ Day 3 |
| `session_service/` | — | user→websocket map | ⏳ Day 4 |
| `direct_msg/` | — | websocket chat + persistence | ⏳ Day 4 |
| `support_chatbot_service/` | — | RAG + memory + live DB via MCP | ⏳ Day 5 |
| `observability/` | — | Prometheus + Grafana | ⏳ Day 6 |
| `frontend/` (Angular) | 4200 | one page per feature | ⏳ Day 1 (in progress) |

## Running it

```bash
docker compose up -d --build      # db, auth, profile, gateway, pgweb
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

# authenticated → 200, and profile_service echoes the user id it received
curl http://localhost:8080/profile -H "Authorization: Bearer $TOKEN"
```

### Inspecting the database
- **Browser (Studio-like):** pgweb at `http://localhost:8081` (auto-connected to
  the `tinder` DB).
- **Desktop client** (pgAdmin/DBeaver/TablePlus): host `localhost`, port `5432`,
  database `tinder`, user/password `postgres`/`postgres`.

## Data store
One shared Postgres (`pgvector/pgvector:pg16` image, chosen up front because the
Day-5 chatbot stores embeddings via the `pgvector` extension). Each service owns
its own tables in the single `tinder` database and creates them on startup — no
migration tool this build week (Alembic is backlog).

## Repo conventions
See `CLAUDE.md` (repo-wide) and each service's own `CLAUDE.md`. Dev tooling lives
under `.claude/`: a Postgres MCP server for DB inspection (`.mcp.json`), a
post-edit syntax hook, a `/test` command, and a `fastapi-endpoint` skill.
