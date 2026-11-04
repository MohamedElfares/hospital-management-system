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

Each ticked stage lists its `refactor` and `docs` commit SHAs.

### Application code

- [ ] 1. Core errors — `app/core/__init__.py`, `app/core/errors.py` (420 lines)
- [ ] 2. Core config and logging — `app/core/config.py` (audit only), `app/core/logging.py` (384 lines)
- [ ] 3. Core security and permissions — `app/core/security.py`, `app/core/permissions.py` (377 lines)
- [ ] 4. Database and migrations — `app/db/__init__.py`, `app/db/base.py`, `app/db/session.py`, `migrations/env.py`, `migrations/versions/feee06ced45e_create_users_table.py`, `migrations/versions/3da0f6bf8dd1_create_refresh_tokens_table.py` (476 lines; migrations audit only)
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
