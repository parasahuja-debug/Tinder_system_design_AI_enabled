
once the dependency is fulfilled, the pod runs by itself.

Only Cassandra actually persists data to disk. not redis or redpanda, so stateful set is not needed.

kind load docker-image - 
    copies a Docker image that already exists on your Mac into the kind cluster's node-containers directly. Why it's needed: even though kind's nodes run on your same Docker, each node-container has its own separate internal image store
    For our own app images (tinder-auth-service:latest etc.), there's no public registry at all — kind load was the only way to get them into the cluster, since nothing by that name exists anywhere on the internet to pull.

A crashed container under CrashLoopBackOff gets automatically restarted forever by Kubernetes itself, with growing delays between attempts. we just fixed the actual blocker(enable postgress dependency), and Kubernetes' built-in retry loop did the rest.

We're building a second, parallel way to run the same app (on Kubernetes), for Phase 6's learning goal — not replacing the first. "Pulling info from docker-compose" means copying the same configuration values (env vars, image names, commands) into the new k8s files — like translating a recipe into different units; the original recipe isn't thrown away. kind's "nodes" genuinely are Docker containers running on your Mac's existing Docker Desktop (we saw this directly with docker port tinder-control-plane). kind doesn't replace Docker or own it — it uses Docker as the raw material to build something that behaves like real Kubernetes machines.

Redpanda's topic-creation Job was different: it needed to actively confirm Redpanda was reachable before running a command that would otherwise just fail outright (not crash-and-retry gracefully) — so I gave it an explicit wait-loop as a dedicated first step. - So initcontainer exists. An initContainer (a feature inside any pod, Job or not) answers "what must happen first, in strict order, before the main container is even allowed to start."

A multi-arch image is one image name (like redis:7.4-alpine) that secretly bundles several different real images inside it — one per architecture — under one shared index. When you docker pull it, Docker quietly grabs only the one matching your machine and hides the rest.

kind load docker-image's built-in command has no flag to turn off --all-platforms; it's baked into the tool itself.
for Redis, I had to repeat the same manual steps (docker save → copy the file into the node → ctr import without --all-platforms) for Cassandra and Redpanda too, since there was no way to tell kind's own command to behave differently.

Kubernetes deliberately locks most of a Job's blueprint (like what command its containers run) the moment it's created — it refuses in-place edits to that field, specifically because a Job represents a specific tracked task, and letting its actual contents change after the fact would make "did it succeed at the old task or the new one?" ambiguous. So when I needed to fix the broken command, editing the existing Job wasn't an option — I had to kubectl delete job redpanda-init -n tinder (throw the old one away entirely) and then kubectl apply a fresh one with the corrected file.

by default, every pod has restartPolicy: Always — meaning "if this container ever exits (crashes, or even exits cleanly), restart it, no matter what." That's great for a real crash you want auto-healed. But if the reason it's crashing hasn't been fixed (like auth-service not being able to reach Postgres), it just crashes again immediately after each restart — so Kubernetes keeps looping: start → crash → wait a bit → start → crash → wait longer → repeat. CrashLoopBackOff is just the name for "stuck in that exact loop.