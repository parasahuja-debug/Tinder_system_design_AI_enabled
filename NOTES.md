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
- create angular.json - point angular.json's serve target at that proxy file, so ng serve picks it up automatically.
    Post this edit- ng serve (i.e. npm start) will now route /auth/* and /profile/* calls to the gateway.
- create app/app.config.ts
- create app/auth.service.ts (called through app.config.ts)
- create app/auth.interceptor.ts
- create app/auth.guard.ts
- create app/login/login.ts
- create app/login/login.html
- create app/register/register.ts
- create app/register/register.html
- create app/home/home.ts
- create app/home/home.html
- now mapping - create app/app.routes.ts (login/register/home)
- create - app.html.generated-placeholder - preserve ng new generated
- edit app.html basis our requirement
- edit app.ts 
- edit styles.css - global styling file

