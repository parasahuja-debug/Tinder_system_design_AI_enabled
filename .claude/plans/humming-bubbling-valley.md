# Tinder System Design — Local Build Plan

## Context

This repo is a hands-on build of a Tinder-style microservice architecture,
reasoning from user-facing features into services rather than from an ER
diagram forward: store profiles + images, note matches, direct messaging,
recommend matches — plus, on top of the core product, a support chatbot,
observability stack, and Claude Code dev-tooling (MCP, skills, hooks, a
test slash command) so the repo also demonstrates a well-instrumented
Claude-Code-driven build, not just a working app.

So far only scaffolding exists: `gateway/` has an nginx config that already
assumes `profile-service:8001` and `auth-service:8002` exist (auth-service
does not exist yet — nothing is assumed to work until it's actually run and
hit with a real request); `profile_service/main.py` is an unauthenticated
FastAPI + SQLAlchemy skeleton; `direct_msg/` is empty; there is no image
service, matcher, session service, recommendation service, chatbot,
observability stack, or frontend.

**Documentation rule for every shipped artifact** (README, code comments,
`CLAUDE.md` files, commit messages): all design reasoning is written as our
own first-principles decisions. Nothing shipped references a video, course,
or other external source as the origin of an idea — this plan file is the
only place that context lives.

## Decisions locked in from discussion

- **Backend**: Python + FastAPI for every service.
- **Frontend**: Angular, built incrementally per feature/day.
- **Images**: plain local disk, `image_store/` at project root, path saved
  in Postgres.
- **Chat transport**: WebSockets in FastAPI.
- **Recommendation engine**: one Postgres table, bounding-box/radius query on
  lat/long + age + gender filters (not real sharding — that's backlog).
- **Auth**: real, minimal auth-service, verified end-to-end (401 → register
  → login → 200), not stubbed.
<!-- 2026-08-09: replaced — the stock `postgres` image has no pgvector, which
     Day 5 depends on (`CREATE EXTENSION vector` would fail). Old line kept
     below for history per standing rule.
- **Data store**: one shared local Postgres (plain `postgres` image, not the
  full Supabase stack). `Supabase_README.md` stays as background notes only.
-->
- **Data store**: one shared local Postgres, still not the full Supabase
  stack — but use the `pgvector/pgvector:pg16` image rather than stock
  `postgres`, because Day 5's chatbot stores embeddings via the `pgvector`
  extension and the stock image can't `CREATE EXTENSION vector`. Same single
  container otherwise; pick this image on Day 1 so it isn't a late swap.
  `Supabase_README.md` stays as background notes only.
- **Schema ownership**: each service owns its own tables in the shared DB and
  creates them itself via `Base.metadata.create_all()` on startup — no
  migration tool this week. Acceptable for a build week (like the in-memory
  session map); a real migration story (Alembic) is backlog.
- **Coding standard**: every function commented with what it is and why it's
  there; non-obvious lines/line-groups get inline comments too. Applies to
  every service and the Angular code.
- **Verification discipline**: nothing is "done" on the strength of "the code
  looks right" — every slice ends with an actual run (`docker compose up`,
  curl/browser check, or an assertion against Postgres).
- **Support chatbot**: RAG over our own README/docs (no external knowledge),
  with persisted conversation memory per user/session so follow-up questions
  keep context.
  <!-- 2026-08-09: replaced — decided to bring live-DB access into Day 5 scope
       via MCP (the chatbot's LLM calls the Postgres MCP server as a tool), so
       the chatbot is no longer docs-only. Old clause kept for history:
  Answers questions about how to use the app, not live account
  data (querying live account state is a backlog idea, not this week).
  -->
  Beyond docs, the chatbot's LLM can also answer questions grounded in live
  account/DB data by calling the Postgres MCP server as a tool (see Day 5) —
  so it does both RAG-over-docs and guarded live queries.
- **Observability**: a real metrics stack — Prometheus + Grafana — for
  system/business metrics (logins, chat volume, DB size). LangSmith
  separately traces the chatbot's LLM calls (via `wrap_anthropic`), which is
  a different concern from Prometheus/Grafana and should not be conflated.
- **Precision/recall eval for the chatbot**: explicitly deferred — discussed
  and scoped as its own mini-plan at the end of the day the chatbot is built
  (Day 5), not implemented this week. No golden set exists yet; it gets
  constructed later as an independent piece of work.
- **MCP**: a Postgres MCP server added to the project (`.mcp.json`) so Claude
  Code itself can query/inspect the local DB directly while building and
  debugging, instead of shelling out to `psql` ad hoc.
  <!-- 2026-08-09: replaced — promoted the chatbot's live-DB-via-MCP use from
       backlog into Day-5 core scope. Old parenthetical kept for history:
  (Exposing that same server as a live tool inside the chatbot's own reasoning
  loop is a backlog idea, not core scope, given the chatbot is RAG+memory only
  for now.)
  -->
  On Day 5 this same Postgres MCP server is additionally exposed as a live tool
  inside the support chatbot's reasoning loop, so the chatbot's LLM can run
  guarded Postgres queries to answer live-data questions. This is the one place
  a service-side component reaches Postgres through MCP rather than a direct
  driver — justified because the consumer there is an LLM making runtime
  decisions, not deterministic app code (app services still use SQLAlchemy).
- **Skills**: a project skill capturing "how we write a new FastAPI
  endpoint here" (comment standard, error-handling shape, how to register
  the route in nginx) so every service written this week follows the same
  pattern without re-explaining it each session.
