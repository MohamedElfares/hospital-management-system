# Review log

One entry per run, newest first. An entry opens when the run is planned and
closes when the last stage is done, so an interrupted run is obvious.

## Run 1 — 2026-11-04 — `all` — open

- **Scope:** `all`, the first full baseline (`STATE.md` was empty).
- **Base commit:** `646fb3a` on `main`; the run works on branch `docs/review-run-1`.
- **Files:** 47 Python files under `backend/`, 8,406 lines.
- **Order:** application code bottom-up (core, database, modules, wiring),
  then tests, so every rename that reaches into the tests lands before the
  test stages document them.
- **Audit-only files:** `app/core/config.py` and `migrations/` are yours, so
  their stages log findings with the exact edit instead of changing them.
- **Split test files:** `test_auth_service.py` (1,162 lines) and
  `test_auth_api.py` (977 lines) are reviewed in three parts each, by the
  function or route under test. A split file gets its `STATE.md` row when
  its last part is done.
- **API check:** there is no committed `openapi.json` yet, so a stage that
  touches a router or schema exports the schema before and after its
  changes and diffs the two.
- **Recurring finding (stage 2):** R-003, R-011, and R-012 are the same
  kind: a guard for secrets, personal data, or configuration that no test
  runs. Proposed line for `CLAUDE.md` under "Backend tests", yours to
  accept or reject: "Every guard that keeps secrets or personal data out of
  responses and logs, or stops startup on a bad setting, gets a test that
  fails when the guard is removed." Accepted on 2026-11-04 (you asked me
  to apply my recommendations) and added to `CLAUDE.md` under "Backend
  tests", word for word.
- **Changed after planning (2026-11-04):** the fixes for R-003 and R-009
  to R-011 grew `tests/test_errors.py` and `tests/test_logging.py`, so
  stage 12 is now about 506 lines; split it when you reach it. Stage 9's
  `app/api/deps.py` gained the user-ID line. `app/core/logging.py` has
  changed since stage 2 reviewed it at `2127a70`, so the next
  `/review new` takes it again, as it will `config.py`, changed in
  `473f2af` for R-004 and R-005. `tests/test_config.py` (R-012,
  `fad3630`) is stage 24.
- **Renames and tutorials (stage 3):** stage 3's renames change code that
  tutorial pages 10 and 12 quote. Those pages stay valid: each one is
  checked against the commit in its `hms-source-commit` tag, as
  `tutorial/README.md` explains, so a later rename never needs a page edit.
- **`config.py` re-checked (2026-11-04):** R-006 and R-007 were fixed in
  `7d080c0`, together with R-017, which a full §17 pass over the file
  found. Its `STATE.md` row now points at `7d080c0`, so the next
  `/review new` skips it unless it changes again; `logging.py` is still
  due. No finding is open.
- **Carried to stage 7 (from stage 6):** `PasswordChange` in
  `auth/schemas.py` says the current password's maximum caps the hashing
  work. Measured with `hash_password`, Argon2's time barely grows with
  length (about 51 ms for 128 characters and 53 ms for a million), so
  stage 7 should correct that sentence, as stage 6 corrected the same
  claim in the `PASSWORD_MAX_LENGTH` comment. Done in `b7d1692`,
  measured again at 48 ms for 128 characters and 50 ms for a million.
- **Stage 6's findings fixed (2026-11-05):** R-018 (`263c771`), R-019
  (`46bf282`), and R-020 (`8f6eb9f`), written at your request, one commit
  each. They change `users/schemas.py` and `users/service.py` after
  stage 6 reviewed them at `75ec621`, and `app/db/session.py` after
  stage 4 (`56f211b`), so the next `/review new` takes those files again.
  The `login` docstring in `auth/service.py` changed too, before stage 8
  reaches it. New tests landed in `test_database.py` (stage 12),
  `test_user_schemas.py` (stage 14), `test_user_service.py` and
  `test_cli.py` (stage 15), and `test_auth_api.py` (stage 21), so those
  stages grow a little. Each commit passes Ruff and the suite on its own,
  run like CI in a clean worktree: 287, 288, then 296 tests. R-021, the
  `create-admin` example's `.test` address, found while fixing R-018, was
  fixed in `7e2eaed`. No finding is open.
