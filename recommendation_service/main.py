"""
recommendation_service — computes the candidate feed for Discover.

Why this service exists: deciding "who should I show this user next" is a
distinct concern from profile data (profile_service) and swipe/match
bookkeeping (matcher_service) — this service only ever reads, never writes,
which is also why it owns no tables of its own and never calls
Base.metadata.create_all() the way every other service here does.

Cross-service reads (deliberate exception): this service reads the
`profiles`, `swipes`, and `images` tables directly from the shared Postgres
instance, rather than calling profile_service/matcher_service/image_service
over HTTP. A candidate feed is fundamentally a SQL WHERE-clause problem
(bounding box + age/gender + "not already swiped") — doing that in SQL lets
Postgres use its indexes; doing it over HTTP would mean pulling every row
across the network and filtering in Python instead. This is the one place
in the repo a service reads data it doesn't own — the same kind of
deliberate exception as the support chatbot's MCP-based Postgres access
(see CLAUDE.md's auth model section).

Not real production scale: this queries one unsharded `profiles` table with
a hand-rolled lat/long bounding box (see compute_bounding_box below) rather
than a true circular radius. A real system at Tinder's scale would geo-shard
the data, or use a dedicated geo-indexed store (PostGIS, Elasticsearch,
Redis geo), so a discovery query only ever touches the region the requester
is actually in, instead of range-scanning one global table.
"""

from fastapi import FastAPI, Header, HTTPException, Query
from sqlalchemy import bindparam, create_engine, text
import math
import os

DATABASE_URL = os.environ["DATABASE_URL"]
engine = create_engine(DATABASE_URL)

# Rough km-per-degree-of-latitude — constant everywhere on Earth, since
# lines of latitude are evenly spaced. The longitude side isn't a constant;
# it depends on the caller's own latitude (see compute_bounding_box below).
KM_PER_DEGREE_LAT = 111.0

DEFAULT_RADIUS_KM = 50.0
DEFAULT_CANDIDATE_LIMIT = 20

app = FastAPI()


def get_user_id(x_user_id: str = Header(default=None)) -> str:
    """Shared guard: every route below needs the authenticated caller's id."""
    if not x_user_id:
        raise HTTPException(status_code=401, detail="Missing X-User-Id from gateway")
    return x_user_id


def compute_bounding_box(lat: float, long: float, radius_km: float) -> tuple[float, float, float, float]:
    """Turn "within radius_km of (lat, long)" into a lat/long rectangle.

    Returns (lat_min, lat_max, long_min, long_max) — a plain SQL BETWEEN on
    two indexed numeric columns, not a real circle (see the module docstring
    for why that's an accepted approximation here).
    """
    lat_delta = radius_km / KM_PER_DEGREE_LAT

    # Longitude degrees shrink toward the poles (meridians converge), so the
    # km-per-degree here depends on the caller's own latitude. cos(90°) = 0
    # would divide by zero at the poles — guarded even though no real user
    # in this build is ever there, since a bug here would otherwise crash
    # every request instead of failing loudly in an obvious spot.
    km_per_degree_long = KM_PER_DEGREE_LAT * math.cos(math.radians(lat))
    long_delta = radius_km / km_per_degree_long if km_per_degree_long > 0 else 180.0

    return (lat - lat_delta, lat + lat_delta, long - long_delta, long + long_delta)


@app.get("/discover")
def discover(
    x_user_id: str = Header(default=None),
    radius_km: float = Query(default=DEFAULT_RADIUS_KM),
    min_age: int | None = Query(default=None),
    max_age: int | None = Query(default=None),
    gender: str | None = Query(default=None),
    limit: int = Query(default=DEFAULT_CANDIDATE_LIMIT),
):
    """Return a batch of candidate profiles for the caller to swipe on.

    min_age/max_age/gender are optional and unpersisted — the frontend
    decides whether to send them on a given request (see IDEAS.md for
    "distance setting" as a related future preference). radius_km/limit have
    defaults so a bare GET /discover with no query params still works.
    """
    user_id = get_user_id(x_user_id)

    with engine.connect() as conn:
        # The caller must have their own lat/long on file to search around —
        # same "create a profile first" requirement profile_service's own
        # routes already assume.
        own_profile = conn.execute(
            text("SELECT lat, long FROM profiles WHERE id = :user_id"),
            {"user_id": user_id},
        ).first()
        if not own_profile:
            raise HTTPException(status_code=404, detail="Create a profile before discovering others")

        lat_min, lat_max, long_min, long_max = compute_bounding_box(own_profile.lat, own_profile.long, radius_km)

        candidates = conn.execute(
            text(
                """
                SELECT id, name, age, gender, city, bio
                FROM profiles
                WHERE id != :user_id
                  AND lat BETWEEN :lat_min AND :lat_max
                  AND long BETWEEN :long_min AND :long_max
                  AND id NOT IN (SELECT target_id FROM swipes WHERE swiper_id = :user_id)
                  AND (:min_age IS NULL OR age >= :min_age)
                  AND (:max_age IS NULL OR age <= :max_age)
                  AND (:gender IS NULL OR gender = :gender)
                ORDER BY id
                LIMIT :limit
                """
            ),
            {
                "user_id": user_id,
                "lat_min": lat_min,
                "lat_max": lat_max,
                "long_min": long_min,
                "long_max": long_max,
                "min_age": min_age,
                "max_age": max_age,
                "gender": gender,
                "limit": limit,
            },
        ).all()

        if not candidates:
            return []

        candidate_ids = [c.id for c in candidates]

        # One query for every candidate's photo ids, rather than one query
        # per candidate — an N+1 query per swipe-deck batch would multiply
        # DB round-trips for no benefit, since this is a single WHERE ... IN.
        image_rows = conn.execute(
            text("SELECT id, profile_id FROM images WHERE profile_id IN :ids").bindparams(
                bindparam("ids", expanding=True)
            ),
            {"ids": candidate_ids},
        ).all()

        # Group photo ids by profile id so each candidate below can look up
        # its own list in O(1) instead of re-scanning image_rows per candidate.
        images_by_profile: dict[str, list[str]] = {}
        for row in image_rows:
            images_by_profile.setdefault(row.profile_id, []).append(row.id)

        return [
            {
                "user_id": c.id,
                "name": c.name,
                "age": c.age,
                "gender": c.gender,
                "city": c.city,
                "bio": c.bio,
                "image_ids": images_by_profile.get(c.id, []),
            }
            for c in candidates
        ]
