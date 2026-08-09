---
description: Run the right tests for wherever this was invoked (backend pytest / frontend ng test).
---

You are running the project's `/test` command.

**Goal:** run the correct test command based on the directory context, without the
user having to remember per-service commands.

**Routing rules (finalized on Day 7 as services gain suites):**
- If invoked inside a backend service dir (`auth_service/`, `profile_service/`,
  `image_service/`, `recommendation_service/`, `matcher_service/`,
  `session_service/`, `direct_msg/`, `support_chatbot_service/`): run that
  service's `pytest`.
- If invoked inside `frontend/`: run `ng test` (or `npm test`).
- If invoked at the repo root: run every service's tests in turn.

**Day 1 status — this is intentionally a stub.** No service has a test suite yet.
For now:
1. Determine which service directory (if any) the command was invoked from.
2. Look for a `tests/` dir or `test_*.py` (backend) / `*.spec.ts` (frontend).
3. If tests exist, run the appropriate command and report pass/fail.
4. If none exist yet, say so plainly (e.g. "auth_service has no tests yet") rather
   than pretending to pass — the whole point of this repo is honest verification.

$ARGUMENTS