- **Stage 7's findings fixed (2026-11-05):** R-023 (`18f8a67`), R-022
  (`9f603dd`), and R-024 (`c5f30ea`), written at your request, one commit
  each, in dependency order: the lock tests first, pinning today's
  behaviour, then the fix with tests that fail before it. `f1c3525` gave
  the race tests a database of their own, after a run of mine failed
  while another test run used the shared test database at the same
  moment, and `e689774` covers a user deleted while refresh waits. They
  change `auth/repository.py` after stage 7 reviewed it at `b7d1692`,
  `users/repository.py` after stage 5 (`8cee6f1`), and
  `users/service.py` after stage 6 (`75ec621`), so the next
  `/review new` takes those files again. `auth/service.py` changed before
  stage 8 reaches it, its `repository` import comment included. New tests
  landed in `test_auth_repository.py` and `test_user_repository.py`
  (stage 16) and `test_user_service.py` (stage 15), and the new
  `tests/test_auth_concurrency.py` is stage 25. Each commit passes Ruff
  and the suite on its own, run like CI in a clean worktree: 298, 311,
  311, 311, then 312 tests, with coverage at 99.56%. R-025, a sign-in
  racing a password change, found while fixing R-022, was fixed in
  `965e10e` at your request, with the lock taken after the password
  check rather than before it as first recommended, so that failed
  sign-ins never wait for each other; 317 tests, coverage 99.56%. It
  changes `auth/repository.py` and `users/service.py` again and grows
  `tests/test_auth_concurrency.py`. No finding is open.
- **Recurring finding (stage 8):** R-022, R-025, and R-026 are the same
  kind: a use case that changes a user's sessions decided on account
  state that another request could change before its commit. Proposed
  line for `CLAUDE.md` under "Conventions", after the row-locks line,
  yours to accept or reject: "A service that issues refresh tokens, or
  revokes all of a user's, locks the user's row with
  `get_user_by_id_for_update` before it writes, and re-checks on the
  locked row anything it read before the lock, such as `is_active` or
  the password hash."

Each ticked stage lists its `refactor` and `docs` commit SHAs.

### Application code

