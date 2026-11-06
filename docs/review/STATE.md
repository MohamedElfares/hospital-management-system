# Review state

One row per reviewed file. `/review new` compares each file against the
commit recorded here and reviews only what changed since.

Keep rows sorted by path. Delete the row when the file is deleted. A file
with no row has never been reviewed and is always in scope.

| File | Reviewed at commit | Date | Run |
|---|---|---|---|
| `backend/app/__init__.py` | `9c56300` | 2026-11-05 | 1 |
| `backend/app/api/__init__.py` | `9c56300` | 2026-11-05 | 1 |
| `backend/app/api/deps.py` | `9e21ddb` | 2026-11-05 | 1 |
| `backend/app/api/health.py` | `9c56300` | 2026-11-05 | 1 |
| `backend/app/api/router.py` | `9c56300` | 2026-11-05 | 1 |
| `backend/app/cli.py` | `9c56300` | 2026-11-05 | 1 |
| `backend/app/core/__init__.py` | `d5dc7cd` | 2026-11-04 | 1 |
| `backend/app/core/config.py` | `7d080c0` | 2026-11-04 | 1 |
| `backend/app/core/errors.py` | `d5dc7cd` | 2026-11-04 | 1 |
| `backend/app/core/logging.py` | `2127a70` | 2026-11-04 | 1 |
| `backend/app/core/permissions.py` | `fe8906c` | 2026-11-04 | 1 |
| `backend/app/core/security.py` | `fe8906c` | 2026-11-04 | 1 |
| `backend/app/db/__init__.py` | `56f211b` | 2026-11-04 | 1 |
| `backend/app/db/base.py` | `56f211b` | 2026-11-04 | 1 |
| `backend/app/db/session.py` | `56f211b` | 2026-11-04 | 1 |
| `backend/app/main.py` | `9c56300` | 2026-11-05 | 1 |
| `backend/app/modules/__init__.py` | `9c56300` | 2026-11-05 | 1 |
| `backend/app/modules/auth/__init__.py` | `b7d1692` | 2026-11-05 | 1 |
| `backend/app/modules/auth/models.py` | `b7d1692` | 2026-11-05 | 1 |
| `backend/app/modules/auth/repository.py` | `b7d1692` | 2026-11-05 | 1 |
| `backend/app/modules/auth/router.py` | `9e21ddb` | 2026-11-05 | 1 |
| `backend/app/modules/auth/schemas.py` | `b7d1692` | 2026-11-05 | 1 |
| `backend/app/modules/auth/service.py` | `605ac3b` | 2026-11-05 | 1 |
| `backend/app/modules/users/__init__.py` | `8cee6f1` | 2026-11-04 | 1 |
| `backend/app/modules/users/models.py` | `8cee6f1` | 2026-11-04 | 1 |
| `backend/app/modules/users/repository.py` | `8cee6f1` | 2026-11-04 | 1 |
| `backend/app/modules/users/schemas.py` | `75ec621` | 2026-11-04 | 1 |
| `backend/app/modules/users/service.py` | `75ec621` | 2026-11-04 | 1 |
| `backend/migrations/env.py` | `2a1b18b` | 2026-11-04 | 1 |
| `backend/migrations/versions/3da0f6bf8dd1_create_refresh_tokens_table.py` | `2a1b18b` | 2026-11-04 | 1 |
| `backend/migrations/versions/feee06ced45e_create_users_table.py` | `2a1b18b` | 2026-11-04 | 1 |
| `backend/tests/conftest.py` | `a459df1` | 2026-11-06 | 1 |
| `backend/tests/factories.py` | `a459df1` | 2026-11-06 | 1 |
| `backend/tests/test_conftest.py` | `bf31a33` | 2026-11-06 | 1 |
| `backend/tests/test_database.py` | `bf31a33` | 2026-11-06 | 1 |
| `backend/tests/test_package_layout.py` | `bf31a33` | 2026-11-06 | 1 |
