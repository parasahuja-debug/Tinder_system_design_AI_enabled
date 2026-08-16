"""
models — this service's own tables in the shared tinder DB.

Same SQLAlchemy pattern every other service here uses (engine from
DATABASE_URL, Base.metadata.create_all() on startup) — the one addition is
enabling Postgres's `vector` extension first, since doc_chunks needs it and
each database has to CREATE EXTENSION once even though the pgvector/pgvector
image already ships the extension binary.
"""

from pgvector.sqlalchemy import Vector
from sqlalchemy import create_engine, text, Column, Integer, String, Text, DateTime, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from config import DATABASE_URL

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

Base = declarative_base()

EMBEDDING_DIM = 384  # fastembed's default model (BAAI/bge-small-en-v1.5) outputs 384-dim vectors


class DocChunk(Base):
    """One row per README.md chunk, with its embedding — the RAG corpus.

    Cleared and reinserted on every startup (see rag.embed_readme()):
    README.md is small enough that re-embedding from scratch each time is
    cheap, and it means doc_chunks can never drift out of sync with whatever
    the file currently says — no incremental-update/diffing logic needed.
    """

    __tablename__ = "doc_chunks"

    id = Column(Integer, primary_key=True)
    source = Column(String, nullable=False)  # always "README.md" for now — see plan decision #2
    chunk_text = Column(Text, nullable=False)
    embedding = Column(Vector(EMBEDDING_DIM), nullable=False)


class ChatbotMessage(Base):
    """One row per message sent during a support-chat WebSocket connection.

    Write-only from the widget's perspective — it never re-fetches a past
    session (plan decision #7). This table exists for three things: the
    working transcript fed to the model turn-by-turn within a still-open
    connection, our own audit/debugging trail, and the raw material handed
    to mem0 for summarization once that connection closes.
    """

    __tablename__ = "chatbot_messages"

    id = Column(Integer, primary_key=True)
    session_id = Column(String, nullable=False, index=True)  # fresh uuid4 per WebSocket connection
    user_id = Column(String, nullable=False)  # from X-User-Id, verified at connect time — see main.py's WS auth handshake
    role = Column(String, nullable=False)  # "user" | "assistant"
    message = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# pgvector's `vector` type has to exist in this database before create_all()
# can create a column of that type. The pgvector/pgvector image ships the
# extension binary, but each database still needs CREATE EXTENSION run once
# — this is exactly why Day 1 picked that image over stock postgres.
with engine.begin() as conn:
    conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

Base.metadata.create_all(bind=engine)
