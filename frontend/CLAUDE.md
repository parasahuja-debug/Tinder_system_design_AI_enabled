# frontend

Angular app, one page per feature (repo `CLAUDE.md`'s convention), behind
`authGuard` except Login/Register. Talks only to the gateway (`:8080` in
prod, proxied through the dev server on `:4200`) — never to a backend
service directly, same rule every backend service follows for each other.

## Structure & pattern
- One directory per page under `src/app/<page>/` (`home/`, `discover/`,
  `matches/`, `chat/`, `login/`, `register/`), each a standalone component,
  lazy-loaded via `loadComponent` in `app.routes.ts`.
- One `*.service.ts` per backend service it talks to (`auth.service.ts`,
  `profile.service.ts`, `discovery.service.ts`, `chat.service.ts`) — pages
  read/write through these, never call `HttpClient` directly, so a route
  path or response shape only needs to change in one place.
- Local component state is `readonly signal<T>`, not a state-management
  library — this app has no cross-page shared state beyond the JWT
  (`AuthService`), so signals scoped to each component are enough.
- Real forms use `ReactiveFormsModule` (`FormBuilder.nonNullable.group`).
  Always `inject()`, never constructor injection — a component's field
  initializers (e.g. building `form`) run *before* the constructor body, so
  a constructor-injected dependency would still be `undefined` when a field
  initializer needed it (TS2729).

## Auth
- `auth.service.ts` owns the JWT lifecycle: stores it in `localStorage`
  (`tinder_access_token`), exposes `isLoggedIn` (a signal, seeded from
  storage so a page refresh doesn't force a re-login) and `getToken()`.
- `auth.interceptor.ts` attaches `Authorization: Bearer <token>` to every
  outgoing `HttpClient` request automatically — pages never do this
  themselves.
- `auth.guard.ts` (`authGuard`) is a **UX convenience only**, not the real
  security boundary — it just avoids rendering a page that would
  immediately fail its API calls. The gateway's `auth_request` is the actual
  boundary; a stolen/expired token still gets a 401 from the API even if
  this guard is bypassed.
- **The one exception**: `direct_msg`'s chat WebSocket can't carry an
  `Authorization` header at all (browsers won't allow it on a WS handshake),
  so `chat.service.ts`'s `connect()` offers the token via the WebSocket
  subprotocol list instead (`new WebSocket(url, ['bearer', token])`) —
  bypasses the interceptor entirely. See `direct_msg/main.py`'s module
  docstring for the server side of this.

## Routing
- `app.routes.ts` — one route per page, `canActivate: [authGuard]` on every
  protected one.
- Route paths that take a URL param (e.g. `/chat/:matchId`) can collide with
  an API prefix that starts the same way — see the proxy gotcha below,
  which is exactly this collision.

## Dev proxy (`proxy.conf.json`)
- Forwards backend paths from `:4200` to the gateway on `:8080` so the
  browser only ever sees one origin — the alternative (CORS headers at the
  gateway) was rejected on Day 1 in favor of keeping the browser same-origin.
- **Only read at `ng serve` startup, never hot-reloaded.** Editing this file
  while the dev server is already running does nothing until it's
  restarted — bit us on Day 4 (added a `/chat` entry, kept testing against
  the already-running server, watched it silently fall through to serving
  `index.html` instead of proxying).
- **Keep each entry as narrow as the real API path, not just the top
  segment.** A blanket `/chat` entry also intercepts a hard navigation/reload
  of the Angular page route `/chat/:matchId` itself (any direct browser
  request to a path starting with `/chat`, not just `HttpClient` calls) —
  nginx then 404s because neither `/chat/ws` nor `/chat/history` matches a
  bare `/chat/<uuid>`. Fixed by using the literal API prefixes
  (`/chat/ws`, `/chat/history`) instead of `/chat`. This only works because
  match ids are UUIDs (hex + dashes) and can never literally start with
  `ws` or `history` — worth remembering if a future page route and API
  prefix share a first segment again.

## Styling
- Single global `src/styles.css` — no per-component stylesheets.
- CSS custom properties at `:root`: `--tinder-pink`, `--tinder-orange`,
  `--tinder-gradient`, `--text-dark`, `--text-muted`, `--border-light`. Reuse
  these rather than hardcoding colors.
- Each page's rules are marked with a section-banner comment
  (`/* --- Discover (swipe deck) --- */`, `/* --- Matches (list) --- */`,
  `/* --- Chat (messages) --- */`) — add one when adding a new page's
  styles, so the file stays navigable as it grows.
- `app-brand-mark`: `variant="full"` (icon + name + tagline, centered —
  Login/Register) vs `variant="compact"` (small icon + name inline —
  functional pages: Home, Discover, Matches, Chat). When the brand block
  already supplies a page's visual context, its literal heading (`<h1>`) can
  be `.sr-only` (visually hidden, still screen-reader-visible) instead of a
  redundant second heading.

## Images
- Never a bare `<img src="/images/id">` — the gateway requires a Bearer
  token an `<img>` tag has no way to send. Fetch via
  `ProfileService.getImageBlob()` (`responseType: 'blob'`, goes through the
  interceptor like any other authenticated call) and bind the template to
  `URL.createObjectURL(blob)` instead. Always revoke every object URL created
  this way in `ngOnDestroy` — otherwise each one stays pinned in browser
  memory for the life of the tab, not just the component.

## Run standalone
```bash
cd frontend
npm install
npm start   # ng serve, http://localhost:4200
```
`/login` and `/register` render without the backend. Everything else needs
the full stack up (`docker compose up -d` from the repo root) — including a
page load of `/` itself, which calls `GET /profile`.

## Testing
`npm test` (`ng test`) — the repo's `/test` slash command runs this
automatically when invoked from inside `frontend/`.

## Verifying UI changes
`.claude/skills/run-tinder/` — a Playwright-driven headless-Chromium REPL for
driving the app without a human at a browser (navigate, fill forms, click,
screenshot, read console errors). Used to verify every page in this app
end-to-end, not just check that the code compiles. See its own `SKILL.md`
for the full command reference and known gotchas (reactive forms need
`fill`, not raw DOM `.value =`; `wait-url` matches the exact pathname, not a
substring).
