---
description: Append a quick note to NOTES.md without interrupting the current task.
---

You are running `/note`. Purpose: let the user drop a thought into the
project's running notes file mid-task, without re-engaging with whatever
you were doing before or after this command runs.

1. Get the current timestamp: `date "+%Y-%m-%d %H:%M"`.
2. Append one line to `NOTES.md` at the repo root, under a `## Quick notes`
   section at the end of the file (create that section, with a blank line
   before it, if it doesn't already exist):
   `[TIMESTAMP] $ARGUMENTS`
3. This still goes through the normal Edit-tool confirmation card (per the
   user's standing "confirm before editing" rule) — but reply with just
   "noted" after it's approved. Do not otherwise comment on the content, and
   do not resume or restate whatever task was in progress before this command.

$ARGUMENTS
