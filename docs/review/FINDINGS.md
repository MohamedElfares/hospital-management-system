# Findings

Open items need a decision or a fix. Settled items are closed, and a later
run must not raise them again.

IDs are permanent: `R-001` keeps its meaning for the life of the project.

Severity: `bug`, `security`, `plan` (deviates from the project plan),
`docs`, `naming`.

## Open

| ID | Severity | File | What | Needs |
|---|---|---|---|---|
| R-003 | security | `app/core/errors.py` | The 500 handler `_handle_unexpected_error` (lines 408–411 at `0b901d8`) runs in no test, so nothing checks that an unexpected crash returns the fixed message and a `request_id` and never the exception's text (plan §12: production error responses never include stack traces). A change such as sending `str(exc)` would pass CI. Found in run 1, stage 1. | A test (yours): add a route to the per-test `app` that raises an exception carrying a fake secret (as the `gated_route` fixture adds a route), call it with an `X-Request-ID` through `TestClient(app, raise_server_exceptions=False)`, since Starlette re-raises after the 500, and assert status 500, code `INTERNAL_ERROR`, the fixed message, the echoed `request_id`, and no secret in the body. |

## Settled

Each row says what was decided and why, so the reason survives longer than
the conversation.

| ID | Date | File | What | Decision and why |
|---|---|---|---|---|
| R-001 | 2026-11-04 | `app/core/errors.py` | Plan §11 omitted five error codes the API sends (`BAD_REQUEST`, `CONFLICT`, `METHOD_NOT_ALLOWED`, `INTERNAL_ERROR`, `SERVICE_UNAVAILABLE`) and the 405, 500, and 503 statuses. | Fixed in `93c56a0`: plan §11 now has the three status rows and the five generic codes, and names `ErrorCode` as the full list. All five codes date from Milestone 1.1 (`7452d03`, the error format), so this was overdue work, not a later phase's. Plan text only: no code, rule, or workflow changed. |
| R-002 | 2026-11-04 | `app/core/errors.py` and others | A caught exception was named `exc` in 7 places and `err` in 2, and the naming standard didn't say whether idioms such as `exc` and Pydantic's `loc` count as abbreviations. | `exc` is the one name for a caught or handled exception (Python's and Starlette's idiom), recorded in `NAMING.md`. The two `err` are renamed in their own stages: stage 2 gives you the exact edit for `core/config.py:171`, and stage 10 renames `api/health.py:104`. A name that mirrors a library's own key, such as `loc`, keeps the library's spelling (also in `NAMING.md`). |
