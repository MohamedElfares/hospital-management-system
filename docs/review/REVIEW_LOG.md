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
  the password hash." Accepted on 2026-11-05 (you asked me to fix the
  findings with my recommendations and best practices) and added to
  `CLAUDE.md` under "Conventions", word for word. With R-026 fixed,
  sign-in, refresh, and the password change all follow it; sign-out
  revokes single tokens, so the rule doesn't cover it.
- **Stage 8's findings fixed (2026-11-05):** R-026 (`a97d21e`), R-027
  (`867a74c`), R-028 (`99c468b`), and R-029 (`0e58ac9`), written at your
  request, one commit each, each code fix with tests that fail before
  it. R-028 went into the API rather than the web-app rule first
  recommended, because plan §6's principle 7 keeps the frontend out of
  security. They change `auth/service.py` after stage 8 reviewed it at
  `605ac3b`, and `auth/repository.py` after stage 7 (`b7d1692`), so the
  next `/review new` takes those files again; `auth/router.py` changed
  before stage 9 reaches it, in one `Raises` entry. New tests landed in
  `test_auth_repository.py` (stage 16), `test_auth_service.py` (stages
  18 and 20), and `test_auth_concurrency.py` (stage 25). Each commit
  passes Ruff and the suite on its own, run like CI in a clean worktree:
  319, 320, then 327 tests, with coverage at 99.57%. R-030, a naming
  question found while fixing R-028, was settled by renaming
  `get_refresh_token_by_hash` to `get_refresh_token_by_hash_for_update`
  (`f316cc1`), your go-ahead; it changes `auth/repository.py` and
  `auth/service.py` again, and both `NAMING.md` rows show the new name.
  No finding is open.
- **Carried from stage 9:** three things in later stages' files, noticed
  while checking the router and `deps.py`. Stage 10: `create_app`'s
  docstring in `app/main.py` says importing the module no longer needs
  valid settings, but the module builds `app` when imported, and its
  imports reach `app.db.session`, which builds the engine; checked in a
  fresh process with no settings, `import app.main` raises
  `ValidationError`, as R-017 found. Stage 18: four tests in
  `tests/test_auth_service.py` name `service.login`'s return `result`,
  which stage 9 renamed `issued_tokens` in the router (shape rule).
  Stage 21: the `gated_route` fixture's docstring in
  `tests/test_auth_api.py` says every route that uses `CurrentUser` is
  exempt from the gate; it means every route that exists today, as the
  same fixture in `tests/test_logging.py` says, since none uses it yet.
  The stage 10 item is done, in `9c56300`.
- **Stage 9's findings fixed (2026-11-05):** R-035 (`331a208`), R-032
  (`040e120`), R-031 (`c565e11`), and R-033 (`412ae00`), written at your
  request ("fix them with your recommendations and best practices"), one
  commit each, each code fix with tests that fail before it; every new
  test was also run against planted defects, such as a limit one
  character off, and each defect failed a test. R-034 became issue #41,
  in Milestone 1.7. The fixes change `app/core/errors.py` after stage 1
  reviewed it at `d5dc7cd`, `users/schemas.py` after stage 6 (`75ec621`),
  `auth/schemas.py` after stage 7 (`b7d1692`), and `auth/router.py` after
  stage 9 (`9e21ddb`), so the next `/review new` takes those files again.
  The new `app/api/__init__.py` joins stage 10, and the new
  `tests/test_package_layout.py` joins stage 12. New tests landed in
  `test_errors.py` (stage 12), `test_auth_schemas.py` (stage 17), and
  `test_auth_api.py` (stages 21 and 22). Each commit passes Ruff and the
  suite on its own, run like CI in a clean worktree: 327, 328, 331, then
  336 tests, with coverage at 99.58%. No finding is open.
