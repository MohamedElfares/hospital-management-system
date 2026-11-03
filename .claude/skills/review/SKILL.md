---
name: review
description: Review backend code against the project plan, check that docstrings and comments are accurate, and improve names. Runs in resumable stages and records everything in docs/review/. Run as /review followed by a scope.
argument-hint: "<scope: new | all | module <name> | file <path>>"
disable-model-invocation: true
---

# Code review

Scope: $ARGUMENTS (when empty, use `new`)

| Scope | Files to review |
|---|---|
| `new` | Files added or changed since their last review, per `docs/review/STATE.md`. The normal repeat run. |
| `all` | Every Python file under `backend/`. Use for the first run and after a convention changes. |
| `module <name>` | `backend/app/modules/<name>/` and its tests. |
| `file <path>` | That file only. |

This runs many times over the project's life, so leave the trackers in a
state your next run can trust. Record first, then review.

## Read before every stage

1. `CLAUDE.md` — ownership, layering, conventions, security rules
2. `docs/PROJECT_PLAN.md` §6 authorization, §9 architecture, §11 API conventions, §13 testing, §17 documentation
3. `docs/review/NAMING.md` — the vocabulary already agreed
4. `docs/review/FINDINGS.md` — open items, and the settled items you must not raise again
5. `docs/review/STATE.md` — when each file was last reviewed

If a tracker is missing, create it from the templates in `docs/review/`
before doing anything else.

## What you may change

**Apply directly:** docstrings, comments, and renames of names that are
private to the backend — local variables, parameters, internal function and
method names, class names, fixtures, and test names.

**Add to `FINDINGS.md` as open, and ask me:**
- Renames that change a Pydantic schema field, route path, query parameter, or error code. That is the public API contract.
- Renames of a SQLAlchemy column, table, index, or constraint. Those need an Alembic migration, which is mine.
- Anything in `backend/app/core/config.py`, `backend/alembic.ini`, `backend/migrations/`, or `backend/.env.example`. Tell me the exact edit to make.
- Any bug, security gap, or deviation from the plan. Log it; never fix it here. This pass changes names and documentation only, never behavior.

**Never:** change logic, add or remove a test, weaken a permission check, or
touch anything outside `backend/`.

## Naming standard

Use the plan's vocabulary exactly: appointment, visit, prescription,
medicine, batch, dispense, transfer, branch. `NAMING.md` holds every term
already settled; follow it and add to it rather than inventing a synonym.

- Booleans start with `is_`, `has_`, or `can_`.
- Collections are plural; single items singular.
- Repository methods: `get_<thing>_by_<field>` returns one or `None`, `list_<things>` returns many, plus `create_`, `update_`, `delete_`, `exists_`.
- Service methods name the use case: `book_appointment`, `dispense_prescription`, never `handle_data` or `process`.
- No type names inside variable names (`appointment_dict`), and no `data`, `info`, `tmp`, or `result` when a specific word exists.
- Abbreviations only when the plan's glossary defines them (MRN, FEFO).
- Tests: `test_<action>_<condition>_<expected>`, for example `test_booking_a_taken_slot_returns_409`.

A rename must make a name more accurate, not merely different. If the
current name is already clear, leave it.

## Step 1: plan the run, then stop

1. Work out the file set for the scope. For `new`, a file needs review when
   `git log --oneline <reviewed commit>..HEAD -- <file>` returns anything,
   or when it has no row in `STATE.md`. Drop rows for deleted files.
2. Group the files into stages of about 400 lines or one module, whichever
   is smaller, keeping a module's `router`, `schemas`, `service`,
   `repository`, and `models` together. Tests get their own stages.
3. Open a run in `REVIEW_LOG.md`: next run number, today's date, the scope,
   the current `HEAD` SHA, the file count, and the stage list as a
   checklist.
4. Commit as `docs(review): plan run <n>`.
5. Tell me the stage list and stop. Do not start a stage.

If the file set is empty, say so, write a one-line run entry saying nothing
needed review, and stop.

## Step 2: one stage per session

Take the first unchecked stage in the open run.

1. **Audit.** Read the files. Check each against the plan: layer rules
   (routers do HTTP only, services own the transaction and raise domain
   errors, repositories never commit), status codes, the standard error
   format, a permission check on every route, record-level checks in
   services, and the testing rules in §13. Check every docstring against the
   code it describes: every argument present, the real return value, every
   error actually raised, and nothing the code no longer does. Add what you
   find to `FINDINGS.md`.
2. **Rename.** Apply only the renames you are allowed to apply. Search the
   whole repository for each old name, including strings and tests, and
   confirm nothing is left. Add any new term to `NAMING.md`. Run
   `uv run pytest`. Commit as `refactor(<module>): clarify names`.
3. **Document.** Bring every docstring and comment in those files to the
   §17 standard, using the new names. Commit as
   `docs(<module>): detailed docstrings and import comments`.
4. **Verify.** `uv run ruff check . && uv run ruff format .` and
   `uv run pytest` both pass. If the stage touched a router or schema, run
   `uv run python -m app.cli export-openapi /tmp/openapi.json` and diff it
   against the committed schema to prove the API did not change.
5. **Record.** Update `STATE.md` with each reviewed file at the new `HEAD`
   SHA, tick the stage in `REVIEW_LOG.md`, and add both commit SHAs. Commit
   as `docs(review): record run <n> stage <m>`.
6. **Report and stop.** In under 15 lines: what you renamed and why, what
   you documented, anything in `FINDINGS.md` needing my decision, and the
   next stage. Do not start it.

When the last stage is ticked, close the run in `REVIEW_LOG.md` with the
check results and the finding counts.

## Recording rules

- Every finding gets the next free `R-<nnn>` ID, and keeps that ID forever.
- Something I accept, or decide is fine as it is, moves to **Settled** in
  `FINDINGS.md` with the reason. Never raise a settled item again; if a
  settled item is genuinely wrong later, open a new finding that links to it.
- A finding that becomes work moves to **Settled** with its GitHub issue
  number.
- When the same kind of finding appears three times across runs, propose one
  line for `CLAUDE.md` that would stop it recurring, and note it in the run
  entry.
- Keep `FINDINGS.md` ordered: open items first, newest run last.

## Stage rules

- A stage is done only when the linters and tests pass and the trackers are
  committed. Never leave the repository mid-rename.
- If context is running low, finish the file you are on, record exactly
  where you stopped, commit, and say so.
- Never run two stages in one session, even if the first was short.
- If a rename or a plan rule is ambiguous, stop and ask instead of guessing.

## Resuming

When I say "continue the review", read the trackers and run the next
unchecked stage of the open run in `REVIEW_LOG.md`.
