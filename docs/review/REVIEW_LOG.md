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
- [ ] 17. auth tests: model and schemas — `tests/test_refresh_token_model.py`, `tests/test_auth_schemas.py` (349 lines)
- [ ] 18. auth service tests, part 1 — `tests/test_auth_service.py`: constants, fixtures, helpers, and `login` tests (about 450 lines)
- [ ] 19. auth service tests, part 2 — `tests/test_auth_service.py`: `get_authenticated_user` and `refresh` tests (about 370 lines)
- [ ] 20. auth service tests, part 3 — `tests/test_auth_service.py`: `logout`, `change_password`, and password-change gate tests (about 340 lines)
- [ ] 21. auth API tests, part 1 — `tests/test_auth_api.py`: constants, fixtures, helpers, and `POST /auth/login` tests (about 265 lines)
- [ ] 22. auth API tests, part 2 — `tests/test_auth_api.py`: `GET /auth/me`, `POST /auth/refresh`, and `POST /auth/logout` tests (about 375 lines)
- [ ] 23. auth API tests, part 3 — `tests/test_auth_api.py`: `POST /auth/change-password` and gated-route tests (about 340 lines)
- [ ] 24. Settings tests — `tests/test_config.py` (327 lines), added 2026-11-04 for R-012
- [ ] 25. auth concurrency tests — `tests/test_auth_concurrency.py` (893 lines), added 2026-11-05 for R-022, R-023, and R-025; split it in three when reached: the fixtures and helpers, the refresh and sign-out races, then the password change and sign-in races
