"""
rag — chunks and embeds README.md, and retrieves relevant chunks per
question. The chatbot's RAG-over-docs half; unrelated to mem0's long-term
memory (memory.py), which needs *an* embedding model too but for a
completely different purpose (see memory.py's module docstring).
"""

import re  # markdown-heading chunking

from fastembed import TextEmbedding

from config import README_PATH
from models import SessionLocal, DocChunk

RETRIEVAL_TOP_K = 4  # generous for a corpus this small (a handful of README sections) — see DocChunk's docstring

# Loads fastembed's default small model once, at import time, and reuses it
# for every embed call below — the model load itself is the slow part, not
# embedding a handful of chunks or a single question.
_embedder = TextEmbedding()


def chunk_readme(readme_text: str) -> list[str]:
    """Split README.md into chunks along markdown headings.

    Why headings, not a fixed character window: this repo's README is
    already organized into meaningful sections (Architecture, Services,
    Running it, ...). Splitting on heading boundaries keeps each chunk one
    coherent topic instead of an arbitrary mid-paragraph cut — what actually
    matters for retrieval quality at this corpus size (a handful of chunks,
    not thousands, so there's no volume-driven reason to chunk any finer).
    """
    # Split right before any line starting with 1-6 `#` characters, so the
    # heading stays attached to the section text that follows it.
    parts = re.split(r"\n(?=#{1,6} )", readme_text)
    return [p.strip() for p in parts if p.strip()]


def embed_readme() -> None:
    """Re-embed README.md into doc_chunks. Called once by main.py at import
    time.

    Clears the table first rather than diffing against the previous run —
    see DocChunk's docstring for why that's the right tradeoff at this
    corpus size.
    """
    with open(README_PATH, "r", encoding="utf-8") as f:
        readme_text = f.read()

    chunks = chunk_readme(readme_text)
    vectors = _embedder.embed(chunks)  # generator of one embedding array per input chunk

    db = SessionLocal()
    try:
        db.query(DocChunk).delete()
        for chunk, vector in zip(chunks, vectors):
            db.add(DocChunk(source="README.md", chunk_text=chunk, embedding=vector.tolist()))
        db.commit()
    finally:
        db.close()


def retrieve_context(question: str) -> str:
    """The top-K README chunks most relevant to this question, joined into
    one block of text for the model's context. Plain cosine distance, no
    ANN index — see DocChunk's docstring for why that's the right call at
    this corpus size (plan decision #2).
    """
    query_vector = list(_embedder.embed([question]))[0].tolist()
    db = SessionLocal()
    try:
        chunks = (
            db.query(DocChunk)
            .order_by(DocChunk.embedding.cosine_distance(query_vector))
            .limit(RETRIEVAL_TOP_K)
            .all()
        )
        return "\n\n---\n\n".join(c.chunk_text for c in chunks)
    finally:
        db.close()
