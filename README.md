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

## Services

| Service | Port | Owns | Status |
|---|---|---|---|
| `gateway/` (nginx) | 8080 | routing + auth gate | ✅ Day 1 |
| `auth_service/` | 8002 | credentials, JWT issue/verify | ✅ Day 1 |
| `profile_service/` | 8001 | profile fields (own + by-id lookup) | ✅ Day 2, extended Day 3 |
| `image_service/` | 8003 | image upload to disk, own + by-id/by-user viewing | ✅ Day 2, extended Day 3 |
| `matcher_service/` | 8004 | swipes, match detection | ✅ Day 3 |
| `recommendation_service/` | 8005 | candidate feed (bounding-box + age/gender) | ✅ Day 3 |
| `session_service/` | — | user→websocket map | ⏳ Day 4 |
| `direct_msg/` | — | websocket chat + persistence | ⏳ Day 4 |
| `support_chatbot_service/` | — | RAG + memory + live DB via MCP | ⏳ Day 5 |
| `observability/` | — | Prometheus + Grafana | ⏳ Day 6 |
| `frontend/` (Angular) | 4200 | one page per feature | ✅ Day 1–3 (auth, profile/images, discover/matches), more to come |

## Running it

```bash
docker compose up -d --build      # db, auth, profile, image, matcher, recommendation, gateway, pgweb
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
post-edit syntax hook, a `/test` command, a `fastapi-endpoint` skill (how every
backend route in this repo is written/wired), and a `run-tinder` skill (launches
the Angular dev server and drives it headlessly via Playwright — screenshots,
form fills, login flows — for verifying frontend changes without a human at a
browser).