- **Hooks**: a post-edit hook that runs the relevant service's
  lint/tests automatically after an Edit/Write inside that service's
  directory, so mistakes surface immediately instead of at end-of-day
  integration.
- **Slash command**: `/test` — introduced as a stub Day 1, grows real teeth
  as each service gets a test suite, finalized Day 7 to run the right
  command (pytest per backend service, `ng test` for frontend) based on
  where you're working.
- **README**: a living document, started Day 1, extended every day as each
  piece lands, finalized Day 7 — not written cold at the end.

## Repo layout additions

```
tinder/
  docker-compose.yml
  .mcp.json                     # NEW — Postgres MCP server for Claude Code
  .claude/
    skills/fastapi-endpoint/    # NEW — endpoint-authoring convention
    commands/test.md            # NEW — /test slash command
    settings.json                # NEW — post-edit lint/test hook
  CLAUDE.md                     # repo-wide conventions
  README.md                     # living doc, grown daily
  image_store/                  # local disk image storage (git-ignored)
  auth_service/                 # NEW
  profile_service/              # EXISTS — extend
  image_service/                # NEW
  recommendation_service/       # NEW
  matcher_service/              # NEW
  session_service/              # NEW
  direct_msg/                   # EXISTS (empty) — becomes chat/websocket service
  support_chatbot_service/      # NEW — RAG + memory, LangSmith traced
  observability/                # NEW — prometheus.yml, grafana provisioning
  frontend/                     # NEW — Angular app
  gateway/                      # EXISTS — extend routes as services are added
```

Each backend service keeps its own lean `CLAUDE.md`.

## Day-by-day plan (vertical slices)

### Day 1 — Foundations, Auth (verified), dev tooling
- `docker-compose.yml`: `db` (postgres), `gateway`, `auth-service`,
  `profile-service`, `frontend`. Internal names/ports match what
  `gateway/conf.d/default.conf` already expects.
- `auth_service/main.py`: register, login (issue signed JWT), `/validate`
  for nginx's `auth_request`. `/validate` returns the user id in an
  `X-User-Id` **response header** (not just the body) so nginx can capture it.
  Every function commented with purpose + why.
- **Wire the `X-User-Id` handoff in nginx** (currently missing from
  `gateway/conf.d/default.conf`, which only calls `auth_request` and forwards
  `Authorization`). The auth model in `CLAUDE.md` depends on these two lines
  and they don't exist yet:
  - in `location = /auth/validate`: `auth_request_set $user_id
    $upstream_http_x_user_id;`
  - in every protected location: `proxy_set_header X-User-Id $user_id;`
  Without them, downstream services get no user id and the whole "gateway is
  the only thing that authenticates" model doesn't actually work.
- **Config via env, not hardcoded hosts.** `profile_service/main.py` currently
  hardcodes `postgresql://...@localhost:5432/...`; inside compose the DB host
  is `db`, not `localhost`. Every service reads `DATABASE_URL` (and JWT
  secret, etc.) from the environment, set in `docker-compose.yml`. Fix this on
  Day 1 as the pattern every later service copies.
- **CORS / dev proxy.** The Angular dev server (:4200) hitting the gateway
  (:8080) is cross-origin. Pick one up front — an Angular dev-server proxy
  (`proxy.conf.json`) or CORS headers at the gateway — or Register/Login
  won't talk to auth. Dev proxy is cleaner (keeps the browser same-origin).
- Verify for real: curl `/profile` unauthenticated → 401; register/login →
  token; curl with token → passes through **and the upstream sees a correct
  `X-User-Id`**.
