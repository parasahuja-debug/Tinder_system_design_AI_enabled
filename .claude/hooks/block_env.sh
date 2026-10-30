#!/bin/bash
# Denies any Read or Bash tool call that reaches this project's real
# secret files — the root .env, and any k8s Secret manifest literally
# named secret.yaml (k8s/auth-service/secret.yaml,
# k8s/postgres/secret.yaml, k8s/image-service/secret.yaml, etc).
# .env.example and secret.yaml.example are intentionally untouched by
# this check — same "real file blocked, template stays readable" pattern
# for both.
#
# For Bash, matching is done on real shell tokens (via python3's shlex),
# not a raw substring/regex on the whole command string — a naive
# substring match also fires on ".env"/"secret.yaml" appearing inside
# ordinary prose (e.g. a log message that mentions one in a sentence),
# which is a false positive, not a real file access.
input=$(cat)
tool_name=$(echo "$input" | jq -r '.tool_name')

RESTRICTED_NAMES=(".env" "secret.yaml")

deny() {
  jq -n --arg reason "$1" '{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "deny", permissionDecisionReason: $reason}}'
  exit 0
}

if [ "$tool_name" = "Read" ]; then
  file_path=$(echo "$input" | jq -r '.tool_input.file_path // ""')
  base=$(basename "$file_path")
  for name in "${RESTRICTED_NAMES[@]}"; do
    if [ "$base" = "$name" ]; then
      deny "$name is restricted — this project's $name must not be read by any tool. Use its .example template for reference."
    fi
  done
elif [ "$tool_name" = "Bash" ]; then
  command=$(echo "$input" | jq -r '.tool_input.command // ""')
  hit=$(python3 -c '
import shlex, sys
cmd = sys.argv[1]
restricted = sys.argv[2:]
try:
    tokens = shlex.split(cmd, comments=False)
except ValueError:
    tokens = cmd.split()
for t in tokens:
    for name in restricted:
        if t == name or t.endswith("/" + name):
            print(name)
            sys.exit(0)
' "$command" "${RESTRICTED_NAMES[@]}")
  if [ -n "$hit" ]; then
    deny "$hit is restricted — this project's $hit must not be reached via Bash (cat/grep/head/tail/sed/redirection, etc). Use its .example template for reference."
  fi
fi

exit 0
