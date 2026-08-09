#!/usr/bin/env bash
# Post-edit hook (Claude Code, DEV-TIME ONLY — never runs in the app at runtime).
# Purpose: right after Claude edits/writes a file, catch obvious breakage in the
# same session instead of discovering it at `docker compose up`. Day 1 has no
# test suites yet, so the check is a fast Python syntax compile (plus ruff if it
# happens to be installed). As each service gains a pytest suite this grows into
# running that service's tests; /test finalizes the story on Day 7. Non-Python
# files are ignored.

# Claude Code pipes the tool call as JSON on stdin; pull out the edited path.
input=$(cat)
file=$(printf '%s' "$input" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("tool_input",{}).get("file_path",""))' 2>/dev/null)

# No path (or a non-file tool) — nothing to check.
[ -z "$file" ] && exit 0
[ -f "$file" ] || exit 0

case "$file" in
  *.py)
    # py_compile only parses (no imports), so it's fast and needs no service
    # deps installed on the host. Exit 2 makes Claude Code surface the error.
    if ! python3 -m py_compile "$file" 2>&1; then
      echo "post-edit hook: py_compile failed for $file" >&2
      exit 2
    fi
    # ruff is optional; only lint if available so the hook never hard-fails just
    # because the host doesn't have ruff installed.
    if command -v ruff >/dev/null 2>&1; then
      ruff check "$file" >&2 || true
    fi
    ;;
esac

exit 0
