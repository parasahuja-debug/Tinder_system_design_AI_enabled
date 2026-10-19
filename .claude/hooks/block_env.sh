#!/bin/bash
# Denies any Read or Bash tool call that reaches this project's .env file.
# .env.example is intentionally untouched by this check.
#
# For Bash, matching is done on real shell tokens (via python3's shlex), not
# a raw substring/regex on the whole command string — a naive substring match
# also fires on ".env" appearing inside ordinary prose (e.g. a log message
# that mentions ".env" in a sentence), which is a false positive, not a real
# file access.
input=$(cat)
tool_name=$(echo "$input" | jq -r '.tool_name')

deny() {
  jq -n --arg reason "$1" '{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "deny", permissionDecisionReason: $reason}}'
  exit 0
}

if [ "$tool_name" = "Read" ]; then
  file_path=$(echo "$input" | jq -r '.tool_input.file_path // ""')
  if [ "$(basename "$file_path")" = ".env" ]; then
    deny ".env is restricted — this project's .env must not be read by any tool. Use .env.example for reference."
  fi
elif [ "$tool_name" = "Bash" ]; then
  command=$(echo "$input" | jq -r '.tool_input.command // ""')
  hit=$(python3 -c '
import shlex, sys
cmd = sys.argv[1]
try:
    tokens = shlex.split(cmd, comments=False)
except ValueError:
    tokens = cmd.split()
for t in tokens:
    if t == ".env" or t.endswith("/.env"):
        print("hit")
        break
' "$command")
  if [ "$hit" = "hit" ]; then
    deny ".env is restricted — this project's .env must not be reached via Bash (cat/grep/head/tail/sed/redirection, etc). Use .env.example for reference."
  fi
fi

exit 0
