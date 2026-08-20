# matcher_consumer

Consumes the `swipes` Redpanda topic and decides whether a swipe completes a
mutual match — logic that used to live inline in `matcher_service`'s
`record_swipe` (see that file's commented-out Step 2) before Phase 1 of the
production-scale plan moved it here, so match detection survives swipe data
being sharded across nodes at real scale. See `main.py`'s module docstring
for the full reasoning, including why the `swipes` topic's partition key
(the sorted pair of user ids) is what makes this safe without a distributed
transaction.

No HTTP business routes — the real work is a background thread
(`consume_loop`) reading Kafka messages, started at import time. The FastAPI
app only exists to serve `/metrics` and `/health`.

## Endpoints
- `GET /metrics` → Prometheus scrape target
- `GET /health` → `{status: ok}` (does not reflect consumer-thread health)

## Talks to
- Redpanda — consumes `swipes` (consumer group `matcher-consumer-group`,
  manual offset commits), produces `matches` (one `MatchCreated` event per
  new match, for future consumers like notifications or icebreaker
  suggestions).
- Postgres — reads `swipes`, writes `matches`. Both tables are owned by
  `matcher_service`; this is a deliberate shared-table exception, same
  reasoning as `recommendation_service`'s cross-service reads.

## Table access (shared with matcher_service, not owned here)
`swipes(swiper_id, target_id, direction, created_at)` — read-only from here.
`matches(id, user_a_id, user_b_id, created_at)` — this service is the sole
writer as of Phase 1; `matcher_service` still reads it for `GET /matches`
and `GET /matches/{id}`.

## Env
`DATABASE_URL` (required); `REDPANDA_BROKERS` (default `redpanda:9092`).

## Run standalone
```
pip install -r requirements.txt
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/tinder \
REDPANDA_BROKERS=localhost:9092 \
uvicorn main:app --port 8009
# needs a real swipe published to the `swipes` topic (e.g. via matcher_service's
# /swipe endpoint) to see it do anything — there's no standalone trigger.
```
