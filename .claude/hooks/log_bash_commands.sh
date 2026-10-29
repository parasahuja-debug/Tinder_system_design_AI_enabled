#!/bin/bash
# Appends every Bash command Claude runs to a local, gitignored log, one
# line each, with TWO separate "why" fields:
#   - general: pulled straight from the Bash tool's own required
#     `description` param — what the command mechanically does, always
#     present, nothing extra required.
#   - project: pulled from a trailing `# <reason>` comment on the command
#     text ITSELF (a habit Claude adopts when a command is tied to a
#     specific project task/phase) — this is the one that explains why
#     THIS command, in THIS repo's build, right now. Falls back to "n/a"
#     when the command carries no such trailing comment.
# Heuristic, not exact: a command containing an unrelated literal "#"
# (a URL fragment, a hex color) could get mis-split. Acceptable here — this
# is a dev-only convenience log, not a security mechanism. Never blocks/
# denies anything (exit 0 always); this is pure logging.
input=$(cat)
command=$(echo "$input" | jq -r '.tool_input.command // ""')
description=$(echo "$input" | jq -r '.tool_input.description // ""')
ts=$(date "+%Y-%m-%d %H:%M:%S")

project_reason=$(echo "$command" | sed -n 's/.* # \(.*\)$/\1/p')
command_clean=$(echo "$command" | sed 's/ #[^#]*$//')
project_reason="${project_reason:-n/a}"

echo "[$ts] $command_clean  # general: $description | project: $project_reason" >> "$CLAUDE_PROJECT_DIR/.claude/bash-commands.log"
exit 0
