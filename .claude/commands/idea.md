---
description: Append a quick idea to IDEAS.md without interrupting the current task.
---

You are running `/idea`. Purpose: let the user drop a backlog/future-feature
idea into a running ideas file mid-task, without re-engaging with whatever
you were doing before or after this command runs. Kept separate from
`NOTES.md` (which is the day-by-day learning log) so backlog ideas don't get
mixed into that narrative.

1. Get the current timestamp: `date "+%Y-%m-%d %H:%M"`.
2. If `IDEAS.md` doesn't exist yet at the repo root, create it with a one-line
   header: `# Ideas / backlog` followed by a blank line.
3. Append one line: `[TIMESTAMP] $ARGUMENTS`
4. This still goes through the normal Edit/Write-tool confirmation card (per
   the user's standing "confirm before editing" rule) — but reply with just
   "noted" after it's approved. Do not otherwise comment on the content, and
   do not resume or restate whatever task was in progress before this command.

$ARGUMENTS
