"""
image_service — owns uploaded profile images (binary files on disk + a
Postgres row per image).

Why this service exists: image data is a different kind of thing than
profile text (auth_service owns credentials, profile_service owns
name/age/bio/etc) — it's a binary blob that belongs on disk, not in a
database column, plus a disk-write path and per-user limits that don't apply
to any other service. Like every other backend service, it never verifies a
JWT itself: it trusts the X-User-Id header set by nginx only after
auth_service's /validate succeeds, because only the gateway can reach this
service directly (see CLAUDE.md's auth model).
"""

from fastapi import FastAPI, Header, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy import create_engine, Column, String, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
import uuid

# --- Configuration from the environment, never hardcoded -------------------
# Same pattern as auth_service/profile_service: inside docker-compose the DB
# host is `db`, not `localhost`.
DATABASE_URL = os.environ["DATABASE_URL"]

# Where uploaded files live *inside the container*. docker-compose mounts the
# repo's image_store/ directory here, so files also show up on the host at
# ./image_store/, matching the repo layout doc in CLAUDE.md.
IMAGE_STORE_DIR = os.environ.get("IMAGE_STORE_DIR", "/app/image_store")

# Product rule from the build plan: at most 5 images per user. Also doubles
# as a bound on per-user disk usage.
MAX_IMAGES_PER_USER = 5

# Size cap per upload (5MB). Without this, a single upload could be
# arbitrarily large — exhausts disk, ties up the request. We reject oversize
# uploads rather than compress/resize them server-side, since resizing needs
# an image-processing library that's out of scope this week. nginx has its
# own default body-size cap (1MB) that would reject a >1MB upload before it
# even reaches here — that gets raised to match when the nginx route is added.
MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024

# Only these extensions are ever written to disk. Standard web-safe raster
# formats every browser renders natively. Deliberately excludes .svg (SVG is
# XML and can embed <script> — a known stored-XSS vector if ever rendered)
# and .heic (most browsers can't render it without server-side conversion,
# which is out of scope this week). Known limitation: this only checks the
# extension, not the actual file content/magic bytes — good enough for a
# local build, not a substitute for content validation in production.
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

Base = declarative_base()


class Image(Base):
    """One row per uploaded image file — 1:many with a user (up to
    MAX_IMAGES_PER_USER), unlike Profile which is 1:1.

    Why `id` is a generated uuid, not the user id: since the relationship is
    1:many, there's no single "the" image per user to reuse as a key — a
    surrogate key is required here, unlike Profile.id.
    """

    __tablename__ = "images"
    __table_args__ = (
        # A real DB constraint, not just an app-level check — unlike the
        # image-count cap above (a race condition there is an accepted gap),
        # "no two rows with the same (user, filename)" is exactly what a
        # uniqueness constraint enforces for real, closing the race a
        # check-then-insert alone can't.
        UniqueConstraint("profile_id", "original_filename", name="uq_profile_filename"),
    )

    id = Column(String, primary_key=True, index=True)  # surrogate key; also becomes the on-disk filename stem
    profile_id = Column(String, nullable=False, index=True)  # = X-User-Id; explicit index because "list/count this user's images" is the real query pattern, not point lookup by id
    original_filename = Column(String, nullable=False)  # the name the client uploaded it as — used to reject re-uploading a same-named file
    extension = Column(String, nullable=False)  # e.g. ".jpg" — needed to reconstruct the on-disk path
    url = Column(String, nullable=False)  # path the client fetches this image at, e.g. /images/<id>


# Create our own table on startup — same build-week convention as every other
# service (Alembic is backlog).
Base.metadata.create_all(bind=engine)

# Make sure the on-disk storage root exists before any upload tries to write
# into it. On a fresh volume/first run this directory doesn't exist yet;
# exist_ok=True makes this a no-op on every later restart.
os.makedirs(IMAGE_STORE_DIR, exist_ok=True)

app = FastAPI(title="image_service")


def get_user_id(x_user_id: str = Header(default=None)) -> str:
    """Shared guard: every route below needs the authenticated caller's id.

    Duplicated from profile_service rather than imported — these are
    independently deployable services with no shared package between them;
    a 4-line guard isn't worth introducing real coupling to deduplicate.
    """
    if not x_user_id:
        raise HTTPException(status_code=401, detail="Missing X-User-Id from gateway")
    return x_user_id


