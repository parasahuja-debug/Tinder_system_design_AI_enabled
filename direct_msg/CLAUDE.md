# direct_msg

WebSocket chat between two matched users, with persisted history. The one
service where the gateway's `auth_request` model doesn't apply to its main
route — see main.py's module docstring for the full reasoning on why and how
it authenticates itself instead.

## Endpoints
- `WS /chat/ws/{match_id}` — the live chat connection. Client must offer the
  JWT via the WebSocket subprotocol list: `new WebSocket(url, ['bearer',
  <token>])`. Closes with code `4401` on bad/missing token, `4403` if the
  token is valid but the caller isn't a participant in `match_id`. Once
  connected, send `{"body": "..."}` JSON frames; receives the same shape
  back (server-assigned `id`/`created_at`) for both the sender's own
  messages and the other participant's, when they're connected too.
- `GET /chat/history/{match_id}` — gateway-protected (normal `auth_request`
  + `X-User-Id`) HTTP route; returns every persisted message for a match,
  oldest first. Also enforces match membership itself (see main.py) since
  `auth_request` alone doesn't prove that.
- `GET /health` → `{status: ok}`

## Table (in shared DB)
`messages(id uuid PK, match_id indexed, sender_id, body, created_at)` —
created on startup via `Base.metadata.create_all`.

## Talks to (service-to-service, not through the gateway)
- `auth-service` `GET /validate` — resolves a WS connection's token to a
  real user_id.
- `matcher-service` `GET /matches/{match_id}?user_id=` — confirms match
  membership, both at WS connect time and on every `/chat/history` call.
- `session-service` `POST /session/connect` / `/session/disconnect` —
  best-effort presence updates; failures here don't affect the chat itself.
- `redis` (Phase 2 of the production-scale plan) — chat message delivery
  fans out via Pub/Sub, not a local dict lookup: each instance subscribes
  to `chat:<user_id>` for every user it currently holds a socket for, and
  every outgoing message is published to `chat:<recipient_id>` unconditionally,
  so delivery works whether the recipient's socket lives on this same
  process or a different replica. See `main.py`'s module-level Redis
  comment and `redis_listener` for the full mechanism.

## Env
`DATABASE_URL` (required); `AUTH_SERVICE_URL`, `MATCHER_SERVICE_URL`,
`SESSION_SERVICE_URL`, `REDIS_URL` (all default to their compose-network
hostnames).

## Run standalone
```
pip install -r requirements.txt
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/tinder \
REDIS_URL=redis://localhost:6379/0 \
uvicorn main:app --port 8007
# needs auth-service/matcher-service/session-service/redis reachable at
# their default URLs (or override via env) for a real connection to succeed.
```
