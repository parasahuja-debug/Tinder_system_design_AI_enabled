"""
matcher_service — owns swipe decisions and match detection.

Why this service exists: "did user A like user B" and "did A and B mutually
like each other" is a distinct concern from profile data (profile_service)
and candidate ranking (recommendation_service) — this service is the single
place that records a swipe and is the only place a match row can be created,
so match creation can never race or duplicate across services.
It never verifies a JWT itself; it trusts the X-User-Id header set by nginx
only after auth_service's /validate succeeds, same as every other protected
service (see CLAUDE.md's auth model).
"""

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, String, DateTime, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import func
import os
import uuid

DATABASE_URL = os.environ["DATABASE_URL"]

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

Base = declarative_base()


class Swipe(Base):
    """One row per (swiper, target) pair — the swiper's current decision on the target.

    Why the pair itself is the primary key, not a generated uuid: a swipe is
    inherently one decision per pair (you can't like AND pass the same
    profile at once), so reusing the natural key as the PK makes the DB
    enforce "at most one decision per pair" for free — same reasoning
    profile_service used to reuse the user id as its PK instead of a
    generated surrogate. A re-swipe overwrites the row rather than creating
    a second one.
    """

    __tablename__ = "swipes"

    swiper_id = Column(String, primary_key=True)  # the user performing the swipe (the actor)
    target_id = Column(String, primary_key=True)  # the profile being swiped on (the passive party, shown as a card)
    direction = Column(String, nullable=False)  # "like" or "pass"
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Match(Base):
    """One row per mutual-like pair, created the moment the second "like" lands.

    Why a generated uuid `id` here (unlike Swipe above): a match needs its
    own identity independent of the two user ids, because Day 4's direct_msg
    service keys a chat thread off a match id, not off a pair of user ids.
    `id` is a plain surrogate row key — it identifies the row, not either
    participant.
    user_a_id/user_b_id are stored in canonical order (lexicographically
    smaller id first) so a mutual like is always exactly one row regardless
    of which of the two users' swipe triggered it — without the ordering,
    "A matched B" and "B matched A" could each insert their own row for the
    same pair.
    """

    __tablename__ = "matches"
    __table_args__ = (UniqueConstraint("user_a_id", "user_b_id", name="uq_match_pair"),)

    id = Column(String, primary_key=True, index=True)
    # Ordering here is alphabetical, not "who swiped first" — so a given user
    # can land in EITHER column depending on how their id compares to the
    # other person's. Looking up "my matches" therefore can't filter on just
    # one column; it must check both and pick whichever isn't the caller
    # (see list_matches below).
    user_a_id = Column(String, nullable=False, index=True)
    user_b_id = Column(String, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


Base.metadata.create_all(bind=engine)

app = FastAPI()


class SwipeRequest(BaseModel):
    # No swiper id field on purpose — per the auth model, identity always
    # comes from the gateway's X-User-Id header, never from the body.
    target_id: str
    direction: str  # "like" or "pass"


def get_user_id(x_user_id: str = Header(default=None)) -> str:
    """Shared guard: every route below needs the authenticated caller's id."""
    if not x_user_id:
        raise HTTPException(status_code=401, detail="Missing X-User-Id from gateway")
    return x_user_id


@app.post("/swipe", status_code=201)
def record_swipe(swipe: SwipeRequest, x_user_id: str = Header(default=None)):
    """Record the caller's swipe decision on a target profile, then check for a mutual match.

    Why the match check happens inline here rather than as a separate async
    step: match creation must never race (two near-simultaneous "like"
    swipes on each other must produce exactly one match row, not zero or
    two), and the simplest way to guarantee that without extra
    infrastructure is to do the check-and-insert inside the same request
    that just wrote the second swipe, inside one DB transaction.
    """
    user_id = get_user_id(x_user_id)

    # Reject junk input before touching the DB at all.
    if swipe.direction not in ("like", "pass"):
        raise HTTPException(status_code=400, detail="direction must be 'like' or 'pass'")
    if swipe.target_id == user_id:
        raise HTTPException(status_code=400, detail="Cannot swipe on yourself")

    db = SessionLocal()
    try:
        # Step 1 — record (or overwrite) this user's decision on the target.
        # Look up whether this exact (swiper, target) pair already has a row
        # — the composite PK means there can be at most one.
        existing = (
            db.query(Swipe)
            .filter(Swipe.swiper_id == user_id, Swipe.target_id == swipe.target_id)
            .first()
        )
        if existing:
            existing.direction = swipe.direction  # re-swipe: overwrite the prior decision (e.g. pass -> like)
        else:
            db.add(Swipe(swiper_id=user_id, target_id=swipe.target_id, direction=swipe.direction))

        # Step 2 — only a "like" can ever create a match. A "pass" is fully
        # handled by step 1 above; nothing further to check.
        matched = False
        if swipe.direction == "like":
            # Step 2a — has the target already liked this user back? Check
            # for that one specific row rather than scanning all of the
            # target's swipes, since (swiper_id, target_id) is indexed as
            # the PK either way.
            reverse_like = (
                db.query(Swipe)
                .filter(
                    Swipe.swiper_id == swipe.target_id,
                    Swipe.target_id == user_id,
                    Swipe.direction == "like",
                )
                .first()
            )
            if reverse_like:
                # Step 2b — mutual like confirmed. Put the pair in canonical
                # (alphabetical) order — same convention the Match model's
                # columns use — so both directions of "who swiped last" land
                # on the same lookup.
                user_a_id, user_b_id = sorted([user_id, swipe.target_id])
                # Guard against a duplicate row: if this pair was already
                # matched (e.g. this is a re-swipe replaying an old "like"
                # after an earlier "pass"), don't insert a second match.
                already_matched = (
                    db.query(Match)
                    .filter(Match.user_a_id == user_a_id, Match.user_b_id == user_b_id)
                    .first()
                )
                if not already_matched:
                    db.add(Match(id=str(uuid.uuid4()), user_a_id=user_a_id, user_b_id=user_b_id))
                    matched = True

        # Commits the swipe write and (if step 2b inserted one) the new
        # match row together, in one transaction — see the docstring above
        # for why that atomicity matters.
        db.commit()
        # `matched` lets the frontend show the "It's a match!" moment right
        # away, instead of the caller having to separately poll /matches.
        return {"message": "Swipe recorded", "matched": matched}
    finally:
        db.close()


@app.get("/matches")
def list_matches(x_user_id: str = Header(default=None)):
    """List every match the caller is part of, newest first.

    Returns the other user's id per row (not the caller's own id back) since
    the frontend only ever needs "who am I matched with", never "am I in
    this match" (the route is already scoped to the caller via X-User-Id).
    """
    user_id = get_user_id(x_user_id)
    db = SessionLocal()
    try:
        # OR across both columns — per the Match model's note above, the
        # caller could be stored as either user_a_id or user_b_id depending
        # on alphabetical order, not on who swiped first.
        matches = (
            db.query(Match)
            .filter((Match.user_a_id == user_id) | (Match.user_b_id == user_id))
            .order_by(Match.created_at.desc())
            .all()
        )
        return [
            {
                "match_id": m.id,
                # Whichever column isn't the caller's own id is "the other
                # person" — this is the ternary the model docstring pointed to.
                "other_user_id": m.user_b_id if m.user_a_id == user_id else m.user_a_id,
                "created_at": m.created_at,
            }
            for m in matches
        ]
    finally:
        db.close()


@app.get("/matches/{match_id}")
def get_match(match_id: str, user_id: str):
    """Look up one match by id and confirm a given user is a participant.

    Why this is different from every other endpoint in this file: it's not
    reached through the gateway, so there's no X-User-Id header set by
    auth_request — the only caller is direct_msg, calling this directly over
    the compose-internal network right when a chat WebSocket connects, after
    it has already resolved the caller's real user_id itself (see
    direct_msg/main.py's module docstring for how). That's why user_id
    arrives as a plain query param here instead of the trusted header every
    gateway-facing route uses.

    Why direct_msg needs this at all: without it, anyone who obtains a
    match_id (it's just a UUID in a URL) could open a chat WebSocket into a
    conversation they were never part of. This is the one-time check, at
    connection time only, that the caller is actually one of the two people
    this match belongs to — not re-checked per message, since matches don't
    get revoked mid-conversation in this build.
    """
    db = SessionLocal()
    try:
        match = db.query(Match).filter(Match.id == match_id).first()
        if not match:
            raise HTTPException(status_code=404, detail="No such match")
        if user_id not in (match.user_a_id, match.user_b_id):
            # Deliberately the same 403 regardless of *why* — either match_id
            # is real but belongs to two other people, or it's a typo'd id.
            # direct_msg only needs "can this caller use this chat thread?",
            # not a diagnosis of which case it is.
            raise HTTPException(status_code=403, detail="Not a participant in this match")
        return {"match_id": match.id, "user_a_id": match.user_a_id, "user_b_id": match.user_b_id}
    finally:
        db.close()
