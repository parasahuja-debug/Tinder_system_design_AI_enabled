from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, String, Integer
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
import uuid

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
    __tablename__ = "profiles"

    id = Column(String, primary_key=True, index=True)
    name = Column(String)
    age = Column(Integer)
    city = Column(String)
    bio = Column(String)

Base.metadata.create_all(bind=engine)

app = FastAPI()

class ProfileRequest(BaseModel):
    name: str
    age: int
    city: str
    bio: str

@app.post("/create-profile")
def create_profile(profile: ProfileRequest):
    db = SessionLocal()

    new_profile = Profile(
        id=str(uuid.uuid4()),
        name=profile.name,
        age=profile.age,
        city=profile.city,
        bio=profile.bio
    )

    db.add(new_profile)
    db.commit()

    return {"message": "Profile created"}


# Day 1 verification endpoint. Purpose: prove the gateway auth handoff works
# end-to-end. This service never verifies a JWT itself — it trusts X-User-Id,
# which nginx sets only after auth_service's /validate succeeded. If this route
# ever sees a request with no X-User-Id, the gateway wiring is broken (a client
# reached us without going through auth), so we 401 rather than guess an
# identity. Day 2 turns this into a real profile read keyed on that id.
@app.get("/profile")
def get_profile(x_user_id: str = Header(default=None)):
    if not x_user_id:
        raise HTTPException(status_code=401, detail="Missing X-User-Id from gateway")
    return {"user_id": x_user_id, "message": "authenticated request reached profile_service"}
