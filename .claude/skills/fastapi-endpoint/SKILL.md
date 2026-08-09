---
name: fastapi-endpoint
description: How to write and register a new FastAPI endpoint in this tinder repo — comment standard, error-handling shape, X-User-Id trust model, and the nginx route wiring. Use whenever adding an endpoint to any backend service here.
---

# Writing a new FastAPI endpoint (tinder repo convention)

Follow this every time you add an endpoint to a backend service so all services
stay consistent. Concrete reference implementation: `auth_service/main.py` and
`profile_service/main.py`.

## 1. Comment standard (non-negotiable in this repo)
Every function gets a docstring/comment saying **what it is and *why* it exists**
— not a restatement of the code. Non-obvious lines get an inline comment on the
reasoning. The goal is debuggability: someone reading it cold understands the
intent, not just the mechanics.

## 2. Identity comes from the gateway, never the body
Protected routes receive the authenticated user id in the `X-User-Id` **request
header**, set by nginx after `auth_request` (see the auth model below). Read it;
never take a user id from the request body.

```python
from fastapi import Header, HTTPException

@app.get("/thing")
def get_thing(x_user_id: str = Header(default=None)):
    # Trust X-User-Id because only the gateway can reach this service and it sets
    # the header only after auth_service's /validate succeeded. Missing header =>
    # the request didn't come through the gateway's auth path => refuse.
    if not x_user_id:
        raise HTTPException(status_code=401, detail="Missing X-User-Id from gateway")
    ...
```
This service never verifies the JWT itself — that's auth_service's sole job.

## 3. Error handling shape
- Raise `HTTPException(status_code=..., detail=...)`; don't return ad-hoc error
  dicts.
- Validate/guard up front (e.g. duplicate check) so DB constraint violations
  aren't the thing surfacing an opaque 500.
- Keep auth failures **generic** (one "invalid email or password" for both
  unknown-email and wrong-password) so you don't leak which accounts exist.

## 4. DB session hygiene
Open `SessionLocal()`, do the work, and `close()` in a `finally` so a raised
HTTPException still releases the connection:
```python
db = SessionLocal()
try:
    ...
finally:
    db.close()
```
Tables are created on startup via `Base.metadata.create_all(bind=engine)` (build-
week convention; Alembic is backlog). Each service owns its own tables in the
shared `tinder` DB.

## 5. Config from env, never hardcoded
Read `DATABASE_URL` (and any secret) from `os.environ`, set in
`docker-compose.yml`. Inside compose the DB host is `db`, not `localhost`.

## 6. Register the route in nginx (`gateway/conf.d/default.conf`)
The gateway is the only thing clients talk to, so a new path isn't reachable
until it's added here.

- **Public route** (no auth): add a `location` that just proxies.
- **Protected route**: copy the `/profile` block — it must include all three of:
  ```nginx
  location /yourpath {
      auth_request /auth/validate;                         # gate on auth
      auth_request_set $user_id $upstream_http_x_user_id;  # capture the id
      proxy_pass http://your-service:PORT;
      proxy_set_header Authorization $http_authorization;
      proxy_set_header X-User-Id $user_id;                 # forward the id
  }
  ```
  All three lines are required — without `auth_request_set` + the `X-User-Id`
  `proxy_set_header`, the upstream gets no identity.
- Make the **FastAPI path and the nginx location agree.** nginx forwards the
  path unchanged (no trailing-slash rewrite), so a `location /foo` reaches the
  service as `/foo...` — mount the route to match.
- Config is mounted into the gateway container, so a route change needs at most
  `docker compose restart gateway` (or an nginx reload), not a rebuild.

## 7. Verify for real
Nothing is "done" on looks. After adding the endpoint: `docker compose up`, then
curl through the gateway (`http://localhost:8080`) — unauthenticated should 401,
authenticated should pass and the upstream should see the right `X-User-Id`. Add
a matching assertion so `/test` can cover it.
