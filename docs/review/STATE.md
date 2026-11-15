# Review state

One row per reviewed file. `/review new` compares each file against the
commit recorded here and reviews only what changed since.

Keep rows sorted by path. Delete the row when the file is deleted. A file
with no row has never been reviewed and is always in scope.

Run 1's rows name commits on `main`: after PR #42 was squash-merged as
`8dacfec`, a file unchanged since its review names that commit, and a
file changed after its review, by the fixes that followed it, names its
parent, `1510f9d`, so the next `/review new` takes it again. The one
exception is `tests/test_auth_concurrency.py`, reviewed in stage 25 after
that merge, on branch `docs/review-run-1-stage-25`: its row names
`33cd514`, where stage 25a documented part 1, because the fixes after
stages 25a and 25b changed parts 1 and 2 after their reviews, so the next
`/review new` takes the whole file again. When that branch is merged, the
row moves by the same rule.

| File | Reviewed at commit | Date | Run |
|---|---|---|---|
| `backend/app/__init__.py` | `8dacfec` | 2026-11-05 | 1 |
| `backend/app/api/__init__.py` | `8dacfec` | 2026-11-05 | 1 |
| `backend/app/api/deps.py` | `8dacfec` | 2026-11-05 | 1 |
| `backend/app/api/health.py` | `1510f9d` | 2026-11-05 | 1 |
| `backend/app/api/router.py` | `8dacfec` | 2026-11-05 | 1 |
| `backend/app/cli.py` | `1510f9d` | 2026-11-05 | 1 |
| `backend/app/core/__init__.py` | `8dacfec` | 2026-11-04 | 1 |
| `backend/app/core/config.py` | `1510f9d` | 2026-11-04 | 1 |
| `backend/app/core/errors.py` | `1510f9d` | 2026-11-04 | 1 |
| `backend/app/core/logging.py` | `1510f9d` | 2026-11-04 | 1 |
| `backend/app/core/permissions.py` | `8dacfec` | 2026-11-04 | 1 |
| `backend/app/core/security.py` | `1510f9d` | 2026-11-04 | 1 |
| `backend/app/db/__init__.py` | `8dacfec` | 2026-11-04 | 1 |
| `backend/app/db/base.py` | `8dacfec` | 2026-11-04 | 1 |
| `backend/app/db/session.py` | `1510f9d` | 2026-11-04 | 1 |
| `backend/app/main.py` | `8dacfec` | 2026-11-05 | 1 |
| `backend/app/modules/__init__.py` | `8dacfec` | 2026-11-05 | 1 |
| `backend/app/modules/auth/__init__.py` | `8dacfec` | 2026-11-05 | 1 |
| `backend/app/modules/auth/models.py` | `8dacfec` | 2026-11-05 | 1 |
| `backend/app/modules/auth/repository.py` | `1510f9d` | 2026-11-05 | 1 |
| `backend/app/modules/auth/router.py` | `1510f9d` | 2026-11-05 | 1 |
| `backend/app/modules/auth/schemas.py` | `1510f9d` | 2026-11-05 | 1 |
| `backend/app/modules/auth/service.py` | `1510f9d` | 2026-11-05 | 1 |
| `backend/app/modules/users/__init__.py` | `8dacfec` | 2026-11-04 | 1 |
| `backend/app/modules/users/models.py` | `8dacfec` | 2026-11-04 | 1 |
| `backend/app/modules/users/repository.py` | `1510f9d` | 2026-11-04 | 1 |
| `backend/app/modules/users/schemas.py` | `1510f9d` | 2026-11-04 | 1 |
| `backend/app/modules/users/service.py` | `1510f9d` | 2026-11-04 | 1 |
| `backend/migrations/env.py` | `8dacfec` | 2026-11-04 | 1 |
| `backend/migrations/versions/3da0f6bf8dd1_create_refresh_tokens_table.py` | `8dacfec` | 2026-11-04 | 1 |
| `backend/migrations/versions/feee06ced45e_create_users_table.py` | `8dacfec` | 2026-11-04 | 1 |
| `backend/tests/conftest.py` | `1510f9d` | 2026-11-06 | 1 |
| `backend/tests/factories.py` | `1510f9d` | 2026-11-06 | 1 |
| `backend/tests/test_auth_api.py` | `1510f9d` | 2026-11-15 | 1 |
| `backend/tests/test_auth_concurrency.py` | `33cd514` | 2026-11-15 | 1 |
| `backend/tests/test_auth_repository.py` | `1510f9d` | 2026-11-08 | 1 |
| `backend/tests/test_auth_schemas.py` | `1510f9d` | 2026-11-08 | 1 |
| `backend/tests/test_auth_service.py` | `1510f9d` | 2026-11-09 | 1 |
| `backend/tests/test_cli.py` | `1510f9d` | 2026-11-08 | 1 |
| `backend/tests/test_config.py` | `1510f9d` | 2026-11-15 | 1 |
| `backend/tests/test_conftest.py` | `8dacfec` | 2026-11-06 | 1 |
| `backend/tests/test_database.py` | `1510f9d` | 2026-11-06 | 1 |
| `backend/tests/test_errors.py` | `1510f9d` | 2026-11-06 | 1 |
| `backend/tests/test_health.py` | `1510f9d` | 2026-11-06 | 1 |
| `backend/tests/test_logging.py` | `1510f9d` | 2026-11-08 | 1 |
| `backend/tests/test_package_layout.py` | `8dacfec` | 2026-11-06 | 1 |
| `backend/tests/test_refresh_token_model.py` | `8dacfec` | 2026-11-08 | 1 |
| `backend/tests/test_security.py` | `1510f9d` | 2026-11-08 | 1 |
| `backend/tests/test_user_model.py` | `1510f9d` | 2026-11-08 | 1 |
| `backend/tests/test_user_repository.py` | `1510f9d` | 2026-11-08 | 1 |
| `backend/tests/test_user_schemas.py` | `1510f9d` | 2026-11-08 | 1 |
| `backend/tests/test_user_service.py` | `1510f9d` | 2026-11-08 | 1 |
