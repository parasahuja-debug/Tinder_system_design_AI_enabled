# Day1 Execution

- Check - Docker daemon up, Node 26, Python 3.13 and Angular.
- Create auth service main.py - three main routes
    Validate - reads the Authorization: Bearer <token> header, verifies the signature/expiry, and puts the user's id into an X-User-Id response header. (first step of nginx, and then cnginx capture the X-User-Id)
    Login
    Register
- Requirements file for the auth service
- DockerFile - for the auth service.
- Claude.md for Auth service 

- Profile_service/main.py 
    create profile 
    get profile - when validate step is done in auth service , nginx with X-User-Id fetches the profile. profile service just trusts X-User-Id, token is already validated.
- gets its own requirements.txt file
- Docker file for the profile service.

- gateway/conf.d/default.conf - the only thing the browser ever talks to. Everything else is sealed inside the private Docker network.
- docker-compose.yml to enable all the env - auth,postgres,profileservice,gateway and pgweb
- then mcp.json file - this is an mcp to connect with postgress, in later runs when llm would wantto connect with the DB, this would be used, until then claude code assistant uses it.
- hook - post_edit_lint.sh - whenever a python file is edited the hook will initiate to check if it is right python syntax.
- /test command- 
- fastapi-endpoint skill to create a good API and note the right things for the purpose.
- building Frontend - 
    npx -y -p @angular/cli@22 ng new frontend --style=css --ssr=false --skip-git --defaults
    > ng new is Angular's scaffolding generator. It created the folder structure and ran npm install, which is where the bulk of the "lots of folders" came from. 

- create - proxy.conf.json (URLs for profile page and /auth)
    Forwards /auth and /profile from :4200 → gateway :8080 so the browser never sees a cross-origin request (no CORS needed)
