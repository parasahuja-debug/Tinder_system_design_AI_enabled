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
In-memory `dict[user_id, connected_at]` — no database, no persistence.
Doesn't survive a restart; acceptable because a restart just means every
connected client reconnects and re-registers, same as any dropped connection.

## Env
None required — no `DATABASE_URL`, since this service has no tables.

## Run standalone
```
pip install -r requirements.txt
uvicorn main:app --port 8006
curl -XPOST localhost:8006/session/connect -H 'content-type: application/json' -d '{"user_id":"test-user"}'
curl localhost:8006/session/test-user
```