- [x] 1. Core errors — `app/core/__init__.py`, `app/core/errors.py` (420 lines) — refactor: none, no rename needed; docs: `d5dc7cd`; Ruff clean, 245 passed; no router or schema touched, so no OpenAPI diff; findings R-001 to R-003
- [x] 2. Core config and logging — `app/core/config.py` (audit only), `app/core/logging.py` (384 lines) — refactor: none in `logging.py`; the two `config.py` renames (R-002's `err`, and `item`) are your edits, in R-006; docs: `2127a70`; Ruff clean, 245 passed; no router or schema touched, so no OpenAPI diff; findings R-004 to R-012
- [x] 3. Core security and permissions — `app/core/security.py`, `app/core/permissions.py` (377 lines) — refactor: `4a04d9d` (`_password_hash` → `_password_hasher`; `check_password` → `verify_login_password`, which also reaches `auth/service.py`, `tests/test_security.py`, and `tests/test_auth_service.py`); docs: `fe8906c`; Ruff clean, 281 passed; no router or schema touched, so no OpenAPI diff; findings R-013, R-014
- [x] 4. Database and migrations — `app/db/__init__.py`, `app/db/base.py`, `app/db/session.py`, `migrations/env.py`, `migrations/versions/feee06ced45e_create_users_table.py`, `migrations/versions/3da0f6bf8dd1_create_refresh_tokens_table.py` (476 lines; migrations audit only) — refactor: none, no rename needed (the migrations' names are Alembic's own); docs: `56f211b`; Ruff clean, 281 passed; no router or schema touched, so no OpenAPI diff; every docstring claim checked on scratch databases; findings R-015 and R-016, both fixed before the stage closed (`77bfb8a`, `2a1b18b`, `3cad085`)
- [x] 5. users: models and repository — `app/modules/users/__init__.py`, `models.py`, `repository.py` (251 lines) — refactor: `217dbac` (`get_by_email` → `get_user_by_email`, `get_by_id` → `get_user_by_id`, `active_admin_exists` → `exists_active_admin`, and `add` → `create_user`, per the repository shape rule; it reaches `users/service.py`, `tests/test_cli.py`, `tests/test_user_repository.py`, and `tests/test_user_service.py`, including a `monkeypatch` target string; `NAMING.md` gained the `create_<thing>` row); docs: `8cee6f1`; Ruff clean, 281 passed; no router or schema touched, so no OpenAPI diff; claims checked with `EXPLAIN` and SQL probes on `hms_test`; no findings
- [x] 6. users: schemas and service — `app/modules/users/schemas.py`, `service.py` (299 lines) — refactor: none, no rename needed (`data` stays, your choice of my recommendation, now a `NAMING.md` row); docs: `75ec621`; Ruff clean, 281 passed; OpenAPI exported before and after: the only difference is `UserRead`'s description, which is its docstring; claims checked with probes on `hms_test` and the installed Pydantic, email-validator, and SQLAlchemy; findings R-018 to R-020
- [x] 7. auth: models, repository, and schemas — `app/modules/auth/__init__.py`, `models.py`, `repository.py`, `schemas.py` (274 lines) — refactor: `e0db329` (`add` → `create_refresh_token`, `get_by_hash` → `get_refresh_token_by_hash`, and `revoke_all_for_user` → `revoke_all_refresh_tokens_for_user`, the last your choice of my recommendation; it reaches `auth/service.py`, `tests/test_auth_repository.py`, whose three `test_revoke_all_*` names follow, and a `tests/test_auth_service.py` docstring; `NAMING.md` gained the `get_<thing>_by_hash` and `revoke_all_<things>_for_<owner>` rows); docs: `b7d1692`, with the `PasswordChange` correction carried from stage 6; Ruff clean, 296 passed; OpenAPI exported before and after: only `TokenResponse`'s and `PasswordChange`'s descriptions differ, which are their docstrings; claims checked with probes on scratch databases (the row lock between two connections, `EXPLAIN`, what loaded objects show after the bulk `UPDATE`) and in the installed SQLAlchemy, FastAPI, and Pydantic; findings R-022 to R-024
- [x] 8. auth: service — `app/modules/auth/service.py` (546 lines when planned, 608 after the R-022 and R-025 fixes) — refactor: none, no rename needed (`refresh` and `logout` follow their routes, as `NAMING.md`'s `login` row does); docs: `605ac3b`; Ruff clean, 317 passed; no router or schema touched, so no OpenAPI diff, and the code's AST is identical without the docstrings; claims checked against the race tests and with probes on a scratch database (a rotated token raises the alarm every time, even expired; a sign-out meeting a refresh in flight; `repr` of `IssuedTokens`); findings R-026 to R-029
- [ ] 9. auth: router and request dependencies — `app/modules/auth/router.py`, `app/api/deps.py` (428 lines)
- [ ] 10. App, health, and CLI — `app/__init__.py`, `app/main.py`, `app/modules/__init__.py`, `app/api/router.py`, `app/api/health.py`, `app/cli.py` (320 lines)

### Tests

- [ ] 11. Test setup — `tests/conftest.py`, `tests/factories.py` (324 lines)
- [ ] 12. Platform tests — `tests/test_database.py`, `tests/test_errors.py`, `tests/test_logging.py`, `tests/test_health.py` (232 lines)
- [ ] 13. Security tests — `tests/test_security.py` (509 lines)
- [ ] 14. users tests: model and schemas — `tests/test_user_model.py`, `tests/test_user_schemas.py` (349 lines)
- [ ] 15. users tests: service and CLI — `tests/test_user_service.py`, `tests/test_cli.py` (414 lines)
- [ ] 16. Repository tests — `tests/test_user_repository.py`, `tests/test_auth_repository.py` (315 lines)
- [ ] 17. auth tests: model and schemas — `tests/test_refresh_token_model.py`, `tests/test_auth_schemas.py` (349 lines)
- [ ] 18. auth service tests, part 1 — `tests/test_auth_service.py`: constants, fixtures, helpers, and `login` tests (about 450 lines)
- [ ] 19. auth service tests, part 2 — `tests/test_auth_service.py`: `get_authenticated_user` and `refresh` tests (about 370 lines)
- [ ] 20. auth service tests, part 3 — `tests/test_auth_service.py`: `logout`, `change_password`, and password-change gate tests (about 340 lines)
- [ ] 21. auth API tests, part 1 — `tests/test_auth_api.py`: constants, fixtures, helpers, and `POST /auth/login` tests (about 265 lines)
- [ ] 22. auth API tests, part 2 — `tests/test_auth_api.py`: `GET /auth/me`, `POST /auth/refresh`, and `POST /auth/logout` tests (about 375 lines)
- [ ] 23. auth API tests, part 3 — `tests/test_auth_api.py`: `POST /auth/change-password` and gated-route tests (about 340 lines)
- [ ] 24. Settings tests — `tests/test_config.py` (327 lines), added 2026-11-04 for R-012
- [ ] 25. auth concurrency tests — `tests/test_auth_concurrency.py` (893 lines), added 2026-11-05 for R-022, R-023, and R-025; split it in three when reached: the fixtures and helpers, the refresh and sign-out races, then the password change and sign-in races
