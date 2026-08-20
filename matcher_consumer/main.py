"""
matcher_consumer — decides whether a swipe completes a mutual match.

Why this service exists (Phase 1 of the production-scale plan, 2026-08-20):
matcher_service used to do this check inline, in the same DB transaction as
the swipe write (see matcher_service/main.py's commented-out Step 2). That
only works on a single Postgres node. Once swipe data is sharded by
user_id, A's swipe and B's swipe could be owned by different shards, so a
single-node transaction can no longer safely decide "is this a match".

Instead, matcher_service publishes every swipe to the `swipes` Redpanda
topic, keyed by the SORTED pair of the two user ids (e.g. "A:B", not "B:A"
or either id alone). Redpanda hashes that key to deterministically pick a
partition, and guarantees only one consumer instance ever reads a given
partition at a time — so both directions of a mutual like always land on
the same partition, processed by the same consumer, and the race that
inline code used to prevent via one DB transaction is instead prevented by
routing. This is the actual mechanism behind "consistent hashing" from the
production-scale plan.

On a confirmed match, this service publishes a MatchCreated event to the
`matches` topic — a hook for future consumers (a notification service, or
the icebreaker-suggestion feature from the original Day 6 plan) to react to
new matches without matcher_consumer needing to know they exist.

Shared-table access (deliberate exception, same reasoning as
recommendation_service's cross-service reads): this service reads `swipes`
and writes `matches`, tables matcher_service still owns and also reads/
writes. Both services define identical SQLAlchemy models for them rather
than importing from one another — these are independently deployable
services with no shared package between them, same reasoning image_service
already used for duplicating the get_user_id guard instead of importing it.
"""

import json
import os
import threading
import time
import uuid

from confluent_kafka import Consumer, Producer
from fastapi import FastAPI, Request, Response
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from sqlalchemy import Column, DateTime, String, UniqueConstraint, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.sql import func

DATABASE_URL = os.environ["DATABASE_URL"]
REDPANDA_BROKERS = os.environ.get("REDPANDA_BROKERS", "redpanda:9092")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class Swipe(Base):
    """Mirrors matcher_service's Swipe model exactly — same table, read-only
    from here (this service only ever queries it, matcher_service is still
    the sole writer)."""

    __tablename__ = "swipes"

    swiper_id = Column(String, primary_key=True)
    target_id = Column(String, primary_key=True)
    direction = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Match(Base):
    """Mirrors matcher_service's Match model exactly — this service is now
    the sole writer of this table; matcher_service still reads it (for
    GET /matches and GET /matches/{id})."""

    __tablename__ = "matches"
    __table_args__ = (UniqueConstraint("user_a_id", "user_b_id", name="uq_match_pair"),)

    id = Column(String, primary_key=True, index=True)
    user_a_id = Column(String, nullable=False, index=True)
    user_b_id = Column(String, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# Idempotent — matcher_service already creates these tables on its own
# startup. Calling this here too avoids a hard startup-ordering dependency
# between the two services beyond both just needing `db` healthy.
Base.metadata.create_all(bind=engine)

app = FastAPI(title="matcher_consumer")

# --- Observability: generic request metrics, same pattern as every other
# service (see auth_service/main.py) — this app only ever serves /metrics
# and /health, the real work below never goes through HTTP at all. ---------
REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests received by this service",
    ["method", "path", "status"],
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "path"],
)


@app.middleware("http")
async def track_requests(request: Request, call_next):
    """Times every request and records it under the generic HTTP metrics."""
    start = time.perf_counter()
    response = await call_next(request)
    REQUEST_LATENCY.labels(request.method, request.url.path).observe(
        time.perf_counter() - start
    )
    REQUEST_COUNT.labels(request.method, request.url.path, response.status_code).inc()
    return response


@app.get("/metrics")
def metrics():
    """Serializes the in-memory counters/histograms for Prometheus to scrape."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/health")
def health():
    """Liveness probe. Deliberately doesn't check consumer-thread health —
    a real system would want that, but confluent-kafka doesn't expose a
    simple "is the consume loop alive" flag; out of scope for this build."""
    return {"status": "ok"}


# Moved from matcher_service (2026-08-20): match creation happens here now,
# so this is where the metric belongs — incremented right where a Match row
# is actually inserted, below.
MATCH_COUNT = Counter("matcher_matches_total", "Total matches created")

# Publishes MatchCreated events — separate Producer instance from
# matcher_service's (different process, can't share one).
match_producer = Producer({"bootstrap.servers": REDPANDA_BROKERS})


def handle_swipe_event(payload: dict):
    """Runs the same reverse-like-check-and-insert-match logic that used to
    live inline in matcher_service's record_swipe (see that file's
    commented-out Step 2) — moved here so it runs on the consumer side,
    safe from the cross-shard race described in this module's docstring.
    """
    swiper_id = payload["swiper_id"]
    target_id = payload["target_id"]
    direction = payload["direction"]

    if direction != "like":
        return  # only a "like" can ever create a match, same as the original inline check

    db = SessionLocal()
    try:
        reverse_like = (
            db.query(Swipe)
            .filter(
                Swipe.swiper_id == target_id,
                Swipe.target_id == swiper_id,
                Swipe.direction == "like",
            )
            .first()
        )
        if not reverse_like:
            return

        # Canonical (alphabetical) order — same convention the Match model
        # already used when this lived in matcher_service.
        user_a_id, user_b_id = sorted([swiper_id, target_id])
        already_matched = (
            db.query(Match)
            .filter(Match.user_a_id == user_a_id, Match.user_b_id == user_b_id)
            .first()
        )
        if already_matched:
            return

        match_id = str(uuid.uuid4())
        db.add(Match(id=match_id, user_a_id=user_a_id, user_b_id=user_b_id))
        db.commit()
        MATCH_COUNT.inc()  # business metric: a new match was just created

        # Publish for future consumers (notifications, icebreaker suggestions)
        # to react to without needing to know this service's internals.
        match_producer.produce(
            "matches",
            key=match_id,
            value=json.dumps({"match_id": match_id, "user_a_id": user_a_id, "user_b_id": user_b_id}),
        )
        match_producer.flush(timeout=5)
    finally:
        db.close()


def consume_loop():
    """Runs forever in a background thread (started at import time, below).

    Manual offset commits (enable.auto.commit=False), committed only after
    handle_swipe_event finishes for that message — so a crash mid-processing
    re-reads the same message on restart instead of silently skipping it as
    already-handled. group.id matters: all matcher-consumer replicas (Phase
    6, once this runs on Kubernetes) share one group, so Redpanda divides
    the 6 swipes partitions across however many replicas are running,
    rather than every replica reading every partition redundantly.
    """
    consumer = Consumer({
        "bootstrap.servers": REDPANDA_BROKERS,
        "group.id": "matcher-consumer-group",
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
    })
    consumer.subscribe(["swipes"])
    try:
        while True:
            msg = consumer.poll(timeout=1.0)
            if msg is None:
                continue
            if msg.error():
                print(f"consumer error: {msg.error()}")
                continue
            handle_swipe_event(json.loads(msg.value()))
            consumer.commit(msg)
    finally:
        consumer.close()


# Started once, at import time — daemon=True so this thread doesn't block
# the process from exiting on shutdown (it has no cleanup that matters more
# than a clean container stop).
threading.Thread(target=consume_loop, daemon=True).start()
