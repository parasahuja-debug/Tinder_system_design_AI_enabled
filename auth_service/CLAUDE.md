# auth_service

Issues and verifies JWTs; owns user credentials. This is the only service that
knows `JWT_SECRET`. nginx calls `/validate` before every protected route and
forwards the resulting `X-User-Id` to the upstream — downstream services trust
that header and never see the token.

## Endpoints
- `POST /auth/register` `{email, password}` → `201 {access_token}` (also logs in)
- `POST /auth/login` `{email, password}` → `200 {access_token}` / `401`
- `GET /validate` (Bearer token) → `200` with `X-User-Id` **response header** / `401`
- `GET /health` → `{status: ok}`

Paths are `/auth/*` because nginx's `location /auth` forwards the path unchanged;
`/validate` is bare because the internal `auth_request` rewrites it.

## Table (in shared DB)
`users(id uuid PK, email unique, password_hash)` — created on startup via
`Base.metadata.create_all`. Passwords stored as bcrypt hashes, never plaintext.

## Env
`DATABASE_URL`, `JWT_SECRET` (required); `JWT_ALGORITHM` (default HS256),
`JWT_EXPIRE_MINUTES` (default 1440).

## Run standalone
```
pip install -r requirements.txt
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres \
JWT_SECRET=dev-secret uvicorn main:app --port 8002
# register: curl -XPOST localhost:8002/auth/register -H 'content-type: application/json' -d '{"email":"a@b.c","password":"pw"}'
```
