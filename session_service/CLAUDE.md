# session_service

Thin presence registry: tracks which users currently have a live WebSocket
connection to `direct_msg`. Does not hold the sockets themselves — only
`direct_msg` can, since it's the process that accepted them. Called only by
`direct_msg`, over the compose-internal network; never reachable through the
gateway, so there's no `X-User-Id`/`auth_request` model here.

## Endpoints
- `POST /session/connect` `{user_id}` → `200 {status: connected, user_id}`
- `POST /session/disconnect` `{user_id}` → `200 {status: disconnected, user_id}`
- `GET /session/{user_id}` → `200 {user_id, online, connected_at}`
- `GET /health` → `{status: ok}`

## State
Redis keys (`presence:<user_id>` -> ISO timestamp), as of Phase 2 of the
production-scale plan — moved off an in-memory dict specifically so presence
is visible across replicas of this service, not trapped in whichever one
happened to handle a given connect/disconnect call. No expiry set on the
keys; a stale entry left behind by a direct_msg crash persists until the
next disconnect call for that user, same tradeoff the old in-memory version
had.

## Env
`REDIS_URL` (default `redis://redis:6379/0`). No `DATABASE_URL` — this
service has no Postgres tables.

## Run standalone
```
pip install -r requirements.txt
REDIS_URL=redis://localhost:6379/0 uvicorn main:app --port 8006
curl -XPOST localhost:8006/session/connect -H 'content-type: application/json' -d '{"user_id":"test-user"}'
curl localhost:8006/session/test-user
```