- Angular: scaffold app, Register + Login pages, route guard.
- **Dev tooling**: `.mcp.json` Postgres MCP server; `.claude/skills/
  fastapi-endpoint/` skill; `.claude/settings.json` post-edit lint/test
  hook; `.claude/commands/test.md` stub; start `README.md` and root
  `CLAUDE.md`.
- **Verification**: register+login through the UI; gateway auth boundary
  confirmed with curl.

### Day 2 — Profile + Image service
- Extend `profile_service`: require auth, add age/gender/city/lat/long/bio.
- **Reconcile the route path.** nginx proxies `location /profile` to the
  service preserving the path, but the only route today is `POST
  /create-profile` — so `/profile` 404s in the app. Mount the profile routes
  under `/profile/...` (or rewrite in nginx) so the gateway path and the
  FastAPI path actually agree. Profile writes take the user id from the
  gateway's `X-User-Id` header, not from the request body.
- `image_service/main.py`: writes to `image_store/<user_id>/<uuid>.<ext>`,
  stores `(image_id, profile_id, url)` in Postgres; cap 5 images/user.
- Add `image_store/` to `.gitignore` (there's no `.gitignore` yet) so uploaded
  binaries never get committed.
- New nginx route for `/images`.
- Angular: profile create/edit with multi-image upload, profile view.
- README: add Profile/Image sections. `/test` gains real assertions for
  these two services.
- **Verification**: create/edit profile with images via UI; confirm files on
  disk match DB rows; reload confirms persistence.

### Day 3 — Discovery, Recommendation, Swipe/Match
- **Frontend page split, deferred from Day 2 (2026-08-13):** Day 2 kept the
  profile form + photo upload on a single repurposed `Home` component to
  avoid new routes mid-build. Now that Day 3 needs `Home` to become the
  actual swipe deck, split it for real: `Home` (`/`, the card stack),
  `Profile` (`/profile`, the create/edit form, moved out of `Home`).
  **Decided (2026-08-13): photo upload does NOT get its own route/page** —
  it stays as an inline preview panel adjacent to the profile form (the
  side-by-side locked/unlocked pattern already built Day 2), just carried
  over into the new `Profile` component. `authGuard` applies to both routes.
- `recommendation_service/main.py`: bounding-box + age/gender candidate
  feed, excludes already-swiped profiles. Comments explain the tradeoff vs.
  a real sharded approach.
- `matcher_service/main.py`: records swipes, creates a match row on mutual
  right-swipe.
- Angular: Discover (card stack) + Matches list.
- README: add Discovery/Matching section.
- **Verification**: two seeded users mutually swipe right → match row exists,
  both see it in the UI.

### Day 4 — Sessions + Direct Messaging
- `session_service/main.py`: in-memory user_id → active websocket map
  (comment notes this doesn't survive a restart and why that's fine now).
- `direct_msg/main.py`: WebSocket endpoint; confirms match via
  matcher-service before allowing a message; persists messages.
- **WebSocket auth gotcha.** `auth_request` + the WS upgrade don't compose
  cleanly, and a browser can't set an `Authorization` header on a WebSocket.
  So the token rides as a query param (or subprotocol) and is validated
  either by a pre-connect HTTP call to auth or inside `direct_msg` itself —
  this is the one place the "only the gateway authenticates" rule bends, and
  the reason gets a comment. nginx also needs the upgrade headers
  (`proxy_set_header Upgrade $http_upgrade; proxy_set_header Connection
  "upgrade";`) on the chat location.
- Angular: Chat page per match.
- README: add Messaging section.
- **Verification**: two matched test users exchange messages live in separate
  browser sessions; history persists across refresh.

### Day 5 — Support Chatbot (RAG + memory) + LangSmith tracing
- `support_chatbot_service/main.py`: chunks & embeds `README.md`/service
  docs locally (a small local embedding model — e.g. `all-MiniLM`, keep the
  dependency light; `sentence-transformers`+`torch` is a heavy container so
  size it consciously), stores vectors in Postgres via `pgvector` (reuses the
  existing DB — this is why Day 1 uses the `pgvector/pgvector` image — no new
  infra; run `CREATE EXTENSION IF NOT EXISTS vector` on startup), retrieves
  relevant chunks per question, calls Claude for the answer.
- Conversation memory: persist `(session_id, role, message)` per user so
  follow-ups keep context; loaded back in on each turn.
- **Live data via MCP**: expose the project's Postgres MCP server (`.mcp.json`)
  as a tool the chatbot's LLM can call, so questions needing live DB state
  (e.g. "how many matches do I have?", "what's my profile city?") are answered
  by running guarded, read-only Postgres queries through MCP — alongside RAG
  over the docs. Scope the tool to safe, parameterized/read-only queries and
  the requesting user's own rows (the chatbot knows the caller's `X-User-Id`),
  so it can't be used to read arbitrary accounts. This is deliberately the one
  spot where a runtime component uses MCP for DB access, because the caller is
  an LLM, not deterministic app code.
