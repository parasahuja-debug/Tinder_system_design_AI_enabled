"""
auth_service — the only service that knows the JWT secret.

Why this service exists: nginx is the single door clients knock on, but nginx
itself can't decide "is this a real, logged-in user?". It delegates that
decision here. This service owns user credentials (a `users` table in the
shared Postgres) and issues/verifies signed JWTs. Downstream services never
see a password or a raw token — they only ever receive the `X-User-Id` that
nginx captured from `/validate`, so trust flows outward from this one place.
"""

import os
import time
import uuid
import datetime

import bcrypt
import jwt
from fastapi import FastAPI, Header, HTTPException, Request, Response
from pydantic import BaseModel
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from sqlalchemy import Column, String, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# --- Configuration from the environment, never hardcoded -------------------
# Why env, not literals: inside docker-compose the DB host is `db`, not
# `localhost`, and the JWT secret must be shared with nobody in source. Every
# service in this repo copies this same "read from env" pattern (set in
# docker-compose.yml) so a host/secret change is one edit, not a code sweep.
DATABASE_URL = os.environ["DATABASE_URL"]
JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
# Token lifetime in minutes; short-lived by default. Refresh tokens are backlog.
JWT_EXPIRE_MINUTES = int(os.environ.get("JWT_EXPIRE_MINUTES", "1440"))

# --- Database wiring --------------------------------------------------------
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class User(Base):
    """One row per registered account.

    Why only these columns: auth's job is authentication, not profile data.
    Name/age/city/bio live in profile_service keyed by the same id. We store a
    bcrypt *hash*, never the password, so a DB leak doesn't leak passwords.
    """

    __tablename__ = "users"

    id = Column(String, primary_key=True, index=True)  # UUID, also the JWT subject
    email = Column(String, unique=True, index=True, nullable=False)  # login handle
    password_hash = Column(String, nullable=False)  # bcrypt hash, never plaintext


# Create our own table on startup. Why here and not a migration tool: this is a
# build-week convention across every service — acceptable now, Alembic is backlog.
Base.metadata.create_all(bind=engine)

app = FastAPI(title="auth_service")

# --- Observability (Day 6): generic request metrics -------------------------
# Counter/Histogram objects hold running totals in memory; nothing exposes
# them to Prometheus yet (that's the /metrics endpoint, added next).
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
# Business metric, not a generic HTTP one: Grafana needs "logins over time"
# specifically, which no generic request counter can distinguish from any
# other 200 — incremented by hand where a login actually succeeds, below.
LOGIN_COUNT = Counter("auth_logins_total", "Total successful logins")


@app.middleware("http")
async def track_requests(request: Request, call_next):
    """Times every request and records it under the generic HTTP metrics.

    Why middleware and not per-route code: every current and future route in
    this service gets measured automatically, without remembering to add
    counter calls inside each new endpoint by hand.
    """
    start = time.perf_counter()
    response = await call_next(request)
    REQUEST_LATENCY.labels(request.method, request.url.path).observe(
        time.perf_counter() - start
    )
    REQUEST_COUNT.labels(request.method, request.url.path, response.status_code).inc()
    return response


@app.get("/metrics")
def metrics():
    """Serializes the in-memory counters/histograms for Prometheus to scrape.

    Why no auth here: only the Prometheus container (same internal compose
    network as session-service and other internal-only services) ever calls
    this — never nginx, never a client.
    """
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


# --- Request/response shapes ------------------------------------------------
class Credentials(BaseModel):
    """Register and login both take exactly an email + password."""

    email: str
    password: str


class TokenResponse(BaseModel):
    """What a successful register/login hands back to the client."""

    access_token: str
    token_type: str = "bearer"


# --- Helpers ----------------------------------------------------------------
def hash_password(plain: str) -> str:
    """Turn a plaintext password into a bcrypt hash for storage.

    Why bcrypt: it's a slow, salted hash, so a stolen DB can't be reversed with
    a fast lookup table. We call bcrypt directly rather than through passlib to
    avoid the known passlib/bcrypt-4.x version-detection warning.
    """
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Check a login attempt against the stored hash, in constant time."""
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def issue_token(user_id: str, email: str) -> str:
    """Mint a signed JWT whose `sub` is the user id.

    Why `sub` = user id: `/validate` reads it straight back out and hands it to
    nginx as X-User-Id, so the id in the token is the identity every downstream
    service trusts. `exp` bounds the damage window if a token leaks.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    payload = {
        "sub": user_id,
        "email": email,
        "exp": now + datetime.timedelta(minutes=JWT_EXPIRE_MINUTES),
        "iat": now,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


# --- Endpoints --------------------------------------------------------------
# Routes are mounted under /auth/* because nginx's `location /auth` forwards the
# path unchanged (so the gateway delivers /auth/register here). /validate is the
# exception: nginx's internal auth_request rewrites it to a bare /validate.


@app.post("/auth/register", response_model=TokenResponse, status_code=201)
def register(creds: Credentials):
    """Create a new account and log the user straight in.

    Why return a token here (not just 201): it lets the frontend register and
    land the user in the app in one round-trip instead of forcing an immediate
    second login call.
    """
    db = SessionLocal()
    try:
        # Reject duplicate emails up front so the DB unique constraint isn't the
        # thing surfacing the error (which would be an opaque 500).
        if db.query(User).filter(User.email == creds.email).first():
            raise HTTPException(status_code=409, detail="Email already registered")

        user = User(
            id=str(uuid.uuid4()),
            email=creds.email,
            password_hash=hash_password(creds.password),
        )
        db.add(user)
        db.commit()
        return TokenResponse(access_token=issue_token(user.id, user.email))
    finally:
        db.close()


@app.post("/auth/login", response_model=TokenResponse)
def login(creds: Credentials):
    """Verify credentials and issue a fresh JWT.

    Why one generic 401 for both "no such email" and "wrong password": telling
    an attacker which of the two failed leaks whether an email is registered.
    """
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == creds.email).first()
        if not user or not verify_password(creds.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Invalid email or password")
        LOGIN_COUNT.inc()  # business metric: a real login just happened
        return TokenResponse(access_token=issue_token(user.id, user.email))
    finally:
        db.close()


@app.get("/validate")
def validate(response: Response, authorization: str = Header(default=None)):
    """The endpoint nginx's `auth_request` calls before every protected route.

    Why the id goes in a *response header*: nginx can't read a JSON body from a
    subrequest, but it can capture a response header via `auth_request_set`.
    Putting the id on `X-User-Id` is the whole hinge of the auth model — nginx
    grabs it here and forwards it to the upstream, so downstream services never
    touch the token themselves. Any failure is a 401, which nginx turns into a
    401 for the original client.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")

    token = authorization.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        # Expired, tampered, wrong-secret — all indistinguishable to a client.
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token missing subject")

    # The one line the whole gateway trust model depends on.
    response.headers["X-User-Id"] = user_id
    return {"user_id": user_id}


@app.get("/health")
def health():
    """Liveness probe so compose/other tooling can tell the app is up."""
    return {"status": "ok"}
