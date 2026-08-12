"""
profile_service — owns profile data (name/age/gender/city/lat/long/bio).

Why this service exists: profile data is a distinct concern from auth
(credentials, owned by auth_service) and images (binary files, owned by
image_service) — this service owns exactly the text/numeric fields a user
fills in about themselves, keyed 1:1 to the user id auth_service issued.
It never verifies a JWT itself; it trusts the X-User-Id header set by nginx
only after auth_service's /validate succeeds, because only the gateway can
reach this service directly (see CLAUDE.md's auth model).
"""

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, String, Integer, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
# 2026-08-12: unused now that POST /profile (below) keys rows off X-User-Id
# instead of a generated uuid — see the commented-out old /create-profile route.
# import uuid

# 2026-08-09: replaced the hardcoded localhost DB URL with an env-driven one.
# Reason: inside docker-compose the Postgres host is `db`, not `localhost`, so
# the literal below can never connect in the real deployment. Reading
# DATABASE_URL from the environment is the pattern every service in this repo
# follows. Old line kept commented per the standing rule.
# DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/postgres"
DATABASE_URL = os.environ["DATABASE_URL"]

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

Base = declarative_base()

class Profile(Base):
    """One row per user's profile — 1:1 with a row in auth_service's `users` table.

    Why `id` is the user id (not a generated uuid): the relationship is
    inherently one-profile-per-user, so reusing X-User-Id as the primary key
    does two things at once — it's the join key back to auth_service's users
    table, and it makes the database itself enforce "at most one profile per
    user" via the PK constraint, so application code doesn't need a separate
    uniqueness check.
    """

    __tablename__ = "profiles"

    id = Column(String, primary_key=True, index=True)  # = the user's id from auth_service
    name = Column(String, nullable=False)
    age = Column(Integer, nullable=False)
    gender = Column(String, nullable=False)  # feeds Day 3's recommendation filter
    state = Column(String, nullable=False)  # Indian state — two states can share a city name, so this is stored separately, not folded into city
    city = Column(String, nullable=False)
    lat = Column(Float, nullable=False)   # feeds Day 3's bounding-box candidate query
    long = Column(Float, nullable=False)  # feeds Day 3's bounding-box candidate query
    bio = Column(String, nullable=False)

Base.metadata.create_all(bind=engine)

app = FastAPI()

class ProfileRequest(BaseModel):
    # No `id`/`user_id` field here on purpose — per the auth model, identity
    # always comes from the gateway's X-User-Id header, never from the body.
    name: str
    age: int
    gender: str
    state: str
    city: str
    lat: float
    long: float
    bio: str

def get_user_id(x_user_id: str = Header(default=None)) -> str:
    """Shared guard: every route below needs the authenticated caller's id.

    Why a helper instead of repeating this in each route: the "no header =>
    401" check is one rule, not three — this is the one place to change if
    the auth model ever changes.
    """
    if not x_user_id:
        raise HTTPException(status_code=401, detail="Missing X-User-Id from gateway")
    return x_user_id


# 2026-08-12: replaced — this route generated its own random id and never
# checked X-User-Id, so (a) nginx's `location /profile` could never reach it,
# since the path didn't match `/create-profile`, and (b) profiles had no real
# owner. Superseded by POST /profile below. Kept for history per standing rule:
# @app.post("/create-profile")
# def create_profile(profile: ProfileRequest):
#     db = SessionLocal()
#
#     new_profile = Profile(
#         id=str(uuid.uuid4()),
#         name=profile.name,
#         age=profile.age,
#         city=profile.city,
#         bio=profile.bio
#     )
#
#     db.add(new_profile)
#     db.commit()
#
#     return {"message": "Profile created"}


@app.post("/profile", status_code=201)
def create_profile(profile: ProfileRequest, x_user_id: str = Header(default=None)):
    """Create the authenticated user's profile.

    Why check-then-409 instead of letting the DB reject it: id is the PK, so a
    second insert for the same user would otherwise surface as an opaque DB
    IntegrityError/500. Checking up front turns that into a clear, expected
    error — same pattern as auth_service's duplicate-email guard.
    """
    user_id = get_user_id(x_user_id)
    db = SessionLocal()
    try:
        if db.query(Profile).filter(Profile.id == user_id).first():
            raise HTTPException(status_code=409, detail="Profile already exists")

        new_profile = Profile(
            id=user_id,
            name=profile.name,
            age=profile.age,
            gender=profile.gender,
            state=profile.state,
            city=profile.city,
            lat=profile.lat,
            long=profile.long,
            bio=profile.bio,
        )
        db.add(new_profile)
        db.commit()
        return {"message": "Profile created", "user_id": user_id}
    finally:
        db.close()


# 2026-08-12: replaced — this was the Day 1 verification stub that just
# echoed X-User-Id back without touching the DB, to prove the gateway's auth
# handoff worked. That's confirmed now; superseded by the real lookup below.
# Kept for history per standing rule:
# @app.get("/profile")
# def get_profile(x_user_id: str = Header(default=None)):
#     if not x_user_id:
#         raise HTTPException(status_code=401, detail="Missing X-User-Id from gateway")
#     return {"user_id": x_user_id, "message": "authenticated request reached profile_service"}


@app.get("/profile")
def get_profile(x_user_id: str = Header(default=None)):
    """Fetch the authenticated user's own profile."""
    user_id = get_user_id(x_user_id)
    db = SessionLocal()
    try:
        profile = db.query(Profile).filter(Profile.id == user_id).first()
        if not profile:
            raise HTTPException(status_code=404, detail="No profile yet for this user")
        return {
            "user_id": profile.id,
            "name": profile.name,
            "age": profile.age,
            "gender": profile.gender,
            "state": profile.state,
            "city": profile.city,
            "lat": profile.lat,
            "long": profile.long,
            "bio": profile.bio,
        }
    finally:
        db.close()


@app.put("/profile")
def update_profile(profile: ProfileRequest, x_user_id: str = Header(default=None)):
    """Edit the authenticated user's existing profile (full replace of the editable fields)."""
    user_id = get_user_id(x_user_id)
    db = SessionLocal()
    try:
        existing = db.query(Profile).filter(Profile.id == user_id).first()
        if not existing:
            raise HTTPException(status_code=404, detail="No profile yet for this user")

        existing.name = profile.name
        existing.age = profile.age
        existing.gender = profile.gender
        existing.state = profile.state
        existing.city = profile.city
        existing.lat = profile.lat
        existing.long = profile.long
        existing.bio = profile.bio
        db.commit()
        return {"message": "Profile updated", "user_id": user_id}
    finally:
        db.close()
