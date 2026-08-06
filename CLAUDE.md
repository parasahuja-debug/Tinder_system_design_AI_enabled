# tinder — repo conventions

A Tinder-style microservice system, built locally service-by-service.
Backend: Python + FastAPI, one service per feature. Frontend: Angular.
Single shared Postgres instance (one DB, one table set per service, not one
DB per service). nginx (`gateway/`) is the only thing clients talk to.

Current state as of this file: `gateway/` has nginx config that already
assumes `auth-service:8002` and `profile-service:8001` exist — auth-service
does not exist yet. `profile_service/main.py` is an unauthenticated
FastAPI + SQLAlchemy skeleton with no `requirements.txt`/`Dockerfile` yet.
`direct_msg/` is empty. Nothing else described below has been built. Do not
assume any service is running or correct without actually starting it and
hitting it.

Full day-by-day build order and the reasoning behind every stack choice
lives in `.claude/plans/humming-bubbling-valley.md` — read that before
starting a new day's work.

## Services (target end state)

| Service | Owns | Talks to |
|---|---|---|
| `auth_service/` | user credentials, JWT issue/verify | called by nginx's `auth_request` before any protected route |
| `profile_service/` | profile fields (name/age/gender/city/lat/long/bio) | reads `X-User-Id` header set by the gateway after auth |
| `image_service/` | image upload, writes to `image_store/` on disk | profile_service (image_id ↔ profile_id) |
| `recommendation_service/` | candidate-feed query (bounding box + age/gender) | profile_service data |
| `matcher_service/` | swipes, match detection | recommendation_service candidates, feeds session/direct_msg |
| `session_service/` | user_id → active websocket map | direct_msg |
| `direct_msg/` | websocket chat, message persistence | session_service, matcher_service (must be matched to message) |
| `support_chatbot_service/` | RAG over `README.md` + conversation memory | Claude API (traced via LangSmith) |
| `frontend/` | Angular app, one page per feature | gateway only, never a backend service directly |
| `gateway/` | nginx: routing + auth gate | every backend service |
| `observability/` | Prometheus scrape config + Grafana dashboards | `/metrics` on every service |

## Coding standard

Every function gets a comment stating what it is and *why* it's there —
not a restatement of what the code already says. Non-obvious lines or
line-groups get inline comments too. This applies to every service and to
the Angular code. The point is debuggability: someone reading a function
cold should understand the reasoning, not just the mechanics.

## Auth model

nginx's `auth_request /auth/validate` gates protected routes. auth-service's
`/validate` endpoint verifies the JWT and returns the user id via an
`X-User-Id` response header; nginx captures it with `auth_request_set` and
forwards it to the upstream service as a request header. Downstream services
trust `X-User-Id` — they never re-verify the JWT themselves, since only the
gateway can reach them directly (they aren't exposed to clients).

## Verification discipline

Nothing is "done" on the strength of "the code looks right." Every slice
ends with an actual run — `docker compose up`, then a curl/browser check or
an assertion against Postgres. This applies to every service, not just
auth — don't presume a dependency exists or works until you've hit it.

## Documentation rule

README, code comments, this file, and commit messages all present design
reasoning as our own first-principles decisions. Don't attribute any design
choice to an external video/course/source — that context lives only in the
plan file, never in shipped docs or code.

## Dev tooling (Claude Code specific)

- `.mcp.json` — Postgres MCP server, for querying/inspecting the local `db`
  container directly instead of shelling out to `psql`.
- `.claude/skills/fastapi-endpoint/` — the convention for writing a new
  endpoint in any service here (comment shape, error handling, how to
  register the route in nginx).
- `.claude/commands/test.md` — `/test`, runs the right test command
  (pytest per backend service, `ng test` for frontend) based on where it's
  invoked.
- `.claude/settings.json` — post-edit hook that runs the relevant service's
  lint/tests automatically after an Edit/Write inside its directory.

Each service directory gets its own lean `CLAUDE.md` once it exists,
scoped to that service only (its purpose, how to run it standalone, its
tables) — this file stays repo-wide and high-level.
