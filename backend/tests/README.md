# Tests

Backend tests, written with pytest against a real PostgreSQL database.

## Running them

```bash
uv run pytest              # the whole suite
uv run pytest -v           # one line per test, including parametrized cases
uv run pytest --cov=app    # with a coverage report
uv run pytest tests/test_health.py::test_liveness_returns_ok_while_the_database_is_unreachable   # a single test
```

## What you need first

| Requirement | How |
|---|---|
| PostgreSQL running | `docker compose up -d db` from the repository root |
| A test database | `docker compose exec db createdb -U hms hms_test`, once per machine |
| `TEST_DATABASE_URL` in `backend/.env` | `postgresql+psycopg://hms:hms@127.0.0.1:5432/hms_test` |

Without `TEST_DATABASE_URL`, every test that needs the database errors with
`TEST_DATABASE_URL is not set`, and the tests that don't need one still run. The suite
never falls back to `DATABASE_URL`, because tests write to the database they are given.

## Fixtures

All of them live in `conftest.py`, which pytest loads automatically. A test uses one by
naming it as a parameter; nothing is imported from that file.

| Fixture | Scope | What it gives you |
|---|---|---|
| `app` | test | A fresh application from `create_app()`, so dependency overrides never leak between tests |
| `client` | test | An HTTP client for that application, with `get_db` replaced by `get_test_db` |
| `get_test_db` | test | A stand-in for `get_db` that hands requests and CLI commands the test's session, ended the way the application ends one |
| `test_engine` | session | The engine for the test database, disposed of at the end of the run |
| `apply_migrations` | session | `alembic upgrade head` against the test database, in a subprocess |
| `db_session` | test | A session from the application's `SessionLocal`, inside a transaction that is rolled back when the test ends |
| `refuse_the_development_database` | session, autouse | Refuses every connection through the application's engine, so no test can reach the development database |

## How isolation works

Each test that touches the database runs inside one transaction:

1. `db_session` opens a connection and begins a transaction.
2. The session, built by the application's `SessionLocal` so it has the same options, joins
   it with `join_transaction_mode="create_savepoint"`, so a `commit()` in application code
   releases a savepoint instead of ending the transaction.
3. After the test, the transaction is rolled back — rows, schema changes and all.

Requests and CLI commands get that same session through `get_test_db`, which ends it the
way the application ends a real one:

- Before the request or command, it commits what the test set up, as that data would
  already be in the database, and expires the test's objects, so the code reads them back
  from the database, as a new session would.
- Afterwards, whether the code succeeded or failed, it rolls back whatever the code didn't
  commit, as closing a real session does.

So a forgotten `commit()` fails the test that reads the result, and what the code did
commit stays visible to the test until the test ends. A CLI test puts
`contextmanager(get_test_db)` in place of `SessionLocal`. A service test that calls a
service with `db_session` directly has no such boundary; it checks a commit by calling
`db_session.rollback()` before it asserts, as `test_the_logout_revocation_is_committed`
does. `test_conftest.py` pins this behaviour.

The application's own engine stays bound to `DATABASE_URL`, the development database, for
the whole run, so `refuse_the_development_database` refuses every connection through it
before one opens. A test that bypasses `client` or `get_test_db` meets `RuntimeError: Tests
must not connect to the development database` instead of writing there.

## Conventions

- **One behaviour per test**, named after the expected result, e.g.
  `test_wrong_method_returns_405_with_an_allow_header`.
- **A docstring on every test** describing the scenario, the expected result, and why the
  behaviour matters.
- **`pytest.mark.parametrize`** for the same logic over several inputs, with `pytest.param(...,
  id="...")` when a value is long or unreadable.
- **Assert the status code before the body**, so an unexpected response fails with a clear
  comparison instead of a `KeyError`.
- **Expected values are literals**, never recomputed with the same logic the code under test
  uses.
- **No test depends on another.** Each test sets up what it needs and leaves nothing behind,
  so it means the same run on its own, picked with `-k`, or in any order. A check that must
  run after a test has ended goes in a fixture's teardown, as
  `check_the_probe_table_is_gone_afterwards` in `test_database.py` does, rather than in a
  second test that runs next.
