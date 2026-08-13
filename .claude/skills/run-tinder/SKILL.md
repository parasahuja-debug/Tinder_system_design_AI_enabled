---
name: run-tinder
description: Build, run, and drive the tinder frontend (Angular) against the live backend stack (docker compose). Use when asked to start the frontend, take a screenshot of a page, log in as a test user, or interact with the app's UI to verify a change.
---

The `frontend/` app is Angular, served via `ng serve` on :4200. Its
`proxy.conf.json` forwards API calls to the gateway on :8080, so the full
backend stack (`docker compose up`) must already be running for anything
beyond static pages (login/register) to work.

For agent/automated use, drive it via the Playwright REPL at
`.claude/skills/run-tinder/driver.mjs`. It's a plain headless-Chromium
driver (no xvfb needed — this runs on macOS, and headless Chromium needs no
display server there or on Linux).

All paths below are relative to the repo root.

## Prerequisites

```bash
cd .claude/skills/run-tinder
npm install
npx playwright install chromium
```

The backend stack must be up:

```bash
docker compose up -d
```

## Run (agent path)

```bash
# ensure the dev server is up (skip if already running):
cd frontend && nohup npm start > /tmp/ng-serve.log 2>&1 & disown
for i in $(seq 1 60); do curl -sf http://localhost:4200 >/dev/null 2>&1 && break; sleep 1; done

# drive it (from repo root):
node .claude/skills/run-tinder/driver.mjs <<'EOF'
launch
nav http://localhost:4200/login
wait app-brand-mark
ss login-page
quit
EOF
```

Screenshots land in `/tmp/tinder-shots/` (override: `SCREENSHOT_DIR`). One
node invocation processes its whole heredoc as a queue — each command
awaits full completion before the next runs (see Gotchas), so it's safe to
script a whole flow in one call rather than needing tmux for simple cases.
Use tmux + `send-keys`/`capture-pane` instead only for real iterative,
back-and-forth debugging.

### Commands

| command | what it does |
|---|---|
| `launch` | launch headless Chromium, open a page |
| `nav <url>` | navigate |
| `ss [name]` | screenshot → `/tmp/tinder-shots/<name>.png` |
| `click <css-sel>` | click element (via DOM, not coords) |
| `click-text <text>` | click button/link containing text |
| `fill <css-sel> <value>` | fill a form control (goes through Playwright's real input pipeline — see Gotchas) |
| `type <text>` / `press <key>` | keyboard input |
| `wait <css-sel>` | wait for element, 10s timeout |
| `wait-url <exact-pathname>` | wait for the URL's pathname to exactly equal this (see Gotchas — NOT substring) |
| `eval <js>` | evaluate in the page, print JSON |
| `text [css-sel]` | print innerText (body if no selector) |
| `quit` | close browser, exit |

Page console errors and uncaught exceptions print automatically
(`[console.error]` / `[pageerror]` prefix) as they happen — no separate
command needed; just watch the output after each `nav`/interaction.

### A full login flow (verified working)

```bash
node .claude/skills/run-tinder/driver.mjs <<'EOF'
launch
nav http://localhost:4200/login
wait app-brand-mark
fill input[formcontrolname="email"] someone@test.com
fill input[formcontrolname="password"] theirpassword
click-text Log in
wait-url /
wait .page-header
ss home
quit
EOF
```

Register a test user first via curl through the gateway if one doesn't
exist yet — see `fastapi-endpoint`'s SKILL.md / `auth_service/main.py` for
the exact request shape (`POST /auth/register` with `email`/`password`).

## Run (human path)

```bash
cd frontend && npm start   # opens on http://localhost:4200
```

## Gotchas

- **Piped/heredoc stdin fires `line` events for every line in one burst**,
  before the first async command (e.g. `launch`'s browser startup) has
  resolved. Without a queue, later commands would race ahead and hit a
  still-null `page`. The driver serializes all queued lines through one
  promise chain (`currentDrain`) so each command fully finishes before the
  next starts — this matters if you ever modify the driver, not just when
  using it.
- **readline self-closes the instant piped stdin hits EOF** — which happens
  right after the last line is delivered, well before the queued async
  commands actually finish. A naive `close` handler that calls
  `process.exit()` immediately will kill an in-flight command (this killed
  `chromium.launch()` mid-start the first time). The driver's `close`
  handler awaits the same `currentDrain` chain before exiting, and a
  `rlClosed` flag guards `rl.prompt()` calls from throwing
  `ERR_USE_AFTER_CLOSE` once the interface has already self-closed.
- **`wait-url` matches the exact pathname, not a substring.** An earlier
  version used `.includes(fragment)`, which is trivially true for every URL
  (every path contains `/`) — it reported success immediately while still
  sitting on `/login` mid "Logging in…", before the actual redirect to `/`
  had happened. Always pass the full exact pathname (e.g. `/`, `/register`),
  not a fragment to search for.
- **Angular reactive forms are controlled inputs.** A raw
  `el.value = '...'` DOM assignment (e.g. via `eval`) won't fire the events
  Angular's `FormControl` listens for, so the form never actually updates.
  Use the `fill` command — it goes through Playwright's real input pipeline
  (focus, keyboard/input events), which Angular picks up correctly.
- **The frontend needs the backend stack up** (`docker compose up -d`) for
  anything past static pages — `/login` and `/register` render without it,
  but submitting either, or loading `/` (which calls `GET /profile`), needs
  the gateway and its backend services reachable at :8080.
- **No geolocation permission in headless Chromium by default** — Home's
  profile form shows "Location access is needed..." unless the driver
  grants it (not yet implemented here; add
  `context.grantPermissions(['geolocation'], { origin: 'http://localhost:4200' })`
  plus `context.setGeolocation(...)` if a flow needs to get past this).

## Troubleshooting

- **`Port 4200 is already in use`:** a dev server is probably already
  running from an earlier session — check with
  `curl -sf http://localhost:4200` before starting a new one; reuse it
  instead of erroring out.
- **`timeout: command not found`:** this is macOS, not Linux — no GNU
  `timeout` by default. Use a manual `for i in $(seq 1 N); do ...; sleep 1;
  done` poll loop instead (or `gtimeout` if coreutils is installed via
  brew).
- **`ERR_USE_AFTER_CLOSE` on `rl.prompt()`:** see the readline
  self-close Gotcha above — means the driver's close-guard was removed or
  bypassed somewhere.