@app.post("/images", status_code=201)
def upload_image(file: UploadFile = File(...), x_user_id: str = Header(default=None)):
    """Upload one image for the authenticated user.

    Order: auth guard -> extension check -> cap check -> size check (all
    before any disk I/O, so a rejected upload never touches the filesystem)
    -> write to disk -> record in DB. If the DB insert fails after the file
    write succeeds, the except below deletes the orphan file (a compensating
    action, not a real transaction — a crash in the exact instant between
    the write and this except could still leave one, but this closes the
    common case of a DB error).
    """
    user_id = get_user_id(x_user_id)

    original_filename = file.filename or "upload"
    _, ext = os.path.splitext(original_filename)
    ext = ext.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext or 'unknown'}")

    db = SessionLocal()
    try:
        # Cap check before any disk I/O. Known gap: two concurrent uploads
        # could both pass this check before either commits (race condition)
        # — not solved here, real complexity for an unlikely case this week.
        existing_count = db.query(Image).filter(Image.profile_id == user_id).count()
        if existing_count >= MAX_IMAGES_PER_USER:
            raise HTTPException(
                status_code=400,
                detail=f"Image limit reached ({MAX_IMAGES_PER_USER} max)",
            )

        # Pre-emptive check for a clear, specific error message. The
        # UniqueConstraint on the model is the real backstop against a
        # concurrent-upload race — this check is just what makes the common
        # (non-race) case return a clean 409 instead of a raw DB error.
        duplicate = (
            db.query(Image)
            .filter(Image.profile_id == user_id, Image.original_filename == original_filename)
            .first()
        )
        if duplicate:
            raise HTTPException(
                status_code=409,
                detail=f"You've already uploaded a file named '{original_filename}'. Rename it or choose a different photo.",
            )

        contents = file.file.read()
        if len(contents) > MAX_FILE_SIZE_BYTES:
            raise HTTPException(status_code=400, detail="File too large (max 5MB)")

        image_id = str(uuid.uuid4())
        user_dir = os.path.join(IMAGE_STORE_DIR, user_id)
        os.makedirs(user_dir, exist_ok=True)
        file_path = os.path.join(user_dir, f"{image_id}{ext}")
        with open(file_path, "wb") as f:
            f.write(contents)

        try:
            new_image = Image(
                id=image_id,
                profile_id=user_id,
                original_filename=original_filename,
                extension=ext,
                url=f"/images/{image_id}",
            )
            db.add(new_image)
            db.commit()
        except Exception:
            os.remove(file_path)  # compensating action — see docstring
            raise

        return {"image_id": image_id, "url": new_image.url, "original_filename": original_filename}
    finally:
        db.close()


@app.get("/images")
def list_images(x_user_id: str = Header(default=None)):
    """List the authenticated user's own images — the query the profile_id
    index (on the Image model) exists to keep fast."""
    user_id = get_user_id(x_user_id)
    db = SessionLocal()
    try:
        images = db.query(Image).filter(Image.profile_id == user_id).all()
        return [
            {"image_id": img.id, "url": img.url, "original_filename": img.original_filename}
            for img in images
        ]
    finally:
        db.close()


@app.get("/images/user/{user_id}")
def list_images_for_user(user_id: str, x_user_id: str = Header(default=None)):
    """List another user's images — used once two users are matched, so
    each side can render the other's photos on the Matches page. Requires
    being authenticated (X-User-Id present) but not ownership, same policy
    shift as GET /images/{image_id} below (view any, edit/upload only your
    own). Two path segments after /images ("user" + the id) mean this never
    collides with GET /images/{image_id} below regardless of declaration
    order — that route only ever matches exactly one segment.
    """
    get_user_id(x_user_id)
    db = SessionLocal()
    try:
        images = db.query(Image).filter(Image.profile_id == user_id).all()
        return [
            {"image_id": img.id, "url": img.url, "original_filename": img.original_filename}
            for img in images
        ]
    finally:
        db.close()


@app.get("/images/{image_id}")
def get_image_file(image_id: str, x_user_id: str = Header(default=None)):
    """Serve the raw bytes of one image, to any authenticated caller. This is
    what a browser's <img src="/images/<id>"> tag actually hits to render a
    thumbnail — GET /images only ever returns metadata (ids + urls), never
    the pixel data itself.

    Always checks the DB for a matching row before touching disk — never
    just "does a file exist at this path". That still closes the orphan-file
    case (a failed upload leaves a file with no DB row, so it can never be
    served) even though ownership is no longer checked here.
    """
    get_user_id(x_user_id)  # still requires a logged-in caller; just no longer requires ownership
    db = SessionLocal()
    try:
        # 2026-08-13: replaced — this used to also filter on
        # `Image.profile_id == user_id`, so only the uploader could ever view
        # their own photo. That was right for the profile-edit page (Day 2's
        # only caller), but Day 3's Discover feed needs any logged-in user to
        # view a candidate's photos, not just their own. GET /images (list)
        # is unchanged and still owner-scoped — this is deliberately the one
        # place a photo becomes visible beyond its owner, once a profile is
        # live. Old query kept for history per standing rule:
        # image = (
        #     db.query(Image)
        #     .filter(Image.id == image_id, Image.profile_id == user_id)
        #     .first()
        # )
        image = db.query(Image).filter(Image.id == image_id).first()
        if not image:
            raise HTTPException(status_code=404, detail="Image not found")
        # Path is built from the image's actual owner (image.profile_id), not
        # the caller — the file lives under the owner's folder on disk
        # regardless of who's viewing it now.
        file_path = os.path.join(IMAGE_STORE_DIR, image.profile_id, f"{image.id}{image.extension}")
        return FileResponse(file_path)
    finally:
        db.close()
