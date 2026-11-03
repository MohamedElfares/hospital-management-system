# Findings

Open items need a decision or a fix. Settled items are closed, and a later
run must not raise them again.

IDs are permanent: `R-001` keeps its meaning for the life of the project.

Severity: `bug`, `security`, `plan` (deviates from the project plan),
`docs`, `naming`.

## Open

| ID | Severity | File | What | Needs |
|---|---|---|---|---|
| R-002 | plan | backend/app/modules/auth/router.py | Route queries the database directly instead of calling the service | My decision: fix now or open an issue |

## Settled

Each row says what was decided and why, so the reason survives longer than
the conversation.

| ID | Date | File | What | Decision and why |
|---|---|---|---|---|
| R-001 | 2026-11-02 | backend/app/core/security.py | `token` is vague where both access and refresh tokens are handled | Renamed to `access_token`. Applied in run 1. |
