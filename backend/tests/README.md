# Tests

Backend tests, written with pytest against a real PostgreSQL database.

## Running them

```bash
uv run pytest              # the whole suite
uv run pytest -v           # one line per test, including parametrized cases
uv run pytest --cov=app    # with a coverage report
uv run pytest tests/test_health.py::test_liveness_returns_ok   # a single test
```

## What you need first

| Requirement | How |
|---|---|
| PostgreSQL running | `docker compose up -d db` from the repository root |
| A test database | `docker compose exec db createdb -U hms hms_test`, once per machine |
| `TEST_DATABASE_URL` in `backend/.env` | `postgresql+psycopg://hms:hms@127.0.0.1:5432/hms_test` |

The suite refuses to run without `TEST_DATABASE_URL` rather than falling back to
`DATABASE_URL`, because tests write to the database they are given.

## Fixtures

All of them live in `conftest.py`, which pytest loads automatically. A test uses one by
naming it as a parameter; nothing is imported from that file.

| Fixture | Scope | What it gives you |
|---|---|---|
| `app` | test | A fresh application from `create_app()`, so dependency overrides never leak between tests |
| `client` | test | An HTTP client for that application, with `get_db` replaced by the test's session |
| `test_engine` | session | The engine for the test database, disposed of at the end of the run |
| `apply_migrations` | session | `alembic upgrade head` against the test database, in a subprocess |
| `db_session` | test | A session inside a transaction that is rolled back when the test ends |

## How isolation works

Each test that touches the database runs inside one transaction:

1. `db_session` opens a connection and begins a transaction.
2. The session joins it with `join_transaction_mode="create_savepoint"`, so a `commit()`
   in application code releases a savepoint instead of ending the transaction.
3. After the test, the transaction is rolled back — rows, schema changes and all.

Because `client` shares that session, a request made over HTTP and a direct query in the
test see the same data, and neither survives the test.

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

## One deliberate exception

`test_a_previous_test_left_no_table_behind` passes trivially when run on its own: it proves
that the *previous* test left nothing behind, so it only carries weight in a full run. Its
docstring says so. Every other test is independent of the order tests run in.
