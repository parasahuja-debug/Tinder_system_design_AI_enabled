npm install supabase --global
OR
brew install supabase/tap/supabase
because Supabase CLI is no longer an npm package
2. Why Homebrew?
Homebrew is the standard package manager on macOS.
It handles:
Installing the CLI in the correct location (/opt/homebrew/bin)
Adding it to your PATH automatically
Updating easily via brew upgrade supabase
It avoids npm-related issues, especially with Node.js versions or system permissions.


supabase --version ---

supabase init ---
created .vscode.settings.json

install deno from extension----

It suggested installing the Deno VS Code extension — this is important for proper syntax highlighting and running Deno scripts inside VS Code.

Why Supabase uses Deno ??

The Supabase CLI is written in Deno, not Node.js.
1. Deno is a modern JavaScript/TypeScript runtime (like Node.js, but more secure and with built-in TypeScript support).
2. Because the CLI itself runs on Deno, some of the scripts, migrations, and helper commands inside a Supabase project rely on Deno features.
3. That’s why when you do supabase init, it detects VS Code and offers to configure Deno settings — so your editor can lint, format, and run these scripts properly.

supabase start -----
open docker -----

why fs layer are getting downloaded? post supabase start 

What “FS layers” are?
Supabase CLI starts local Docker containers for:
Postgres database
Supabase API
Realtime server
Auth
Storage
Each of these services is packaged as a Docker image.
When Docker pulls an image, it does so in layers:
Each layer represents a part of the image (base OS, dependencies, app code).
Docker prints logs like:

Your system doesn’t yet have the Supabase Docker images cached.
Docker downloads all required layers from the Docker Hub.
Example layers:
Base Linux image
Postgres binaries
Supabase API code
Once downloaded, these layers are cached, so the next time you run supabase start, it’s much faster.

either uou can do  before supabase
docker pull supabase/postgres
docker pull supabase/gotrue
docker pull supabase/realtime
docker pull supabase/storage-api


supabase/logflare
supabase/vector
supabase/kong
supabase/malpit
supabase/postgresst
supabase/edge-runtime
supabase/postgress-meta
supabase/studio
supabase/postgres-meta

open - 
http://localhost:54323
studio url
http://localhost:54341/project/default

to find the pw-
docker inspect supabase_db_Supabase | grep POSTGRES_PASSWORD
as my image has name as supabase_db_Supabase - 
CONTAINER ID   IMAGE     COMMAND   CREATED   STATUS    PORTS     NAMES
9005d6f3f562   public.ecr.aws/supabase/postgres:17.6.1.029             "sh -c '\ncat <<'EOF'…"   4 months ago   Up 2 weeks (healthy)   0.0.0.0:5432->5432/tcp, [::]:5432->5432/tcp                                                supabase_db_Supabase

quick check- if it works- psql postgresql://postgres:postgres@localhost:5432/postgres