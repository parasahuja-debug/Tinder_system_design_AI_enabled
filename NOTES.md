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



