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
  fails when the guard is removed."
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

Each ticked stage lists its `refactor` and `docs` commit SHAs.

### Application code

- [x] 1. Core errors — `app/core/__init__.py`, `app/core/errors.py` (420 lines) — refactor: none, no rename needed; docs: `d5dc7cd`; Ruff clean, 245 passed; no router or schema touched, so no OpenAPI diff; findings R-001 to R-003
- [x] 2. Core config and logging — `app/core/config.py` (audit only), `app/core/logging.py` (384 lines) — refactor: none in `logging.py`; the two `config.py` renames (R-002's `err`, and `item`) are your edits, in R-006; docs: `2127a70`; Ruff clean, 245 passed; no router or schema touched, so no OpenAPI diff; findings R-004 to R-012
- [x] 3. Core security and permissions — `app/core/security.py`, `app/core/permissions.py` (377 lines) — refactor: `4a04d9d` (`_password_hash` → `_password_hasher`; `check_password` → `verify_login_password`, which also reaches `auth/service.py`, `tests/test_security.py`, and `tests/test_auth_service.py`); docs: `fe8906c`; Ruff clean, 281 passed; no router or schema touched, so no OpenAPI diff; findings R-013, R-014
- [x] 4. Database and migrations — `app/db/__init__.py`, `app/db/base.py`, `app/db/session.py`, `migrations/env.py`, `migrations/versions/feee06ced45e_create_users_table.py`, `migrations/versions/3da0f6bf8dd1_create_refresh_tokens_table.py` (476 lines; migrations audit only) — refactor: none, no rename needed (the migrations' names are Alembic's own); docs: `56f211b`; Ruff clean, 281 passed; no router or schema touched, so no OpenAPI diff; docstring claims and R-015 checked against `hms_test` at head; findings R-015, R-016
- [ ] 5. users: models and repository — `app/modules/users/__init__.py`, `models.py`, `repository.py` (251 lines)
- [ ] 6. users: schemas and service — `app/modules/users/schemas.py`, `service.py` (299 lines)
- [ ] 7. auth: models, repository, and schemas — `app/modules/auth/__init__.py`, `models.py`, `repository.py`, `schemas.py` (274 lines)
- [ ] 8. auth: service — `app/modules/auth/service.py` (546 lines)
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
