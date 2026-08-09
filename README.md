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