- **Stage 10's findings fixed (2026-11-05):** R-037 (`451e40b`), R-036
  (`0951df5`), and R-038 (`6e13eba`), written at your request ("fix them
  with your recommendations and best practices"), one commit each, in
  dependency order: the test that pins today's 503 body first, then the
  log line, then the CLI setting. Every new test was also run against
  planted defects, such as a log line written with `%s` or a traceback
  that shows local variables, and each defect failed it. R-038's guard
  test checks what reaches the screen instead of reading the setting
  back, as first recommended. The fixes change `app/api/health.py` and
  `app/cli.py` after stage 10 reviewed them at `9c56300`, so the next
  `/review new` takes them again. New tests landed in `test_health.py`
  (stage 12) and `test_cli.py` (stage 15), and plan §12 and §8.1 each
  gained a clause. Each commit passes Ruff and the suite on its own, run
  like CI in a clean worktree: 337, 338, then 339 tests, with coverage at
  99.58%. No finding is open.
- **Carried from stage 11:** two things in later stages' files. Stage 25:
  `_run_migrations` in `tests/test_auth_concurrency.py` names what
  `subprocess.run` returns `result`, as `apply_migrations` did until
  stage 11 renamed it `upgrade`. Stage 15:
  `test_create_admin_creates_an_admin_and_prints_its_email` says the
  command saves the Admin, but through `nullcontext(db_session)` it can't
  see whether the command committed (R-039); if R-039 is still open then,
  its docstring should say what the test can see. The stage 15 item is
  done, in `8c2512b`: the test now fails when the command doesn't commit,
  and its docstring says why.
- **Stage 11's findings fixed (2026-11-06):** R-039 (`8c2512b`), R-040
  (`5cb442c`), and R-041 (`9a9df67`), written at your request ("fix the
  findings with recommendations with best practices"), one commit each,
  in dependency order: the session boundary first, then the session
  options, which build on it, then the plan and the dependency. Every new
  test was also run against planted defects, such as a stand-in that
  rolls back without `finally` or a session not built by `SessionLocal`,
  and each defect failed a test. R-040 went one step beyond its
  recommendation: `get_test_db` expires the test's objects after its
  first commit, so a request reads the test's setup from the database.
  `9210b27` corrected `tests/README.md`'s claim that the suite refuses to
  run without `TEST_DATABASE_URL`, which stage 11 had corrected in
  `conftest.py`. The fixes change `tests/conftest.py` after stage 11
  reviewed it at `a459df1`, so the next `/review new` takes it again;
  `tests/test_cli.py` changed before stage 15 reaches it, and the new
  `tests/test_conftest.py` joins stage 12. Each commit passes Ruff and the
  suite on its own, run like CI in a clean worktree: 339, 344, 347, then
  347 tests, with coverage at 99.58%. No finding is open.
- **Stage 12a's findings fixed (2026-11-06):** R-044 (`61819ee`), R-043
  (`f71533e`), and R-042 (`c5066fc`), written at your request ("fix them
  with recommendations and best practices"), one commit each, in
  dependency order: first the guard that keeps tests off the development
  database, so that the tests the next two commits add can't reach it,
  then the tests of the real `get_db`, then the single test that replaces
  the order-dependent pair, with R-042's recommendation as revised on the
  second pass. The code under test didn't change, so every new test was
  run instead against broken copies, of `conftest.py` and of `get_db`,
  and each copy failed a test. The fixes change `tests/conftest.py` after
  stage 11 reviewed it at `a459df1`, and `tests/test_database.py` after
  stage 12a (`bf31a33`), so the next `/review new` takes them again;
  `tests/test_cli.py` changed in one docstring before stage 15 reaches
  it. `tests/README.md` gained the new fixture and a convention, and
  plan §13 a sentence. Each commit passes Ruff and the suite on its own,
  run like CI in a clean worktree: 348, 351, then 350 tests, with
  coverage at 99.58%, then 99.86% once `get_db` runs. No finding is open.
- **Recurring finding (stage 12b):** R-011, R-036, and R-045 are the same
  kind: a log line that plan §12 requires or a docstring promises, which
  no test captures, so it could go missing or lose its request ID
  unseen. Proposed line for `CLAUDE.md` under "Backend tests", yours to
  accept or reject: "Every log line that plan §12 requires or a docstring
  promises gets a test that captures it with `caplog` and checks its
  level, its request ID, and what it must leave out." Accepted on
  2026-11-08 (you said "yes" to both open proposals) and added to
  `CLAUDE.md` under "Backend tests", word for word. Of the five log
  lines in `app/`, three carry the request ID and have such a test: the
  request line, the readiness failure, and the 500 handler. Two carry
  none: the token-reuse alarm in `auth/service.py` and the unknown-hash
  warning in `security.py`. Stages 18 to 20, which reach the reuse
  tests, and the next `/review new`, which takes `security.py` again,
  should log them.
- **Stage 12b's findings fixed (2026-11-06):** R-045 (`5791b30`), R-046
  (`44d5731`), R-047 (`c89c3e9`), and R-048 (`33c698f`), written at your
  request ("fix the open in findings with recommendations and best
  practices"), one commit each, in ID order, since none depends on
  another. The code under test didn't change, so each new or changed
  test was run instead against the broken copies of `errors.py`,
  `health.py`, and `logging.py` that had passed the whole suite, and each
  copy failed it. R-046's test is now
  `test_liveness_returns_ok_while_the_database_is_unreachable`, and the
  single-test example in `tests/README.md` follows; R-047 strengthens the
  existing request-ID test rather than adding one beside it. The fixes
  change `tests/test_errors.py` and `tests/test_health.py` after stage 12b
  reviewed them at `d8362d5`, so the next `/review new` takes them again.
  Each commit passes Ruff and the suite on its own, run like CI in a
  clean worktree: 351 tests each time, with coverage at 99.86%, and the
  suite also passes reversed and shuffled twice. The `CLAUDE.md` line
  proposed above still waits for your answer. No finding is open.
- **Carried from stage 12c:** three things in files this run has already
  passed or reaches later. For the next `/review new` of
  `app/core/logging.py`, due anyway since it changed after stage 2:
  `configure_logging`'s docstring says `force=True` means a second call
  "never adds a second handler that would print every line twice", but
  `basicConfig` without `force` adds no second handler either: once the
  root logger has one, it does nothing at all (Python 3.13.15's source),
  so what `force` buys is that a later call, such as each test's
  `create_app`, still applies its level and format. And
  `request_context_middleware`'s docstring says "Starlette already drops
  line breaks and tabs": it is Python's `urlsplit`, which Starlette parses
  `request.url` with, that removes tabs, carriage returns, and line feeds
  (probed). For stage 21: the `user` fixture in `tests/test_auth_api.py`
  says it is "flushed, not committed, so the test's rollback removes it",
  the reasoning stage 12c corrected in `tests/test_logging.py`:
  `get_test_db` commits the setup before each request, and the rollback
  removes it either way.
- **Stage 12c's findings fixed (2026-11-08):** R-049 (`1a1560c`), R-050
  (`73f3165`), and R-051 (`72244c0`), written at your request ("fix the
  open in findings with recommendations and best practices"), one commit
  each, in ID order, since none depends on another. The code under test
  didn't change, so each new or changed test was run instead against the
  broken copies of `logging.py` that had passed the whole suite, and each
  copy failed it. R-049's test now pins both of `_resolve_request_id`'s
  branches that generate an ID, and R-050's also checks the line format,
  one step beyond its recommendation. The fixes change
  `tests/test_logging.py` after stage 12c reviewed it at `0494955`, so the
  next `/review new` takes it again. Each commit passes Ruff and the suite
  on its own, run like CI in a clean worktree: 351, 352, then 352 tests,
  with coverage at 99.86%, and with R-050's fixture in place the suite
  also passes reversed, shuffled twice, and at `LOG_LEVEL=INFO`. The
  `CLAUDE.md` line proposed in stage 12b still waits for your answer. No
  finding is open.
- **Probed in stage 13, no finding:** four broken copies of
  `security.py` pass the whole suite but were left alone, because none is
  a defect a client can reach. `decode_access_token` requiring only
  `exp`, or skipping the check that `iat` isn't in the future: a token
  without `sub` or `iat`, or issued in the future, can only be signed
  with `JWT_SECRET_KEY`, and whoever holds the key can sign any claims.
  `_DUMMY_HASH` made from a known password: harmless while
  `verify_login_password` answers False on its own, which R-053's second
  test would pin. The warning logging pwdlib's exception: no stored value
  reaches the log, which is R-057's point.
- **Recurring finding (stage 13):** R-052, R-053, R-054, and R-056 are
  the same kind: a safeguard for passwords or tokens that a docstring or
  the plan promises, and that no test fails without. The guard line
  `CLAUDE.md` gained in stage 2 covers secrets and personal data in
  responses and logs, and settings at startup, but not these. Proposed
  replacement for that line, yours to accept or reject: "Every guard that
  keeps secrets or personal data out of responses and logs, protects
  passwords or tokens (hashing settings, the unknown-email dummy check,
  token and cookie rules), or stops startup on a bad setting, gets a test
  that fails when the guard is removed." Accepted on 2026-11-08 (you said
  "yes" to both open proposals), with the stage 12b line, and put in
  `CLAUDE.md` in place of the stage 2 line, word for word.
- **Stage 13's findings fixed (2026-11-08):** R-052 (`36919e6`), R-053
  (`31b2445`), R-054 (`d00c08f`), R-055 (`47151a4`), R-056 (`276eeaf`),
  R-057 (`6d57f19`), R-058 (`e8e09ae`), R-059 (`fc35fae`), and R-060
  (`903a8c5`), written at your request ("fix the open in findings with
  recommendations and best practices"), one commit each, in ID order,
  since none depends on another: the test-only fixes first, then the
  docstring, then the two changes of behaviour, each with tests that fail
  before it. Every new or changed test was run against broken copies of
  the code it pins, and each copy failed it. Two steps differ from the
  logged recommendations: R-055's access token test uses 9 minutes, since
  a copy that reads the refresh setting passes a 7-minute test, and
  R-059 adds a ligature case that pins NFC over NFKC. `73515e7` brought
  `tests/test_security.py`'s module docstring up to the fixes. R-058
  raises the password minimum to 15, and R-059 puts every password in
  Unicode NFC, so `app/core/security.py`, `users/schemas.py`,
  `auth/schemas.py`, `auth/router.py`, and `cli.py` changed after their
  stages reviewed them (3, 6, 7, 9, and 10), as did
  `tests/test_security.py` after stage 13 (`cc8e73f`) and
  `tests/factories.py` after stage 11 (`a459df1`), so the next
  `/review new` takes them again. `test_user_schemas.py` (stage 14),
  `test_cli.py` and `test_user_service.py` (stage 15),
  `test_auth_schemas.py` (stage 17), `test_auth_service.py` (stages 18
  and 20), and `test_auth_api.py` (stage 21) changed before their stages
  reach them. Each commit passes Ruff and the suite on its own, run like
  CI in a clean worktree: 353, 355, 356, 356, 358, 358, 358, 361, 361,
  then 361 tests, with coverage at 99.86%, and the suite also
  passes reversed, shuffled twice, and at `LOG_LEVEL=INFO`. The
  `CLAUDE.md` lines proposed in stages 12b and 13 still wait for your
  answer. No finding is open.
- **Carried to stage 17 (from stage 14):** `tests/test_auth_schemas.py`
  has the pattern stage 14 renamed in `tests/test_user_schemas.py`: its
  helper `valid_password_change` returns the dict the tests call `data`,
  and the `PasswordChange` built from it is `password_change`. Under
  `NAMING.md`'s new `values` row, your choice in stage 14, they become
  `_valid_values`, `values`, and `data`.
- **Stage 14's findings fixed (2026-11-08):** R-061 (`b85b6ba`), R-062
  (`74098c0`), R-063 (`d2be109`), and R-064 (`b8e5e2a`), written at your
  request ("fix the open in findings with recommendations and best
  practices"), one commit each, in ID order, since none depends on
  another. The code under test didn't change, so each new test was run
  instead against the broken copy that had passed the whole suite, and
  each copy failed it: the mixin without `onupdate`, the name check run
  before the stripping, and, for R-064's new test, an email rule that
  refuses a display name. Two steps go beyond the recommendations:
  R-061's test first checks that the row really holds the backdated
  time, so it can't pass vacuously, and R-062's adds a Windows line
  ending. R-063 changes no value: `tests/test_security.py`'s whole AST is
  identical. R-064 keeps the display-name form and documents it, and plan
  §8.1 now says sign-in counts an account's attempts under the
  normalized email, for IAM-3 (#16). The fixes change
  `tests/test_user_model.py` and `tests/test_user_schemas.py` after
  stage 14 reviewed them at `442fa6b`, so the next `/review new` takes
  them again, with `tests/test_security.py`, `users/schemas.py`, and
  `users/service.py`, which were due already. Each commit passes Ruff
  and the suite on its own, run like CI in a clean worktree: 362, 365,
  365, then 366 tests, with coverage at 99.86%, and the suite also passes
  reversed, shuffled twice, and at `LOG_LEVEL=INFO`. No finding is open.
- **Carried to stage 16 (from R-061):** `TimestampMixin`'s docstring says
  `onupdate` also reaches a bulk `update()`, such as the one in
  `revoke_all_refresh_tokens_for_user`. R-061's test covers only an
  update through the ORM, so stage 16 should check whether any test sees
  that revocation move `refresh_tokens.updated_at`. Done in stage 16: no
  test does, and R-074 records it.
- **Probed in stage 15, no finding:** a copy of the users service whose
  `get_user_by_id` takes the row lock, through the repository's locking
  lookup, passes the whole suite, but was left alone. Every request's
  authentication would then lock its user's row until the request ends,
  so one user's parallel requests would wait for each other, but no
  docstring promises that the plain lookup takes no lock. A test that
  reads the statement for `FOR NO KEY UPDATE` could pin it if that ever
  matters.
- **Carried to stage 16 (from stage 15):** `tests/test_user_repository.py`
  names what a lookup returns `database_user` in two tests and `result` in
  three. Under `NAMING.md`'s new `found_<thing>` row they become
  `found_user`, as stage 15 renamed them in `tests/test_user_service.py`.
  Its `found`, the boolean `exists_active_admin` returns, falls under the
  boolean rule instead. Done in `184ab2c`: `found_user`, and
  `has_active_admin` for `found` and for `admin_exist`, the same boolean
  under another name.
- **Stage 15's findings fixed (2026-11-08):** R-065 (`5906bf8`), R-066
  (`9074852`), R-067 (`dca6417`), R-068 (`00d32ba`), and R-069
  (`8133e37`), written at your request ("fix the open in findings with
  recommendations and best practices"), one commit each, in ID order,
  since none depends on another. The code under test didn't change, so
  each new or changed test was run instead against the broken copies
  that had passed the whole suite, and each copy failed it. One step
  differs from the logged recommendations: R-067's tests compare the
  whole of `result.stderr` with the one line expected, rather than
  finding the message there and not on stdout, which also refuses
  Pydantic's whole error printed beside it. R-066 and R-068 renamed the
  tests they strengthened, so that each name states what its test now
  checks. R-069's open row, recorded in `f7c48df`, showed the
  recommended escapes as the raw characters themselves, because they were
  turned into characters while the row was being written; its settled row
  has them as committed. The fixes change `tests/test_cli.py` and
  `tests/test_user_service.py` after stage 15 reviewed them at
  `acf3765`, so the next `/review new` takes them again. Each commit
  passes Ruff and the suite on its own, run like CI in a clean worktree:
  367 tests each time, with coverage at 99.86%, and the suite also passes
  reversed, shuffled twice, and at `LOG_LEVEL=INFO`. No finding is open.
- **Environment (stage 16):** `backend/.venv` was synced with
  `uv sync --locked` to the lock merged from `main` in `4f4b381`, as the
  commit hooks' `uv run` would have done at the first commit. SQLAlchemy
  2.1.6, pytest 9.2.0, Ruff 0.17.3, Typer 0.27.3, httpx2 2.16.0,
  pydantic-settings 2.16.2, and Alembic 1.20.1 replace the versions that
  earlier stages name as installed. The claims stages 7 and 14 checked on
  SQLAlchemy 2.1.1 about the bulk `UPDATE` were checked again on 2.1.6,
  and they still hold.
- **Probed in stage 16, no finding:** five broken copies pass the whole
  suite but were left alone, because none changes what a client can see
  today. The users row lock taken `FOR UPDATE` instead of
  `FOR NO KEY UPDATE`, and the token lock by hash taken
  `FOR NO KEY UPDATE` instead of `FOR UPDATE`: the difference is whether
  another transaction's insert of a row that refers to the locked one
  must wait, and today every such insert, a refresh token or a
  `replaced_by_id`, comes from the transaction that holds the lock. The
  user lock's choice will matter once other modules insert rows that
  refer to users while auth holds the lock. A `create_refresh_token`
  that flushes: the service flushes or commits right after it. A
  `revoke_all_refresh_tokens_for_user` that doesn't keep the session in
  step, or that commits: no caller reads a token after it, and both
  callers commit right after it, except that a password change would
  then commit its revocation before it issues the new token. That
  repositories never commit is a layer rule this review checks, and both
  repositories keep it.
- **Stage 16's findings fixed (2026-11-08):** R-070 (`1f58fa7`), R-071
  (`f4dd26a`), R-072 (`b6bfdc9`), R-073 (`9a584e7`), and R-074
  (`fabac35`), written at your request ("fix the open in findings with
  recommendations and best practices"), one commit each, in ID order,
  since none depends on another. The code under test didn't change, so
  each new or changed test was run instead against the broken copies
  that had passed the whole suite, and each copy failed it. One step
  differs from the logged recommendations: R-073's password change runs
  with `lock_timeout` at 1 s, as the failed sign-in test's does, so any
  wait fails it at once rather than a timer deciding. R-071 adds a
  sentence on `=` to `get_user_by_email`'s docstring, and R-074 a pointer
  to R-061's test docstring; neither changes code. R-070 renames the
  active-Doctor test it parametrizes, so that its name says what it now
  checks. The fixes change `tests/test_user_repository.py` and
  `tests/test_auth_repository.py` after stage 16 reviewed them at
  `f8b131a`, and `app/modules/users/repository.py` and
  `tests/test_user_model.py`, which the next `/review new` takes anyway;
  `tests/test_auth_service.py` (stage 19) and
  `tests/test_auth_concurrency.py` (stage 25) changed before their stages
  reach them. Two commit messages were amended while still local, one to
  keep a test name whole and one to drop a stray draft line; the trees
  are unchanged. Each commit passes Ruff and the suite on its own, run
  like CI in a clean worktree: 374, 376, 380, 381, then 382 tests, with
  coverage at 99.86%, and the suite also passes reversed, shuffled twice,
  and at `LOG_LEVEL=INFO`. No finding is open.
- **Probed in stage 17, no finding:** every broken copy of the refresh
  token model, each changed in the model and the migration together so
  that `alembic check` would see no drift, fails at least one test. All
  but one fail a test in `tests/test_refresh_token_model.py`; the other,
  a `revoked_at` without a time zone, fails four tests in
  `tests/test_auth_repository.py`, which compare the revocation time read
  back with the one written. A database default on `revoked_at` or
  `replaced_by_id`, added in a migration alone, can't reach a token the
  application saves either, because SQLAlchemy writes NULL into both
  columns on every insert (probed).
- **Stage 17's findings fixed (2026-11-08):** R-075 (`774b302`) and
  R-076 (`02bf551`), written at your request ("fix the open findings with
  recommendations and best practices"), one commit each, in ID order,
  since neither depends on the other. The code under test didn't change,
  so each new or changed test was run instead against the broken copies
  that had passed the whole suite, and each copy failed it. One step goes
  beyond the recommendations: R-075 adds a password change through the
  API with spaces around both passwords, because copies of the auth
  service that strip either password in `change_password` passed the
  whole suite and both recommended tests. While fixing R-075, a
  `create-admin` that strips the typed password passed the whole suite
  too; it is the same gap at account creation, which R-075 left out, so
  it was logged as R-077 and fixed in `203eaf1` at your go-ahead
  ("yes"): a CLI test types a password with a space at each end and
  checks the saved hash against it as typed. The fixes change
  `tests/test_auth_schemas.py` after stage 17 reviewed it at `f46a105`,
  and `tests/test_cli.py` after stage 15 (`acf3765`), so the next
  `/review new` takes them again; `tests/test_auth_api.py` (stages 21 and
  23) changed before its stages reach it. Each commit passes Ruff and the
  suite on its own, run like CI in a clean worktree: 385, 387, then 388
  tests, with coverage at 99.86%, and the suite also passes reversed,
  shuffled twice, and at `LOG_LEVEL=INFO`. No finding is open.
- **Probed in stage 18, no finding:** four broken copies of `login` and
  `IssuedTokens` pass the whole suite but were left alone, because none
  changes what a client can see. A `login` that checks `is_active` only
  after the row lock: the password is still checked first and the same
  error follows, so only someone who knows a deactivated account's
  password can make it take the lock. One that reads the clock twice,
  for the sign-in time and for the expiry: the two would differ by
  microseconds, although a comment says they "agree exactly", and
  nothing reads them together. An `IssuedTokens` that isn't frozen:
  nothing assigns to one after it is built. And one with a `__str__`
  that prints both tokens: the guard `CLAUDE.md` asks a test of is
  `field(repr=False)`, which the repr test pins, and that test's
  docstring now says it reads `repr`, which `str()` falls back to only
  while the class defines no `__str__`.
- **Carried to stage 19 (from stage 12b):** the reuse alarm's log line,
  which the stage 12b note leaves to stages 18 to 20, is checked by the
  reuse tests in part 2 of `tests/test_auth_service.py`. Part 1, the
  constants, fixtures, helpers, and sign-in tests, has no log line, and
  R-081 records that none of its tests captures what a sign-in logs.
  Done in stage 19: the line carries no request ID, and R-087 records
  it.
- **Stage 18's findings fixed (2026-11-08):** R-078 (`db17080`), R-079
  (`108f560`), R-080 (`3c86891`), and R-081 (`e9912ee`), written at your
  request ("fix the open findings with recommendations and best
  practices"), one commit each, in ID order, since none depends on
  another. The code under test didn't change, so each new or changed test
  was run instead against the broken copies that had passed the whole
  suite, and each copy failed it. Three steps go beyond the
  recommendations: R-078 shares its spy through a new fixture,
  `password_check_calls`, which the unknown-email test now uses too;
  R-079 compares the status as well, because a copy that raised a
  subclass with status 403 passed the recommended checks; and R-081 adds
  the same check through the API, because copies of the sign-in route
  that logged a secret passed the service test. R-080 renames the test
  it strengthens, so that its name says what it now checks; its commit
  message was amended while still local, to keep that name whole, and
  the tree is unchanged. Each commit passes Ruff and the suite on its
  own, run like CI in a clean worktree: 390, 390, 390, then 392 tests,
  with coverage at 99.86%, and the suite also passes reversed, shuffled
  twice, and at `LOG_LEVEL=INFO`. Run against the fixed suite, all 12
  copies the fixes target fail it: the 9 behind the findings, the status
  copy, and the two route copies. No finding is open.
- **Carried to stage 20 (from the stage 18 fixes):** the fixes change
  part 1 of `tests/test_auth_service.py` after stage 18 reviewed it at
  `360f3f1`, and the file gets its `STATE.md` row only when stage 20
  ends. Record that row at `360f3f1`, so that the next `/review new`
  takes the fixed tests in part 1 again, as it takes every file a fix
  changed after its stage. `tests/test_auth_api.py` changed before stage
  21, which reaches the new API test with the rest of the sign-in tests.
  Done in stage 20: the row is at `360f3f1`.
- **Probed in stage 19, no finding:** eight broken copies of
  `get_authenticated_user` and `refresh` pass the whole suite but were
  left alone, because none changes what a client can see. A
  `get_authenticated_user` that commits: nothing is pending when it
  runs. A refresh that refuses only a `None` cookie, not an empty one: an
  empty value hashes to a value no row has, and the lookup refuses it.
  One without its check for an unknown token: SQLAlchemy 2.1.6's
  `session.get` answers `None` for a `None` ID, with a warning that this
  "may raise an error in a future release", and the token lookup then
  refuses the cookie, so for now the check spares only that warning and
  one query. An
  alarm line that adds the token's hash: the hash can't be used to
  refresh, and R-087's recommended test, which compares the whole line,
  would catch it. An alarm that records the rotated token's old
  revocation time for the sessions it ends, rather than the time of the
  alarm: the sessions still end. A refusal of a token revoked without
  rotation that revokes it again, with a new time, and commits: no other
  session ends, and only that token's recorded time moves, which sign-out
  guards against with a test of its own. A refresh that checks the
  account before the expiry: both refuse quietly and write nothing. And
  an expiry check with `<` for `<=`: a token works one microsecond longer,
  at the instant it expires, which no client can aim at.
- **Recurring finding (stage 19):** R-037, R-079, and R-083 are the same
  kind: an error that must not reveal which check failed, or why, tested
  on only part of what the client receives, so a copy that puts the
  reason in the code, the details, or the message passed. Proposed line
  for `CLAUDE.md` under "Backend tests", yours to accept or reject:
  "Every error that must not reveal which check failed, or why, such as a
  failed sign-in, a rejected token, or a failed readiness check, gets a
  test that compares the whole error: its status, code, message, and
  details." Accepted on 2026-11-09 (you said "fix the still waiting with
  recommendations and best practices") and added to `CLAUDE.md` under
  "Backend tests", with one change: the test is "for each check that
  raises it", since R-079's and R-083's broken copies each gave only one
  check an error of its own, and both fixes compare the whole error in
  every case. What it flags today are refusals that only a race reaches,
  in `tests/test_auth_concurrency.py`, which stage 25 reaches: a sign-in
  refused because its account changed during the password check, and a
  refresh refused because its owner was deleted while it waited, are
  checked by class only, and a password change refused because its
  account was deactivated or deleted after loading, by message only.
  Copies that give the sign-in refusal a message of its own, or the
  other two details of their own, pass all 405 tests (probed).
- **Carried from stage 19:** R-087's recommended test belongs in
  `tests/test_auth_api.py`, with the refresh tests stage 22 reaches. The
  module docstring of `tests/test_auth_service.py` now has a paragraph
  for each part, and stage 20 should bring part 3's up to what its tests
  check, as stage 19 did for part 2's. Stage 19 also reviewed
  `test_a_token_revoked_without_rotation_is_refused_quietly`, a refresh
  test that sits among part 3's tests, so stage 20 can leave it. The
  R-087 item is done, in `0bd0039`; stage 22 reviews the new test with
  the other refresh tests.
- **Stage 19's findings fixed (2026-11-09):** R-082 (`f07a725`), R-083
  (`3d6bce8`), R-084 (`5234c00`), R-085 (`d66a2be`), R-086 (`bca7f38`),
  and R-087 (`0bd0039`), written at your request ("fix the open findings
  with recommendations and best practices"), one commit each, in ID
  order: R-086's test compares its error with R-083's helper, and no
  other fix depends on another. Only R-087 changes the code under test,
  so each new or changed test was run against the broken copies that had
  passed the whole suite, and each copy failed it: R-082's in the slow
  run that had shown its gap, and R-087's against the old line and
  against broken copies of the new one. One step goes beyond the
  recommendations: R-083's helper replaces the message-only check in all
  nine tests that expect the generic token error, not only the five the
  finding named. R-087 puts the request ID in the alarm's line in
  `app/modules/auth/service.py`, which the next `/review new` takes
  anyway, and adds a clause to plan §8.1; its test lands in
  `tests/test_auth_api.py` before stage 22 reaches it. The fixes change
  part 2 of `tests/test_auth_service.py` after stage 19 reviewed it at
  `ab8f47d`, and the file's `STATE.md` row, due at `360f3f1` when stage
  20 ends, already makes the next `/review new` take the whole file
  again. Each commit passes Ruff and the suite on its own, run like CI in
  a clean worktree: 392, 392, 393, 394, 395, then 396 tests, with
  coverage at 99.86%, and the suite also passes reversed, shuffled twice,
  and at `LOG_LEVEL=INFO`. Run against the fixed suite, all 25 copies the
  fixes target fail it. The `CLAUDE.md` line proposed in stage 19 still
  waits for your answer. No finding is open.
- **Probed in stage 20, no finding:** nine broken copies of `logout`,
  `change_password`, and the password-change gate pass the whole suite
  but were left alone, because none changes what a client can see. A
  `logout` that commits when it revokes nothing: nothing is pending then.
  One that returns early only for a missing cookie, not an empty one: an
  empty value hashes to a value no row has, and the lookup finds nothing.
  One that locks the user's row first: it would take the locks in the
  order refresh and a password change take them, so it could only make a
  sign-out wait for them. A refused change with `details` of its own: its
  message already says which check failed, as the API means it to. A
  password change whose revocations read the clock a few microseconds
  after the new expiry's reading, although
  `revoke_all_refresh_tokens_for_user`'s docstring says both come from
  one reading, the kind of copy stage 18 left as a note for sign-in. One
  that checks the current password against `user` rather than the locked
  copy: they are one object, since the locked lookup returns the
  session's own copy, refreshed (probed, through the API too). One that
  changes other accounts' hashes in raw SQL: the test of other accounts
  reads the session's copy, as its docstring now says, and no realistic
  change writes raw SQL there. A gate that gives its 403 `details` of its
  own, and one that also refuses an inactive user, who never reaches it.
  And, probed on today's code, a sign-out with a cookie rotated twice, A
  to B to C, leaves C working: sign-out follows one link, as R-028
  decided, and the second rotation needs the browser to have stored B
  and refreshed again before the sign-out, sent earlier with A, reaches
  the server, since a sign-out that waits for A's lock gets it when the
  first refresh commits and locks B at once.
- **Recurring finding (stage 20):** R-066, R-081, and R-093 are the same
  kind: a use case or command that handles a password or a token, with
  no test that captures what it logs or prints, so a copy that wrote the
  secret out passed. Proposed line for `CLAUDE.md` under "Backend tests",
  yours to accept or reject: "Every use case, route, or command that
  takes or issues a password or a token gets a test that captures what it
  logs, down to DEBUG, and what it prints, and finds none of those
  values." The line proposed in stage 19 still waits for your answer too.
  Accepted on 2026-11-09, with the stage 19 line, and added to
  `CLAUDE.md` under "Backend tests", with three changes: request
  dependencies join the list, since the bearer token is taken by
  `get_current_user_allowing_password_change` in `app/api/deps.py`, not
  by the routes that use it; activation codes join passwords and tokens,
  as in the security rules; and the test also finds no password hash the
  code reads or writes, as R-081's and R-093's tests already check. What
  it flags today, probed against all 405 tests: copies that log the
  refresh cookie or the new refresh token at DEBUG, in `refresh` or in
  its route, pass, and so do copies of `create-admin` and of the users
  service's `create_user` that log the typed password at WARNING. A copy
  of the bearer-token dependency that logs the presented token at DEBUG
  fails only the API password change test, and only by chance: the
  change's new access token, signed in the same second, is the same
  string, because two tokens with the same claims are identical. Stage
  22 reaches the refresh and `/auth/me` API tests, and the next
  `/review new` takes `tests/test_auth_service.py`, `tests/test_cli.py`,
  and `tests/test_user_service.py` again, since fixes changed each after
  its stage.
- **Carried from stage 20:** three things in files this run has passed or
  reaches later. For the next `/review new` of
  `app/modules/auth/service.py`, due anyway since it changed after stage
  8: `change_password`'s docstring says that after the lock "everything
  after works on that copy, not on `user`, which the request loaded
  earlier", but the two are one object, since `get_user_by_id_for_update`
  returns the session's own copy of the account, refreshed from the
  locked row (probed, through the API too); what the lock buys is the
  refreshed values, not a second object. For stages 22 and 23: R-093's API
  tests, and R-091's case for `REFUSED_PASSWORD_CHANGES`, belong in
  `tests/test_auth_api.py`. And R-088's third test,
  `test_a_token_revoked_without_rotation_is_refused_quietly`, is the
  refresh test stage 19 reviewed among part 3's, so its fix changes part
  2 again, which the file's `STATE.md` row at `360f3f1` already sends to
  the next `/review new`. The two items for `tests/test_auth_api.py` are
  done, in `bb859ca` and `c57e171`; stages 22 and 23 review them with the
  tests around them.
- **Stage 20's findings fixed (2026-11-09):** R-088 (`bd86b0d`), R-089
  (`95630e2`), R-090 (`eda0a6f`), R-091 (`bb859ca`), R-092 (`390bb66`),
  and R-093 (`c57e171`), written at your request ("fix the open findings
  with recommendations and best practices then commit and push"), one
  commit each, in ID order: R-089's check of the rotated token's row goes
  into the test whose alarm check R-088 changes, and no other fix depends
  on another. No fix changes the code under test, so each new or changed
  test was run against the broken copies that had passed the whole
  suite, and each copy failed it, as did eight more written for the
  fixes: the alarm logged at WARNING by a rotated sign-out and by the
  quiet refusal, and at CRITICAL in each of R-088's three cases, a
  sign-out that drops the rotated token's link (R-089), a change that
  commits after the revocation (R-090), and a route that logs the new
  hash (R-093). Steps beyond the recommendations: R-090's test sets the
  forced-change flag itself and expects the error to name the unique
  token hash; R-091's case also goes into `REFUSED_PASSWORD_CHANGES`, as
  the finding offered, and plan §8.1 now says the current password is
  checked first; R-093's API sign-out test checks that the cookie reached
  the route, and its password change test reads the new hash back, so it
  catches the copy that logs it. The fixes change parts 2 and 3 of
  `tests/test_auth_service.py` after stages 19 and 20 reviewed them, and
  the file's `STATE.md` row at `360f3f1` already makes the next
  `/review new` take the whole file again. Each commit passes Ruff and
  the suite on its own, run like CI in a clean worktree: 396, 397, 398,
  400, 401, then 405 tests, with coverage at 99.86%, and the suite also
  passes reversed, shuffled twice, and at `LOG_LEVEL` INFO and DEBUG. Run
  against the fixed suite, all 25 copies the fixes target fail it. The
  `CLAUDE.md` lines proposed in stages 19 and 20 still wait for your
  answer. No finding is open.
- **Probed in stage 21, no finding:** three broken copies pass the whole
  suite but were left alone, because none tells a caller anything about
  an account or changes what a correct client gets. A `login` that
  refuses text that isn't an address, such as one with a NUL, before the
  lookup and the password check, with the very same error: no account
  can have such an email, so the quicker answer tells the caller only
  what they typed; with details of its own it is R-097. A `LoginForm`
  without `grant_type`'s pattern: a sign-in that names another grant
  type would get tokens rather than the 422 the form's docstring
  promises, but the API reads only the email and the password and offers
  no other grant. And one whose password loses `format: password`: only
  the OpenAPI schema changes, so Swagger UI's Authorize form would show
  the password as it is typed; no test reads the schema until Milestone
  2.1 commits `frontend/openapi.json` and its contract check.
- **Recurring finding (stage 21):** R-011, R-019, and R-096 are the same
  kind: personal data that could reach a log, a query string's name and
  phone, a typed email in a database error, or a typed email at sign-in,
  with no test that would notice. The guard line `CLAUDE.md` gained in
  stages 2 and 13 asks for a test of a guard that keeps personal data
  out of logs, and stage 20's line covers passwords, tokens, and
  activation codes, but no line asks a test to look for the personal
  data a use case takes, which plan §12 keeps out of logs, and which
  patients' records will hold from Milestone 1.3 on. Proposed line for
  `CLAUDE.md` under "Backend tests", yours to accept or reject: "Every
  use case, route, or command that takes personal data, such as an
  email, a name, or a patient's details, gets a test that captures what
  it logs, down to DEBUG, and finds none of it." It leaves out what a
  command prints, since `create-admin` prints the new Admin's email by
  design (plan §8.1). What it flags today, probed against all 405 tests:
  sign-in (R-096), a users service `create_user` that logs the new
  account's email and name, and a `create-admin` that logs the typed
  email, since neither `tests/test_user_service.py` nor
  `tests/test_cli.py` captures a log record; the next `/review new`
  takes both files again. Accepted on 2026-11-09 (your "yes") and added
  to `CLAUDE.md` under "Backend tests", word for word. R-096's fix,
  `466360c`, has since given sign-in such a test; the users service's
  `create_user` and `create-admin` still have none, for that
  `/review new`, since neither those files nor the code they test has
  changed since this stage.
- **Carried to stages 22 and 23 (from stage 21):** four things in the
  parts those stages reach. R-094's kind: the API tests of refresh,
  sign-out, and the password change capture no printed output either.
  R-095's kind, for stage 23: `test_an_invalid_body_is_a_validation_error`
  says a rejected password "can't end up in logs" but reads only the
  response, and both of R-095's copies of the validation handler log a
  refused change's new password, the one that logs the body the real
  current password too, while all 405 tests pass (probed). R-097's kind,
  for stage 22: the `/auth/me`, refresh, and sign-out tests of a 401
  compare the code and the message at most, R-083's gap through the
  API. And two names in part 2: `test_me_without_a_token_is_the_standard_401`
  and `test_me_rejects_an_unusable_authorization_header` call the error
  object `body`, where the rest of the file says `error`, and
  `test_me_accepts_the_access_token_from_login` calls a response
  `login`, where the rest say `login_response`. R-098 already lists the
  status checks of parts 2 and 3, so a fix for it changes them before
  their stages.
- **Stage 21's findings fixed (2026-11-09):** R-094 (`b32eaf5`), R-095
  (`e503260`), R-096 (`466360c`), R-097 (`0951ec3`), R-098 (`fd773a7`),
  and R-099 (`7e47579`), written at your request ("fix the open findings
  with recommendations and best practices then commit and push"), one
  commit each, in ID order: R-094 to R-096 change the same two logging
  tests, each on top of the one before, and R-097 puts the status first
  in its three tests, so R-098 reorders the other 19. R-099 is the one
  fix that changes the code under test: `app/core/security.py` gains
  `forbid_caching`, which the three token routes in
  `app/modules/auth/router.py` call, so the next `/review new` takes
  both files again; the three routes' descriptions are the only OpenAPI
  change. Steps beyond the recommendations: the logging tests name each
  value they find and where, never the value; two more broken copies, a
  validation handler that logs the form without its failed fields and a
  `login` that logs only an unknown email, show why each refused form
  and the unknown email are needed; R-098 also checks the count of
  `Set-Cookie` headers before it reads the first one; and R-099's test
  was run against seven broken copies of the fix. The fixes change parts
  2 and 3 of `tests/test_auth_api.py` before stages 22 and 23 review
  them, which they will with the tests around them, the new
  `test_every_token_response_forbids_caching` in part 2 included, and
  part 1 of `tests/test_auth_service.py` after stage 18 reviewed it,
  which the file's `STATE.md` row at `360f3f1` already sends to the next
  `/review new`. Carried to stages 22 and 23: two tests drop a setup
  response unread, the sign-in in
  `test_logout_without_an_access_token_is_the_standard_401` and the
  password change in `test_only_the_new_password_signs_in`, so a failed
  setup shows up only at a later status. Each commit passes Ruff and the
  suite on its own, run like CI in a clean worktree: 405 tests five
  times, then 406, with coverage at 99.86%, and the final suite also
  passes reversed, shuffled twice, and at `LOG_LEVEL` INFO and DEBUG.
  Run against the fixed suite, all 23 copies the fixes target fail it,
  as do the two controls. The `CLAUDE.md` line proposed in stage 21
  still waits for your answer. No finding is open.
- **Stage 22's carried items:** R-094's kind for refresh and sign-out
  is R-100 and R-101, with the copies stage 20's probe found for
  refresh's DEBUG lines; R-097's kind is R-102; the two names are
  renamed in `7a5cb76`; and the sign-out test's setup sign-in left
  unread is R-103. R-087's test, R-093's API sign-out test, and R-099's
  `test_every_token_response_forbids_caching` were reviewed with the
  tests around them: R-099's needed no change, R-087's docstring now
  says its capture holds only WARNING and above, and R-093's what it
  can't see.
- **Probed in stage 22, no finding:** three broken copies pass the whole
  suite but were left alone. A refresh route that sets its cookie
  itself, without `set_refresh_cookie`, and with neither `Max-Age` nor
  `Secure`: the cookie would end with the browser session, and in
  production travel over plain HTTP, but the route calls the helper,
  whose flags `tests/test_security.py` pins in and out of production
  and whose lifetime the sign-in cookie test pins, and R-056 settled
  that the API tests can check the cookie as text because those tests
  pin the helpers; the refresh cookie test's docstring now says why it
  leaves `Max-Age` to them. And a sign-out route whose dependency skips
  the active check, or also accepts an expired access token: the
  route's docstring says it needs a valid access token, and plan §13's
  checklist names both cases for every endpoint, but either copy only
  lets a token's own user end a session of their own, since `logout`
  revokes only that user's tokens, and the current-user tests pin the
  dependency the real route shares with them.
- **Recurring finding (stage 22):** R-048, R-098, and R-103 are the same
  kind: a test that reads a response's body, cookies, or headers before
  asserting its status, or never asserts a setup response's status,
  although `tests/README.md` says to assert the status first, so an
  unexpected response fails at a `KeyError` or at a later assertion that
  points at the wrong step. Proposed line for `CLAUDE.md` under "Backend
  tests", yours to accept or reject: "Every test asserts each
  response's status before it reads the response's body, cookies, or
  headers, setup responses included." What it flags today, besides
  R-103's two tests of this part: part 3's
  `test_only_the_new_password_signs_in`, which stage 23 reaches, and two
  tests in `tests/test_errors.py`, both listed in R-103.
- **Carried to stage 23 (from stage 22):** five things in part 3.
  R-101's kind for the password change: its API logging test reads no
  printed output, and it looks only for the access token the change
  returned, not the one it sent, which is the same string only when
  both were signed in the same second (probed). R-102's kind: the
  change's two 401 tests, the gated route's two 401 tests, and its 403
  test compare the code, and the 403's message, at most. R-103's
  `test_only_the_new_password_signs_in`. The refresh cookie note for
  `test_change_password_sets_a_new_refresh_cookie`, which reads neither
  `Max-Age` nor `Secure` either. And a name: part 3 calls sign-in
  responses `old_login`, `new_login`, `phone_login`, and `laptop_login`,
  where parts 1 and 2 say `login_response`.

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
- [x] 9. auth: router and request dependencies — `app/modules/auth/router.py`, `app/api/deps.py` (428 lines when planned, 476 after the docs) — refactor: `20d8b7b` (the sign-in route's `result` → `issued_tokens`, the name the refresh and password change routes already use; the bearer token's parameter in `deps.py`, `token` → `access_token`, as the auth service names it, now a `NAMING.md` row); docs: `9e21ddb`; Ruff clean, 327 passed; OpenAPI exported before and after: identical after the renames, and after the docs only the five routes' descriptions differ, which are their docstrings; the code's AST is identical without the docstrings, with the renames mapped back; claims checked in probes on the test database and in the installed FastAPI 0.141.1, Starlette 1.6.0, and coverage.py 7.16.1 (one user lookup and one session per request, the context copies, which 401s carry `WWW-Authenticate`, the sign-in form's field sizes, the 422 body, coverage of a folder without `__init__.py`); findings R-031 to R-035
- [x] 10. App, health, and CLI — `app/__init__.py`, `app/main.py`, `app/modules/__init__.py`, `app/api/__init__.py` (added 2026-11-05 for R-032), `app/api/router.py`, `app/api/health.py`, `app/cli.py` (320 lines when planned, 382 after the docs) — refactor: `f636cc4` (the readiness check's `database` → `db`, the name every other route and dependency gives the session from `get_db`, your choice of my recommendation, now a `NAMING.md` row; and `err` → `exc`, as R-002 settled); docs: `9c56300`, with the `create_app` correction carried from stage 9; `app/api/__init__.py`, written for R-032, already met the standard; Ruff clean, 336 passed, each commit also run like CI in a clean worktree (coverage 99.58%); OpenAPI exported before and after: after the renames only the readiness route's description differs, and after the docs only it and `HealthStatus`'s description, which are docstrings; after the docs commit, the code's AST is identical to the refactor's without the docstrings; claims checked in fresh processes and probes (importing `app.main`, and `python -m app.cli --help`, with no settings; the readiness check against a wrong password and a closed port; Typer's lone command, and its crash traceback with and without locals; Pydantic's password wording), in the installed Starlette 1.6.0, FastAPI 0.141.1, fastapi-cli 0.0.32, uvicorn 0.53.0, and Typer 0.27.2, and in Typer's release notes and Render's health check documentation; findings R-036 to R-038

### Tests

- [x] 11. Test setup — `tests/conftest.py`, `tests/factories.py` (324 lines when planned, 403 after the docs) — refactor: `ba00ba5` (`apply_migrations`' `result` → `upgrade`, the finished `alembic upgrade head` run, per the shape rule); docs: `a459df1`; Ruff clean, 339 passed, both commits also run like CI in a clean worktree (coverage 99.58%); no router or schema touched, so no OpenAPI diff, and the code's AST is identical without the docstrings; claims checked in probes on the test database, in fresh runs, and in the installed SQLAlchemy 2.1.1, pytest 9.1.1, pwdlib 0.3.1, and Faker 40.40.0 (the savepoint statements and what a rollback undoes, a run without `TEST_DATABASE_URL`, the whole suite against an unreachable `DATABASE_URL`, the import mode that makes `factories` importable, `caplog` after `create_app`, the time to build an engine and to connect, a built user's database defaults, every Argon2 variant passing `verify_password`, the `user_id` call forms, and `TestClient` re-raising an error), and with mutants that skip each of the six service commits; findings R-039 to R-041
- Stage 12, platform tests (232 lines when planned), had grown to 892 lines with the fixes for R-003, R-009 to R-011, R-019, R-032, R-036, R-037, R-039, and R-040, so it was split in three on 2026-11-06, keeping the numbers of the later stages:
- [x] 12a. Platform tests: database and test setup — `tests/test_database.py`, `tests/test_conftest.py` (added 2026-11-06 for R-039 and R-040), `tests/test_package_layout.py` (added 2026-11-05 for R-032) (306 lines when split, 443 after the docs) — refactor: `30a5018` (in `test_database.py`: `test_a_row_written_in_one_test_is_not_visible_in_the_next` → `test_a_row_committed_in_a_test_is_visible_in_that_test`, since it checks its own commit and its companion checks the next test; the scratch table `rollback_prob` → `rollback_probe`; `rows` → `row_count`; `exists` → `probe_table`, which holds a table name or `None`, not a boolean); docs: `04f1228`; Ruff clean, 347 passed, both commits also run like CI in a clean worktree (coverage 99.58%); no router or schema touched, so no OpenAPI diff, and the code's AST is identical without the docstrings; claims checked with broken copies of `conftest.py` on a scratch database (a plain `Session` with `SessionLocal`'s options, `SessionLocal` without `create_savepoint`, `control_fully`, no outer rollback, no outer transaction) and in the installed SQLAlchemy 2.1.1 (`sessionmaker` builds its own `Session` subclass); findings R-042. **Second pass** (2026-11-06, at your request, the same three files read again): refactor: none, no rename needed; docs: `bf31a33` (claims the first pass left too broad: which tests `db_session` runs, "points at" for a test that connects to nothing, which SQLAlchemy errors carry a statement's values, coverage.py's `include_namespace_packages` default, and two import comments); Ruff clean, 347 passed, also run like CI in a clean worktree (coverage 99.58%); the code's AST is identical without the docstrings; claims checked with broken copies of `conftest.py` and `app/db/session.py` on scratch databases, one of them standing in for the development database (a `get_db` that never closes or that commits, the engine without `-c timezone=utc`, a teardown that commits, a CLI test without the `SessionLocal` replacement, every connection through the application's engine refused), with the whole suite run reversed and shuffled twice (all pass), and in the installed SQLAlchemy 2.1.1, pytest 9.1.1, coverage.py 7.16.1, and FastAPI 0.141.1; R-042's recommendation revised, because the one first logged misses a teardown that commits; findings R-043 and R-044
- [x] 12b. Platform tests: errors and health — `tests/test_errors.py`, `tests/test_health.py` (277 lines when split, 366 after the docs) — refactor: none, no rename needed; docs: `d8362d5`; Ruff clean, 350 passed, also run like CI in a clean worktree (coverage 99.86%); no router or schema touched, so no OpenAPI diff, and the code's AST is identical without the docstrings; claims checked in the installed FastAPI 0.141.1 and Starlette 1.6.0 (FastAPI's default 404 body, the 405's `Allow` without HEAD, `OAuth2PasswordBearer`'s challenge, Starlette re-raising after the 500), in RFC 9110 (§11.6.1, §15.5.4, §15.5.6) and Render's health check documentation, and in probes (which responses carry `X-Request-ID`: all but a crash's 500; what a session's first `execute` raises when nothing listens at the database's address; libpq's wording in psql 17; the test database on a closed port), and with broken copies of `errors.py`, `health.py`, and `logging.py` run against the whole suite: each handler claim a docstring makes fails its test when broken; findings R-045 to R-048
- [x] 12c. Platform tests: logging — `tests/test_logging.py` (309 lines when split, 381 after the docs) — refactor: `e77349f` (`test_reuses_a_valid_uuid_in_lowercase` → `test_a_valid_uuid_is_reused_in_its_normalized_form`, since three of its five cases change more than the case; `test_generates_an_id_when_clients_sends_fake_uuid_value` → `test_a_missing_or_invalid_header_gets_a_generated_id`, for the "clients sends" slip and a missing header, which is no fake value); docs: `0494955`; Ruff clean, 351 passed, both commits also run like CI in a clean worktree (coverage 99.86%); no router or schema touched, so no OpenAPI diff, and the code's AST is identical without the docstrings; claims checked in the installed Starlette 1.6.0 (the test client decodes the path, `request.url` is parsed with `urlsplit`, and `TestClient` prefers httpx2), httpx2 2.13.1 (it logs each request at INFO, as `httpx2`), fastapi-cli 0.0.32 and uvicorn 0.53.0 (neither configures the root logger), and Python 3.13.15's `urlsplit` and `basicConfig`, in probes (which records a request leaves at `LOG_LEVEL` WARNING and INFO; an encoded line feed, tab, carriage return, and vertical tab in a logged path; the file run without `TEST_DATABASE_URL`), and with broken copies of `logging.py` run against the whole suite; findings R-049 to R-051
- [x] 13. Security tests — `tests/test_security.py` (509 lines when planned, 633 after the docs) — refactor: `42e7ee0` (`hashed_password` → `password_hash`, with `first_password_hash` and `second_password_hash`, the name the column, every parameter, and `make_user` already use, now a `NAMING.md` row with `token_hash`; `hash_tokens` → `token_hashes`; `result` → `is_correct`; `value` → `sha256_of_abc`; `production` → `production_settings`); docs: `cc8e73f`; Ruff clean, 352 passed, both commits also run like CI in a clean worktree (coverage 99.86%, `security.py` 100%); no router or schema touched, so no OpenAPI diff, and the code's AST is identical without the docstrings, with the renames mapped back for the refactor; claims checked in the installed PyJWT 2.15.1 (the error each rejected token raises, `exp` checked only when present, alg `none` taking only `None` or an empty key), pwdlib 0.3.1 and argon2-cffi 25.1.0 (`recommended()`'s settings, the Argon2 pattern that lets a hash without a digest through to argon2-cffi, `UnknownHashError`'s fixed message), Starlette 1.6.0 (the headers `set_cookie` and `delete_cookie` write), and NIST SP 800-63B-4 §3.1.1.2 (minimum length, truncation, NFC), in probes (10,000 refresh tokens all 43 characters long, the test's bcrypt value against the factories' one, the NFC and NFD forms of the Unicode password), and with 16 broken copies of `security.py` and one of `auth/service.py`, run against the whole suite on a scratch database, where only `test_engine_points_at_the_test_database` fails, by design, with or without a copy: of the 16, only the control and a warning that names the stored value were caught; each recommendation was then run against the copies it targets; findings R-052 to R-060
- [x] 14. users tests: model and schemas — `tests/test_user_model.py`, `tests/test_user_schemas.py` (349 lines when planned, 397 before the docs, 506 after) — refactor: `aa282a0` (in `test_user_schemas.py`, the helper `valid_data` → `_valid_values`, the dict it returns `data` → `values`, and the `UserCreate` built from it `user` → `data`, your choice of my recommendation, now a `NAMING.md` row: `data` already named a validated input schema, and `user` an ORM `User`; in `test_user_model.py`, `role` → `stored_role`, the raw string PostgreSQL holds); docs: `442fa6b` (module docstrings and import comments; four claims corrected: which test a lowered password minimum fails, a sentence that came with R-058's fix; which code lowercases emails; what a bad role sends to the database; and the CHECK refusing a case-only duplicate "first"); Ruff clean, 361 passed, both commits also run like CI in a clean worktree (coverage 99.86%); no router or schema touched, so no OpenAPI diff, and the code's AST is identical without the docstrings, with the renames mapped back for the refactor; claims checked in probes on the test database (a bad role sends only the session's rollback; a raw insert without an `id` fails on it before the role CHECK; `now()` stays fixed when a savepoint is released; the `INSERT` sends NULL for a `None` in a column with no default and leaves out a `None` flag, which then takes its server default; an update through the ORM after a raw SQL backdating; sign-in with `Eve <test@example.com>` as the username), in the installed SQLAlchemy 2.1.1 (`IntegrityError` is a `StatementError`), Pydantic 2.13.5 (`EmailStr` takes the display-name form, `str_strip_whitespace` strips a `SecretStr` too, which whitespace `strip_whitespace` removes around a name), and email-validator 2.3.0 (it lowercases only the domain, and no address it accepts is longer than 254 bytes), and with 23 broken copies of `users/models.py`, `users/schemas.py`, and `db/base.py`, run against the whole suite on a scratch database, where only `test_engine_points_at_the_test_database` fails, by design: all but two fail a test, and each recommendation was then run against the copy it targets; findings R-061 to R-064
- [x] 15. users tests: service and CLI — `tests/test_user_service.py`, `tests/test_cli.py` (414 lines when planned, 594 before the docs, 785 after) — refactor: `428eff9` (in `test_user_service.py`, what each lookup returns, `result` → `found_user`, as `test_auth_repository.py` says `found_token`, now a `NAMING.md` row, and the recovery test's `result` → `admin`, the name the other two `create_first_admin` tests use; in `test_cli.py`, the refusal test's `user` → `existing_admin`, and the crash test's `crash` → `exc_info`, your choice of my recommendation, the name the suite's other 49 `pytest.raises` blocks use, now a `NAMING.md` row; what `CliRunner().invoke` returns stays `result`, also your choice, since it is Click's `Result`, a row too); docs: `acf3765` (module docstrings and import comments; five claims corrected or made exact: the service refuses, not the command; the spy's empty record proves the repository was never called, not that no query ran; lookups return inactive accounts because each caller decides what deactivation means; the taken-email test can't tell the service's check from the unique constraint; and "keeps its chosen password" meant the first Admin needn't change it; three comments that said what an object is folded into the docstrings); Ruff clean, 366 passed, both commits also run like CI in a clean worktree (coverage 99.86%); no router or schema touched, so no OpenAPI diff, and the code's AST is identical without the docstrings, with the renames mapped back for the refactor; claims checked in probes on scratch databases (a lookup that ignores the ID finds the decoy first, in two whole-suite runs; without the service's rollback the duplicate test's count fails with `PendingRollbackError`, and without its flush the `IntegrityError` escapes at the commit; the `INSERT` returns the server defaults; a password hash takes about 48 ms), in the installed Click 8.5.0 (`Result.output` holds both streams since 8.2, a visible prompt echoes what is typed while a hidden one calls `getpass.getpass`, and a mismatched confirmation prints its error, asks again, and aborts when the input runs out), Pydantic 2.13.5 (the whole validation error holds the typed password as `input_value`), and email-validator 2.3.0 (the full-width domain and the decomposed accent rewritten), and with 42 broken copies of `users/service.py`, `users/repository.py`, and `cli.py`, run against the whole suite on a scratch database, where only `test_engine_points_at_the_test_database` fails, by design: all but eight fail a test, and each recommendation was then run against the copies it targets; findings R-065 to R-069
- [x] 16. Repository tests — `tests/test_user_repository.py`, `tests/test_auth_repository.py` (315 lines when planned, 530 before the docs, 635 after) — refactor: `184ab2c` (in `test_user_repository.py`, what each lookup returns, `database_user` and `result` → `found_user`, under `NAMING.md`'s `found_<thing>` row, as carried from stage 15, and what `exists_active_admin` returns, `found` and `admin_exist` → `has_active_admin`, under the boolean rule; in `test_auth_repository.py`, the read-back query's `result` → `found_token`, the name its other lookups use, and the owner lookup's `user_id` → `found_user_id`; the row now covers a lookup that returns one column); docs: `f8b131a` (module docstrings and import comments, and "ID" in prose, as stage 15's tests write it; seven claims corrected or made exact: which test the decoy saved first helps; that the locking lookup queries whatever the session holds, so emptying the session only makes it build a new object; why the first revocation test reads its tokens back with a query, since the session never loaded their `revoked_at` and the `UPDATE` leaves it unloaded; why the third reads the stored time, since the token it never keeps in a variable is gone from the session after the flush; that the ID and owner lookup tests save only a revoked target; that the service already flushes and commits; and what a caller that waited for the lock sees); Ruff clean, 367 passed, both commits also run like CI in a clean worktree (coverage 99.86%); no router or schema touched, so no OpenAPI diff, and the code's AST is identical without the docstrings, with the renames mapped back for the refactor; claims checked in probes on the test database and in the installed SQLAlchemy 2.1.6 (the bulk revocation sends `updated_at=now()`; a token the session created without `revoked_at` still reads None after it, with no query; the session keeps a saved object only while the test holds a reference to it; the locking user lookup sends `FOR NO KEY UPDATE` with the user still in the session) and email-validator 2.3.0 (the `Email` rule accepts `_` and `%` before the @), and with 52 broken copies of the two repositories, `TimestampMixin`, and the auth service, run against the whole suite on a scratch database, where only `test_engine_points_at_the_test_database` fails, by design: all but 15 fail a test, and each recommendation was then run against the copies it targets; findings R-070 to R-074
- [x] 17. auth tests: model and schemas — `tests/test_refresh_token_model.py`, `tests/test_auth_schemas.py` (349 lines when planned, 369 before the docs, 473 after) — refactor: `760a9ea` (in `test_auth_schemas.py`, the helper `valid_password_change` → `_valid_values`, the dict it returns `data` → `values`, and the `PasswordChange` built from it `password_change` → `data`, as carried from stage 14 under `NAMING.md`'s `values` row, which now records it; in `test_refresh_token_model.py`, the count taken before the user is deleted, `remaining` → `token_count_before`, the name `test_auth_service.py` gives the same count); docs: `f46a105` (module docstrings and import comments; six claims corrected or made exact: that the valid-input test sees a schema that strips a password, which it can't, since neither default has a space at either end; that no stored password is longer than 128 characters, and that the refusal spares Argon2 work "on input of any size"; which tests count with `_count_tokens`; that the fixture's user goes because it isn't committed; that a new token is "usable", where the test checks only its revocation and replacement; and that the model "is what ends up in logs"; the three tests next to a gap now say what they can't see); Ruff clean, 382 passed, both commits also run like CI in a clean worktree (coverage 99.86%), and the two files pass reversed, shuffled twice, and one test at a time; no router or schema touched, so no OpenAPI diff, and the code's AST is identical without the docstrings, with the renames mapped back for the refactor; claims checked in probes on the test database and in the installed SQLAlchemy 2.1.6 (the `INSERT` sends NULL for `revoked_at` and `replaced_by_id`, and both read None afterwards with no query; after the cascade, the deleted user's tokens stay persistent, and `session.get` returns them without a query; refreshing a row that is gone raises `InvalidRequestError`; a `None` ID gets a UUID, and a `None` timestamp is left out of the `INSERT`; `Result.scalar` takes the first row; without `SET NULL`, deleting a replacement fails with `ForeignKeyViolation`; a naive expiry makes refresh raise `TypeError`) and Pydantic 2.13.5 (`str_strip_whitespace` strips a `SecretStr` too), through the API (a password with a space at either end signs in and can be changed, a 128-character current password can be changed, a 129-character one never reaches `verify_password`, and an empty one is a 400), and with 34 broken copies of the refresh token model and its migration, run on a scratch database rebuilt for each, and of the auth schemas, the password rule's constants, and sign-in: 26 run against the whole suite, of which 5 pass it, and every model and migration copy fails a test; the other 8, run against the two schema test files to check their boundary and printing claims, each fail a test there; each recommendation was then run against the copies it targets; findings R-075 and R-076
- [x] 18. auth service tests, part 1 — `tests/test_auth_service.py`: constants, fixtures, helpers, and `login` tests (about 450 lines when planned, 491 before the docs, 647 after) — refactor: `5cb266a` (what `service.login` returns, `result` → `issued_tokens`, in four tests, as carried from stage 9; a refresh token's row, `token` → `token_row` and `tokens` → `token_rows`, in four tests, the names the rest of the file gives rows wherever a raw token is in scope too, your choice of my recommendation, now a `NAMING.md` row; and `test_a_user_who_must_change_their_password_can_still_log_in` → `test_login_succeeds_while_a_password_change_is_pending`, since `NAMING.md`'s `login` row keeps `log_in` out of code names, and the other sign-in tests start with `test_login_`); docs: `360f3f1` (the module docstring, for the whole file, and import comments; six claims corrected or made exact: why the rollback removes the `user` fixture's account, since a use case's commit releases only a savepoint; that importing `get_user_by_id` by name copied it; that without `populate_existing` a bulk `UPDATE` could leave `_token_row` a stale copy; that each of the three case lists holds every way its use case fails; that printing an `IssuedTokens` shows its `repr`, which holds only while the class defines no `__str__`; and why a failed sign-in writes nothing; the three tests next to a gap now say what they can't see); Ruff clean, 388 passed, both commits also run like CI in a clean worktree (coverage 99.86%), and the file passes reversed and shuffled twice; no router or schema touched, so no OpenAPI diff, and the code's AST is identical without the docstrings, with the renames mapped back for the refactor; claims checked in probes on the test database and in the installed SQLAlchemy 2.1.6 (a use case's commit is invisible to another connection; the auth service's `get_user_by_id` is the users service's function itself; after the bulk revocation, a plain query reads the new `revoked_at` whether or not the session had loaded it, and only a loaded row changed by raw SQL reads stale; `db_session.refresh` drops a sign-in time that was set but never flushed, while a count sees a token that was only added; `repr`, `str()`, an f-string, and `%s` all show `IssuedTokens()`; the database gives a new account both flags true), through the API (the details a copy gives a failed sign-in reach the 401's body; a sign-in's records at DEBUG hold no secret), in timings (every kind of failed sign-in takes about 50 ms, and a deactivated account refused before its password check 0.9 ms), and with 24 broken copies of `login`, `IssuedTokens`, and `_issue_tokens`, run against the whole suite on a scratch database, where only `test_engine_points_at_the_test_database` fails, by design: 11 fail a test, 9 pass it and are R-078 to R-081, and 4 are left as notes; each recommendation was then run against the copies it targets; findings R-078 to R-081
- [x] 19. auth service tests, part 2 — `tests/test_auth_service.py`: `get_authenticated_user` and `refresh` tests (about 370 lines when planned; 437 before the docs, with the refresh test that sits among part 3's tests, and 488 after) — refactor: `45bedab` (what `get_authenticated_user` returns, `result` → `authenticated_user`, in three tests, since the function is no lookup, which `NAMING.md`'s `found_<thing>` row now says; the comprehension's `row` → `token_row`, under the `token_row` row; and `test_the_new_token_keeps_the_old_expiry` → `test_refresh_keeps_the_old_expiry`, since a password change's new token gets a fresh window, and the other refresh tests start with `test_refresh_`); docs: `ab8f47d` (the module docstring gives part 2 a paragraph of its own, which says what its tests check; six claims corrected or made exact: that only a database read catches a deactivated account, where the test's account is the session's own copy, read with no query; that the new token is "still usable"; that three days is "not the configured seven"; that the link serves only an investigation, where it is what marks a token as rotated; that the second use "is treated as reuse"; and "the same 401 error", where the tests check the class and the message; the tests next to an open finding say what they can't see); Ruff clean, 392 passed, both commits also run like CI in a clean worktree (coverage 99.86%), and the file passes reversed, shuffled twice, and at `LOG_LEVEL=INFO`; no router or schema touched, so no OpenAPI diff, and the code's AST is identical without the docstrings, with the renames mapped back for the refactor; claims checked in probes on the test database (`get_authenticated_user` sends no statement for an account the session holds, while a request to `GET /auth/me` sends one `SELECT`; through the API, the reuse warning carries no request ID, and the request's own line names no user; a copy's details and code reach the 401's body; with a one-minute access token lifetime and a 61-second pause after collection, the unknown-user case passes on a copy without the `None` check; a refresh that ends the other sessions makes the phone's next refresh a 401; one that checks the account before reuse lets a thief's replacement refresh once the account is reactivated) and in the installed SQLAlchemy 2.1.6 (`session.get` with a `None` ID warns and answers `None`), and with 54 broken copies of `get_authenticated_user` and `refresh` and a control, run against the whole suite on a scratch database, where only `test_engine_points_at_the_test_database` fails, by design: 27 fail a test, 19 pass it and are R-083 to R-087, and 8 are left as notes; R-082 came from the slow run; each recommendation was then run against the copies it targets; findings R-082 to R-087
- [x] 20. auth service tests, part 3 — `tests/test_auth_service.py`: `logout`, `change_password`, and password-change gate tests (about 340 lines when planned; 399 before the docs, with the refresh test that sits among them, which stage 19 reviewed, and 436 after) — refactor: `035b212` (raw refresh tokens get `raw_` in front, as `NAMING.md`'s `access_token` and `refresh_token` row asks and parts 1 and 2 write them: `user_raw_token`, `other_user_raw_token` (twice), and `revoked_raw_token`; `first_token` and `second_token`, raw values beside their rows `first_token_row` and `second_token_row`; and where a test has a twin in part 2, its tokens and rows take the twin's names for the same roles, `raw_refresh_token` with `refresh_token_row` and `raw_other_device_token` with `other_device_row`, in three tests); docs: `fcb8fa0` (the module docstring's part 3 paragraph says what its tests check; six claims corrected or made exact: that the commit makes `other_user` reload, when the session doesn't expire objects on commit; that the rollback makes `user` reload, when after a commit it has nothing to undo; that the empty link serves only an investigation, when it keeps a later refresh with the token quiet; that `user` is the object the service changes; what "a working session" checks; and that sign-out "ends only the caller's own session" where it ends none; three import comments brought up to the stage 18 and 19 fixes; the tests next to an open finding say what they can't see); Ruff clean, 396 passed, both commits also run like CI in a clean worktree (coverage 99.86%), and the file passes reversed, shuffled twice, and at `LOG_LEVEL` INFO and DEBUG; no router or schema touched, so no OpenAPI diff, and the code's AST is identical without the docstrings, with the renames mapped back for the refactor; claims checked in probes on the test database and the installed SQLAlchemy 2.1.6 (after the change's commit no attribute of another account is expired, and reading its hash sends no statement; after a commit no transaction is in progress, so the test's rollback expires nothing, while changing an attribute begins one, which a rollback then undoes; the locked lookup returns the very object the request loaded, through the API too; a sign-out that links its token makes the next refresh log the reuse warning and revoke the other device's token; the copy loaded before a sign-out shows a bulk revocation; through the API, a copy that compares the new password first answers "must be different" only for the right guess and leaves the password as it was, and one that sets the sign-in time moves it; a password change whose token `INSERT` fails at the commit saves nothing), and with 65 broken copies of `logout`, `change_password`, `ensure_password_change_not_pending`, refresh's quiet refusal, and the sign-out and password change routes, and a control, run against the whole suite on a scratch database, where only `test_engine_points_at_the_test_database` fails, by design: 39 fail a test, 17 pass it and are R-088 to R-093, and 9 are left as notes; each recommendation was then run against the copies it targets; findings R-088 to R-093
- [x] 21. auth API tests, part 1 — `tests/test_auth_api.py`: constants, fixtures, helpers, and `POST /auth/login` tests (about 265 lines when planned, 473 before the docs, 616 after) — refactor: `aa7ca81` (`test_wrong_credentials_return_the_standard_401` → `test_login_with_a_wrong_password_returns_the_standard_401`, since it sends only a wrong password, and the file's other sign-in tests start with `test_login_`, as `NAMING.md`'s `login` row has code names follow the route; and in `test_the_refresh_cookie_holds_the_stored_token`, the cookie's raw value `refresh_token` → `raw_refresh_token` and the rows `tokens` → `token_rows`, under `NAMING.md`'s raw-token and `token_row` rows); docs: `d9b4837` (a module docstring for the whole file, which had none, with a paragraph for each part, the other two in brief for stages 22 and 23; a comment above each of the 26 imports, 3 of which had one; eight claims corrected or made exact: why the `user` fixture flushes, carried from stage 12c; that every route that uses `CurrentUser` is exempt from the gate, carried from stage 9, with `Args` and `Returns` for its route function; that `_auth_header` serves only the current-user route's tests; that the client's cookie jar keeps only names and values; that the empty token table proves the service never ran; that a rejected password "can't reach a log"; that `REFUSED_PASSWORD_CHANGES` holds every way the service refuses a change; and "the same 401" where the tests compare the code and the message; the tests next to an open finding say what they can't see); Ruff clean, 405 passed, both commits also run like CI in a clean worktree (coverage 99.86%), and the file passes reversed, shuffled twice, and at `LOG_LEVEL` INFO and DEBUG; no router or schema touched, so no OpenAPI diff, and the code's AST is identical without the docstrings, with the renames mapped back for the refactor; claims checked in probes on the test database (the fixture's account is active and must change its password; the cookie jar keeps the path, the domain, `Secure`, an expiry from `Max-Age`, and `HttpOnly` and `SameSite` as nonstandard attributes; a JSON body's 422 names both fields as missing; a wrong password, a NUL, and a 255-character email each get the very same 401 body, `details` empty, with `WWW-Authenticate: Bearer`; a sign-in logs no email and prints nothing; no route uses `CurrentUser`; a sign-in's 200 has no `Cache-Control`), with an AST scan of `tests/` for status checks that come after the body is read (R-098), and with 21 broken copies of the sign-in route, `login`, `LoginForm`, the error handlers, the users service, and the CLI, run against the whole suite on a scratch database, where only `test_engine_points_at_the_test_database` fails, by design: 2 fail a test, the controls that log a secret at DEBUG; 14 pass it and are R-094 to R-097; 2 pass it and are what the proposed `CLAUDE.md` line would flag; and 3 are left as notes; a copy with R-099's fix passes the suite too; each recommendation was then run against the copies it targets; findings R-094 to R-099
- [x] 22. auth API tests, part 2 — `tests/test_auth_api.py`: `GET /auth/me`, `POST /auth/refresh`, and `POST /auth/logout` tests (about 375 lines when planned, 529 before the docs, 564 after) — refactor: `7a5cb76` (the error object `body` → `error` in the three current-user tests that read one, the name the rest of the file gives it, and the sign-in response `login` → `login_response` in `test_me_accepts_the_access_token_from_login`, both carried from stage 21; in `test_reusing_an_old_cookie_signs_out_every_session`, the cookie values `old_token` and `new_token` → `old_cookie` and `new_cookie`, since `NAMING.md`'s raw-token row rules out a bare `token` where either kind could be meant, and its twin, `test_reuse_is_logged_with_the_request_id`, and part 3 already say so, now a sentence in that row; and in `test_every_kind_of_401_names_the_bearer_scheme`, `wrong_password` → `wrong_password_form` and `expired_header` → `expired_token_header`, for what each holds); docs: `3302745` (the module docstring's part 2 paragraph brought up to what its tests check, and its first paragraph says why a test clears the cookie jar before it sets a cookie; eight claims corrected or made exact: that a cookie on any other path is left out, when one on `/` or `/api` is sent; that `Max-Age` may "still be aligned later", when ADR-0004 accepts the reset; that the gate is "added later" and "once the gate exists", in two tests; that `WWW-Authenticate` tells clients how to sign in; that signing out never fails; that neither cookie may appear "anywhere" in a capture that holds only WARNING and above; that the chaining test is the one that proves sign-in's tokens open "the protected routes"; and why an empty bearer token reaches the service; the tests next to an open finding say what they can't see); Ruff clean, 406 passed, both commits also run like CI in a clean worktree (coverage 99.86%), and the file passes reversed, shuffled twice, and at `LOG_LEVEL` INFO and DEBUG; no router or schema touched, so no OpenAPI diff, and the code's AST is identical without the docstrings, with the renames mapped back for the refactor; claims checked in probes on the test database and in the installed FastAPI 0.141.1 and Starlette 1.6.0 (which cookie paths the client sends to the refresh URL; that without clearing the jar it sends the server's cookie and the test's both, and the "replay" refreshes with the new one, 200, because Starlette keeps one value per name; that the client drops the cookie sign-out clears; that `OAuth2PasswordBearer` hands on whatever follows `Bearer`, so `Bearer ` reaches the service as an empty token, and no unusable header sends a query for a user; that every 401 of this part has `details` empty, the request ID of its `X-Request-ID` header, `WWW-Authenticate: Bearer`, and no cookie; that the fixture's account must change its password and refreshes all the same; that at DEBUG these requests log only the request lines, the test client's lines, asyncio's, and the reuse warning, and print nothing; that sign-in's and refresh's access tokens, signed in the same second, are the same string; and that `caplog.at_level("WARNING", logger=...)` keeps the WARNING records of every logger), with a status-first scan of `tests/` widened to header reads and responses never read (R-103), and with 33 broken copies of the three routes, the bearer-token dependency, `refresh`, `logout`, `get_authenticated_user`, the token decoder, the error handlers, and `login`, and a baseline, run against the whole suite on a scratch database, where only `test_engine_points_at_the_test_database` fails, by design: 8 fail a test, the controls, the two copies R-103 shows its tests failing on, and two that only the API password change test catches, by chance (R-101); 22 pass it and are R-100 to R-102; and 3 are left as notes; each recommendation was then run against the copies it targets; findings R-100 to R-103
- [ ] 23. auth API tests, part 3 — `tests/test_auth_api.py`: `POST /auth/change-password` and gated-route tests (about 340 lines)
- [ ] 24. Settings tests — `tests/test_config.py` (327 lines), added 2026-11-04 for R-012
- [ ] 25. auth concurrency tests — `tests/test_auth_concurrency.py` (893 lines), added 2026-11-05 for R-022, R-023, and R-025; split it in three when reached: the fixtures and helpers, the refresh and sign-out races, then the password change and sign-in races