- create angular.json - point angular.json's serve target at that proxy file, so ng serve picks it up automatically.
    Post this edit- ng serve (i.e. npm start) will now route /auth/* and /profile/* calls to the gateway.
    ng serve doesn't know the proxy file exists unless told — serve.options.proxyConfig wires it in
- edit app/app.config.ts - 
- create app/auth.service.ts (called through app.config.ts) - localStorage is only ever touched in auth.service.ts — nowhere else. AuthService is the hub, everything else points at it.

- create app/auth.interceptor.ts
- create app/auth.guard.ts
- create app/login/login.ts
- create app/login/login.html - Email/password form → AuthService.login() → navigate home
- create app/register/register.ts
- create app/register/register.html - Same shape, calls /auth/register (also logs you in, per the backend)
- create app/home/home.ts
- create app/home/home.html - The guarded landing page — calls GET /profile on load to prove the whole auth chain works from a real browser, not just curl
- now mapping - create app/app.routes.ts (login/register/home)
- create - app.html.generated-placeholder - preserve ng new generated
- edit app.html basis our requirement
- edit app.ts 
- edit styles.css - global styling file - Minimal shared styling so the forms/buttons aren't unstyled 

                    ┌─────────────────────────┐
                    │   AuthService            │
                    │  (owns the JWT)           │
                    └───────────┬─────────────┘
        writes token ↑          │ reads token ↓
   ┌──────────┬──────────┐      ├───────────┬────────────┐
   │ login.ts │register.ts│     │interceptor│  guard.ts   │
   └──────────┴──────────┘      └───────────┴────────────┘
                                        │            │
                              attaches header   blocks route
                                        ▼            ▼
                                gateway :8080   Router → /login


> Initiate - 
    Frontend dev server
    cd frontend
    npm start                     # = `ng serve`, picks up proxy.conf.json automatically
    Open- http://localhost:4200

## Quick notes

[2026-08-12 23:20] i wanted to learn Day1 procedure from Day1 setup session
[2026-08-12 23:20] i wanted to understand the decisioning around database , why index are there and why each table exists and why we key pk.

-----

# Day2 Execution
- Edit profile service (main.py)
    Profile schema addition for day3 plan (gender/lat/long)
    Id column is index and pk for 1-1 relationship with auth service user table
    Profile request schema update (user id doesnt validated, it comes in request)
    **Profile: ProfileRequest is what the client sends; Profile is what's stored.**
    X-User-Id pull funtion to pull from request. Fail if not exists.
    Replacing /create-profile with the real POST /profile route. (adding small validations- profile exists and new fields). ID comes in request now, not random created.
    Get profile changed - 
        Day 1 version just echoed X-User-Id back to prove the gateway wiring worked — it never touched the database. Now it does a real Profile lookup for that user, returning all the fields, or a 404 if they haven't created a profile yet.
    Adding /Put profile - if there is a need to update the profile.

- Add fresh image Service
    **key decisions :**
        Image limit - 5
        Image extensions (check is added later).
        Some extensions are deliberately missed to cater the attacks. 
            Deliberately excluding .svg: SVG is XML, and XML can embed script tags.
            Not handling .heic (the iPhone default format): most browsers can't render it natively.
        File size cap is needed.
    Image Schema (surrogate key concept because 1-many relationship, not fk/pk like profile and user)
    get_user_id helper - **no sharing with profile service as each service runs on its own container, 4 lines can cause coupling**
    /post method in images - upload an image
        Image table and User table is linked (through userid column)
        First file write then DB update.
        If DB fails, file is removed.
    /get images - all images information
        this is what the Angular profile view will call to render existing thumbnails, and what makes the "reload confirms persistence" verification step possible later.
    /get imageid - get image one at a time for rendering, browser would ask it.
        stops checking "do you own this photo" — it just checks "are you logged in at all" (which it already gets for free, since only the gateway can reach it and only after auth).

- Adding entry in Docker-compose.yml
- Update nginx/default conf - to add image service
- Frontend :
    - new profile.service.ts : listImages/uploadImage/getImageBlob methods - all API calls of image service
        A new service, same shape as auth.service.ts — owns talking to /profile. Profile mirrors what GET /profile returns; ProfileRequest is Profile minus user_id
    - Edit home.ts - has profile create/edit logic
    - Edit home.html - provides profile info now, image section
    - Edit global styles.css
    - India-locations.ts - all state and city names of india to render on form, home.ts to refer


----

# Day3 Execution
- create matcher_service/main.py
    - Schema or matcher and swipe
    - swipe request and userid fetch from header
    - add swiperid,targetid and direction of swipe in table
    - post swipe - swipe table entry if new, and check for match if other person has also swiped
    - get matches - 
        filters for rows where the caller is either user_a_id or user_b_id (per the alphabetical-ordering note from piece 1), then for each row returns whichever id isn't the caller — that's "the other person in the match."
- requirements.txt file for matcher service
- Docker file

- create recommendation service 
    - recommendation_service reads the images table directly from the shared Postgres — just the image ids, not the actual photo files. It includes those ids in each candidate it returns.
    - get user id
    - bounding function if 2kn is selected, it is 2 km in rectangular area.
    - /discover get method - use profiles table to get the user, and then get image from image table for the users,
- requirements.txt for recommendation service
- Docker file

- update dockercompose.yml file with both the service
- nginx config update -
    nginx routes. Two new paths need registering — /discover → recommendation-service:8005, and /swipe + /matches → matcher-service:8004 (two separate location blocks pointing at the same upstream, since matcher owns two distinct paths). All three are protected routes, so each gets the full three-line pattern (auth_request, auth_request_set, X-User-Id forward) copied from /profile.

- Front end -
    - Add brandmark on register.html and register.ts
    - Home.html,home.ts also gets a smaller one

- Make run tinder skill to run the frontend 
    - a driver.mjs (headless-Chromium REPL via Playwright) plus SKILL.md documenting it — so future sessions can launch the Angular dev server and actually click through/screenshot the app instead of trusting code-reading alone; used it just now to confirm the brand-mark changes render correctly on /register (full) and / (compact), fixing three real bugs in the driver along the way (async command ordering, premature stdin-close killing in-flight commands, and a substring bug in URL-waiting) — all now documented in the skill's Gotchas section for next time.

- create - discovery.service.ts
    mirrors profile.service.ts's pattern (routes + shapes live in one service, pages never call HttpClient directly). Three methods: discover() → GET /discover, swipe() → POST /swipe, listMatches() → GET /matches.

- building discover.ts in three small pieces, same rhythm as matcher_service. Piece A: imports, state signals, and ngOnInit 
- discover.html - page
- adding the clasess used in styles.css

- updating app.routes.ts in frontend/src/app

- updating home.html in same
- updating home.ts - guided discover button
- two services in profile and image (get method added to each service for docker)
- frontend/src/app/matches - for discover matches 
    app.routes.ts add 
    global css
    rest files in matches folder

# Day4 Execution

- session_service - 
    post("/session/connect") - who came online (Called by direct_msg right after it accepts that
    user's WebSocket connectionc)
    post("/session/disconnect") - Called by direct_msg when that user's WebSocket closes (tab closed, network drop, etc.
    get("/session/{user_id}") - to check if the user is online or not-
        The lookup endpoint isn't called by direct_msg today — Day 4's chat only needs match verification and persistence, not "is the other person online right now"
    get("/health") - healthcheck
- Docker File
- requirements.txt
- Claude.md - purpose, endpoints, env, how to run standalone.

- direct_msg - 
    The core problem: nginx's auth_request (which every other protected route uses) doesn't compose with a WebSocket upgrade, and a browser can't set an Authorization header on a WS connection anyway. So this is the one place in the whole system where "only the gateway authenticates" has to bend.
- get("/matches/{match_id}") - in main.py of matcher_service
    Runs through the direct msg service - to confirm the matches before direct msging service to enable.
- main.py for direct_msg service.
    has its own authenticator - authenticates from auth service
    has its own confirmation of matches through matcher service.
    custom codes for websocket
    then eventually websocket - those who do not know - 
        it starts as a completely normal HTTP request — the browser asks the server "can we upgrade this connection to a WebSocket?" The server replies with a special HTTP status (101 Switching Protocols) if it agrees. After that one exchange, it stops being HTTP entirely — it becomes a raw, long-lived, two-way pipe 
    GET /chat/history/{match_id} — the plain HTTP endpoint (gateway-protected via auth_request, like every other route) the Angular page calls on load to fetch prior messages before the WebSocket connects. 
    healthcheck also.
    direct_msg/main.py first — it's the one existing service using async/WebSocket patterns, and the MCP client's lifecycle (opened once at startup, kept alive)
- Docker File 
- requirements.txt
- CLAUDE.md

- append both services - dockercompose.yml
- append - ateway/conf.d/default.conf
    validation skip in websocket
    for chat hostory it exists.

**note - gateway does't get recreated since it depends only on a mounted config, not a rebuilt image — restarting it helps**

- Front end -
     src/app/chat.service.ts.- websocket connect and chat
        getHistory (plain HTTP, interceptor handles auth) and connect (raw WebSocket with the subprotocol token trick).
     src/app/chat/chat.ts - 
        history loading, the WebSocket lifecycle (openSocket, onmessage, onclose branching on those real close codes), send(), and ngOnDestroy (so navigating away actually closes the socket, matching the per-page connection scope we agreed on).
    src/app/chat/chat.html - 
    styles.css - chat page styles
    src/app/app.routes.ts - bounc the frontend

# Day5 Execution

- Support_chatbot_service - 
    - Docker File - for the service independency.
    - Requirements.txt - for the individual dependency.
    - main.py - Entry point then other things are plitted across files now
        Readme.md chunking, use of fastembed instead of sentencetransformers
        - docchunk(README) and chatbotmessage stored.
        - two tables - chatbot_messages,doc_chunks one for each.
        - MCP client - This is the first place in the codebase needing genuine async startup (spawning and keeping open a subprocess), so it introduces @app.on_event("startup"/"shutdown") — nothing else here has needed that yet, since every other service's setup is synchronous module-level code.
        <everything else in this file (the two named tools, and later the WS endpoint tool-call loop) depends on _mcp_session already being open — so the session itself has to exist before anything can call it.>
        - _run_readonly_query is the single function that actually talks to _mcp_session — every tool call funnels through here so there's exactly one code path to audit, not one per tool.
        - get_match_count and get_profile_summary.they're the only live-data the plan calls for — companion mode grounding a supportive reply in a real match count, and enough profile info (name/age/city, deliberately not bio/lat/long) to personalize a reply without exposing more than the app itself already shows a user about their own profile.
    - mem0 init — configuring it to use the local Ollama model (both as LLM and embedder) and our existing pgvector as its store, so it's a separate concern from the README-RAG embeddings but doesn't add a new datastore

    Around mem0 - 
        - memory.add(transcript, user_id=...) (when a session ends): mem0 calls the configured LLM (our Ollama model) to extract a short summary from the transcript, calls the configured embedder (Ollama's nomic-embed-text) to vectorize that summary, and writes both the text and the vector as a row in its own Postgres table (via the pgvector extension — the same extension doc_chunks uses, just a different table).
        - memory.get_all(user_id=...) (when a session opens): reads back every stored row for that user — a plain metadata filter by user_id, no vector math needed, since we just want "this user's recent memories," not a semantic search. We then filter that list to the last 7 days ourselves and delete anything older.
    
    - the two helper functions the WS endpoint will call — save_session_memory (on disconnect) and load_recent_memories (on connect, with the lazy 7-day pruning).
    - connection handshake. This mirrors direct_msg's pattern almost exactly (same reason: auth_request can't gate a WebSocket, and a browser can't set Authorization on one either) — token rides as the Sec-WebSocket-Protocol subprotocol, resolved via a plain HTTP call to auth-service's existing /validate. The one thing new here: after auth succeeds, the client's first JSON message must declare {"mode": "faq" | "companion"} before anything else happens.
    - chat client, system prompts, tool schemas.

    A few notes before writing:

    Using AsyncOpenAI (not the sync client) since everything else in this endpoint will be async/await (the MCP calls, the WebSocket itself) — using the sync client here would block the event loop.
    - wrap_openai from LangSmith wraps the client instance itself, so every call through it gets traced automatically — no per-call tracing code needed.
    - Tool schemas take no parameters — consistent with decision #5: the model only ever picks which tool to call, user_id always comes from the connection's trusted identity, never from the model.

- docker-compose.yml - append ollama and the supportchatbotservice
- gateway/conf.d/default.conf — a new self-authenticated /support/ws location, same shape as the existing /chat/ws block (no auth_request, since a WS upgrade can't compose with it; just the Upgrade/Connection headers forwarded).

- Frontend - 
    - first support-chat.service.ts. Let me check the existing chat.service.ts and auth.service.ts to mirror the established WS + auth patterns exactly.
    - src/app/support-widget/support-widget.ts
    - src/app/support-widget/support-widget.html
    - styles.css
    - mounting the widget in the app shell. This means **app.ts** needs to gate on login state for the first time (previously it had "no app-level state on purpose").

----
## Key Facts
mem0 fetching - 
    - there's no user_id column at all. mem0's create_col (line ~68 above) only ever defines three columns: id UUID,vector, payload JSONB. user_id isn't schema — it's just a key inside payload, same as data/memory/created_at.
    - Filtering happens in list() (used by get_all, which is what load_recent_memories calls): for each filters key/value passed in — here just {"user_id": "..."} — it builds payload->>%s = %s and runs
        - SELECT id, vector, payload FROM mem0 WHERE payload->>'user_id' = '<the-uuid>' LIMIT 100

----
# Day6 Execution

- auth_service/main.py
    middleware - tracks every request in the piece.
    get metrics() - 
        generate_latest() produces the bytes, and Response(generate_latest(), media_type=CONTENT_TYPE_LATEST) just wraps those bytes in an HTTP response with the content-type Prometheus's scraper expects (text/plain; version=0.0.4; charset=utf-8, which is what the CONTENT_TYPE_LATEST constant holds).
    Login count(seperate)- above two were Request related.
    update requirements.txt
- profile-service, image-service, recommendation-service, session-service
    the generic part (REQUEST_COUNT, REQUEST_LATENCY, the track_requests middleware, and the /metrics endpoint) is copy-paste identical across every service, same imports and same code. Nothing about it needs re-deriving per service.
- matcher_service — this one also needs a business counter for swipe/match counts, the generic part first
    SWIPE_COUNT is labeled by direction (like vs pass) so
# Grafana can chart them separately; 
    MATCH_COUNT has no labels since a match is a single kind of event.
- direct_msg - 
    which needs the chat-message business counter but there's a wrinkle worth flagging before I write it: the generic track_requests middleware only wraps regular HTTP requests, not WebSocket connections (@app.middleware("http") doesn't intercept the /chat/ws/{match_id} upgrade at all). So the generic metrics will only ever see /chat/history, /health, and /metrics — the WebSocket route itself never shows up in http_requests_total, which is expected and fine.
    






