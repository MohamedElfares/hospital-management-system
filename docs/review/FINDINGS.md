# Findings

Open items need a decision or a fix. Settled items are closed, and a later
run must not raise them again.

IDs are permanent: `R-001` keeps its meaning for the life of the project.

Severity: `bug`, `security`, `plan` (deviates from the project plan),
`docs`, `naming`.

## Open

| ID | Severity | File | What | Needs |
|---|---|---|---|---|
| R-001 | plan | `app/core/errors.py` | Plan §11 lists 10 standard error codes, but `ErrorCode` also sends `INTERNAL_ERROR` (500), `BAD_REQUEST` (400), `CONFLICT` (409), `METHOD_NOT_ALLOWED` (405), and `SERVICE_UNAVAILABLE` (503), and the §11 status table has no 405, 500, or 503 row. A client built from the plan wouldn't expect them. Found in run 1, stage 1. | Your decision: sync plan §11 with the code (a docs edit I can make outside this review), or keep §11 to the domain-specific codes and say so there. |
| R-002 | naming | `app/core/errors.py` and others | A caught or handled exception is called `exc` in 7 places (the four handlers here, `users/service.py`, `cli.py` twice) and `err` in 2 (`core/config.py:171`, `api/health.py:104`); `errors.py` also keeps Pydantic's key `loc`. The naming standard allows only glossary abbreviations and doesn't say whether these Python and library idioms count. Left unchanged. Found in run 1, stage 1. | Your decision. Recommended: settle `exc` in `NAMING.md` as the one name for a caught exception (Python's and Starlette's own idiom), rename the two `err` in their stages (`config.py` is yours, so you'd get the exact edit), and keep library keys such as `loc` spelled as the library spells them. |
| R-003 | security | `app/core/errors.py` | The 500 handler `_handle_unexpected_error` (lines 384–387) runs in no test, so nothing checks that an unexpected crash returns the fixed message and a `request_id` and never the exception's text (plan §12: production error responses never include stack traces). A change such as sending `str(exc)` would pass CI. Found in run 1, stage 1. | A test (yours): add a route to the per-test `app` that raises an exception carrying a fake secret (as the `gated_route` fixture adds a route), call it with an `X-Request-ID` through `TestClient(app, raise_server_exceptions=False)`, since Starlette re-raises after the 500, and assert status 500, code `INTERNAL_ERROR`, the fixed message, the echoed `request_id`, and no secret in the body. |

## Settled

Each row says what was decided and why, so the reason survives longer than
the conversation.

| ID | Date | File | What | Decision and why |
|---|---|---|---|---|
