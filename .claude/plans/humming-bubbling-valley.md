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
- **Data store**: one shared local Postgres (plain `postgres` image, not the
  full Supabase stack). `Supabase_README.md` stays as background notes only.
- **Coding standard**: every function commented with what it is and why it's
  there; non-obvious lines/line-groups get inline comments too. Applies to
  every service and the Angular code.
- **Verification discipline**: nothing is "done" on the strength of "the code
  looks right" — every slice ends with an actual run (`docker compose up`,
  curl/browser check, or an assertion against Postgres).
- **Support chatbot**: RAG over our own README/docs (no external knowledge),
  with persisted conversation memory per user/session so follow-up questions
  keep context. Answers questions about how to use the app, not live account
  data (querying live account state is a backlog idea, not this week).
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
  debugging, instead of shelling out to `psql` ad hoc. (Exposing that same
  server as a live tool inside the chatbot's own reasoning loop is a backlog
  idea, not core scope, given the chatbot is RAG+memory only for now.)
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
  for nginx's `auth_request`. Every function commented with purpose + why.
- Verify for real: curl `/profile` unauthenticated → 401; register/login →
  token; curl with token → passes through.
- Angular: scaffold app, Register + Login pages, route guard.
- **Dev tooling**: `.mcp.json` Postgres MCP server; `.claude/skills/
  fastapi-endpoint/` skill; `.claude/settings.json` post-edit lint/test
  hook; `.claude/commands/test.md` stub; start `README.md` and root
  `CLAUDE.md`.
- **Verification**: register+login through the UI; gateway auth boundary
  confirmed with curl.

### Day 2 — Profile + Image service
- Extend `profile_service`: require auth, add age/gender/city/lat/long/bio.
- `image_service/main.py`: writes to `image_store/<user_id>/<uuid>.<ext>`,
  stores `(image_id, profile_id, url)` in Postgres; cap 5 images/user.
- New nginx route for `/images`.
- Angular: profile create/edit with multi-image upload, profile view.
- README: add Profile/Image sections. `/test` gains real assertions for
  these two services.
- **Verification**: create/edit profile with images via UI; confirm files on
  disk match DB rows; reload confirms persistence.

### Day 3 — Discovery, Recommendation, Swipe/Match
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
- Angular: Chat page per match.
- README: add Messaging section.
- **Verification**: two matched test users exchange messages live in separate
  browser sessions; history persists across refresh.

### Day 5 — Support Chatbot (RAG + memory) + LangSmith tracing
- `support_chatbot_service/main.py`: chunks & embeds `README.md`/service
  docs locally (e.g. a small local embedding model), stores vectors in
  Postgres via `pgvector` (reuses the existing DB, no new infra), retrieves
  relevant chunks per question, calls Claude for the answer.
- Conversation memory: persist `(session_id, role, message)` per user so
  follow-ups keep context; loaded back in on each turn.
- Wrap the Anthropic client with LangSmith's `wrap_anthropic` so every
  chatbot call is traced (prompt, retrieved context, response, latency).
- Angular: Support/Help chat widget.
- README: add Support Chatbot section (architecture, not "how we thought of
  it").
- **Verification**: ask a support question grounded in README content, ask a
  follow-up that depends on memory, confirm both traces show up in
  LangSmith.
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
  live-DB tool access for the chatbot via the MCP server, automated test
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
