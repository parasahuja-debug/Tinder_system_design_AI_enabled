from fastapi import FastAPI
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, String, Integer
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import uuid

DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/postgres"

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