- Wrap the Anthropic client with LangSmith's `wrap_anthropic` so every
  chatbot call is traced (prompt, retrieved context, response, latency, and
  any MCP tool calls it made).
- Angular: Support/Help chat widget.
- README: add Support Chatbot section (architecture, not "how we thought of
  it").
- **Verification**: ask a support question grounded in README content, ask a
  follow-up that depends on memory, ask a live-data question that forces an MCP
  Postgres query (e.g. match count) and confirm the answer matches the DB;
  confirm all traces (including the MCP tool call) show up in LangSmith.
- **End of day**: pause for a short separate discussion to scope the
  precision/recall eval (golden Q&A set construction, scoring approach) —
  planned, not built, today.

### Day 6 — Observability: Prometheus + Grafana
- Instrument every service with `prometheus_client` `/metrics`: request
  counts/latency, login counts, chat message counts, swipe/match counts.
- `observability/prometheus.yml` scrapes all services; `observability/
  grafana/` provisions dashboards for the three things asked for
  specifically: user logins over time, chat volume, DB size/volume
  (`pg_database_size` etc.), plus general per-service request rates as a
  bonus.
- Add both containers to `docker-compose.yml`.
- Angular: an internal admin page linking/embedding the Grafana dashboards
  (Grafana remains the real dashboard; Angular just surfaces it).
- README: add Observability section (what's tracked, how to view it).
- **Verification**: generate logins/chats, confirm the numbers move in
  Grafana within one scrape interval.

### Day 7 — Integration, hardening, docs/tooling finish
- Full `docker compose up` walkthrough of the entire journey: register →
  profile → images → discover → swipe → match → chat → ask the support bot
  a question — including checking Grafana reflects the activity and
  LangSmith shows the chatbot traces.
- Apply the rate-limit/caching snippets already parked in
  `gateway/conf.d/confcanbethere.txt` (e.g. rate-limit swipe/discover, short
  cache on the discovery feed).
- Finish `/test`: runs the right test command (pytest per backend service
  dir, `ng test` for frontend) based on where it's invoked.
- Comment sweep across every service (including chatbot/observability code)
  for the "purpose + why" standard.
- Finish every service's `CLAUDE.md` + root `CLAUDE.md`.
- Finalize `README.md`: architecture overview, setup/run instructions, every
  service described, how to use the chatbot, how to read the dashboards —
  entirely first-principles reasoning, no external attribution.
- Write a **Day 8+ backlog**: real sharded/Cassandra recommendation engine,
  MinIO/S3 for images, JWT refresh + hardening, per-service databases, the
  chatbot precision/recall eval (golden set + scoring, scoped on Day 5),
  <!-- 2026-08-09: removed from backlog — "live-DB tool access for the chatbot
       via the MCP server" is now Day-5 core scope, not backlog. Old text kept:
  live-DB tool access for the chatbot via the MCP server,
  -->
  automated test
  suite expansion, cloud deployment.

## How we'll actually work each day (Claude Code workflow)

- Each service/feature gets its own scoped session — stay inside one
  service directory at a time so context (and comment review) stays tight.
- Before writing a new service, do a quick read-only pass over related
  existing code/config instead of assuming what's there.
- The post-edit hook (Day 1) surfaces lint/test failures immediately inside
  a session, rather than discovering them at end-of-day integration.
- The `fastapi-endpoint` skill keeps every new endpoint's shape (comments,
  error handling, gateway registration) consistent without re-explaining it
  each time.
- Nothing is marked done without an actual run — `docker compose up`, then
  curl/browser/Postgres check.

## Verification plan (end of Day 7)

1. `docker compose up` brings up all services (including chatbot,
   Prometheus, Grafana) + Angular dev server cleanly.
2. Full manual walkthrough: two users register → build profiles with
   images → discover and mutually swipe right → match → chat in real time
   → one of them asks the support chatbot a question and a relevant,
   README-grounded answer comes back, with memory holding across a
   follow-up.
3. Auth boundary regression check: unauthenticated `/profile` still 401s.
4. `image_store/` on disk matches Postgres references.
5. Grafana shows login count, chat volume, and DB size reacting to the
   walkthrough; LangSmith shows traces for both chatbot turns.
6. `/test` run from inside any service directory runs and passes that
   service's tests.
