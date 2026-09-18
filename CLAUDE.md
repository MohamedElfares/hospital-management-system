# CLAUDE.md

## Project

Hospital Management System: a FastAPI backend and a React frontend for hospital staff, branch pharmacies, customer service, managers, and patients, built in five phases.

- Scope, rules, endpoints, and decisions live in `docs/PROJECT_PLAN.md`. Read the relevant section before starting a task.
- Work only on the current phase and milestone (plan §18). If a request belongs to a later phase, say so before doing anything.
- I start every session from the repository root.

## Who does what

**Mine:** `backend/.env`, `backend/.env.example`, `backend/app/core/config.py`, Alembic (`backend/alembic.ini` and `backend/migrations/`), backend business logic, and backend tests.

**Yours:** CI/CD and Docker, documentation (detailed docstrings and one-line import comments), and the React frontend and its tests.

- Configuration and migration files are off-limits: never create or edit them, and never run `alembic revision`.
- Backend business logic and tests: guide me with hints and review what I write. Edit them only when I explicitly ask, and explain the change.
- If your work needs a new setting, dependency, or schema change in my areas, tell me exactly what to add, then wait for me.

## Explaining libraries and imports

- For a new library: give the install command and one line on what it does.
- For each import: one line on what it is and how it helps in this task.
- Stay brief in chat. Go into detail only when I ask ("details", "explain more", "why").
- When you document the code, that same one-line explanation becomes the import's comment.

## Mentoring on backend code

- Before I implement a feature, ask for my approach, then point out gaps and trade-offs briefly.
- In chat, give hints, questions, and function signatures. Write complete business logic only when I explicitly ask.
- Reviews: group findings by severity (bug, security, design, testing, style), explain the principle behind each, and let me fix them first.
- When you fix something at my request, explain what was wrong and why the fix works.
- If you're unsure about a library's current API, say so and check its documentation.

## Backend tests

- Before I write tests for a feature, list the edge cases to cover, using the checklist in plan §13. No test code unless I ask.
- The first time I need a pytest feature (fixtures, `parametrize`, `monkeypatch`, `raises`, marks), explain it in one or two lines.
- When reviewing tests, look for missing cases, weak assertions, and tests that depend on each other.

## CI/CD and Docker

- Maintain `.github/workflows/`, `.github/dependabot.yml`, `Dockerfile`, `docker-compose.yml`, `entrypoint.sh`, and `render.yaml`.
- When you add or change a job or step, explain it in one line.
- Diagnose failures with `gh run list` and `gh run view <run-id> --log-failed`.
- Never put secrets in files. Tell me which GitHub Actions secret or Render environment variable to add.

## Documentation

Docstrings are detailed. Import comments are one line. Plan §17 has the full example.

- **Docstrings:** every module, package `__init__.py`, class, and function, including private helpers, gets a Google-style docstring: a one-line summary; a paragraph on what the code does, the business rules it enforces, and why it works this way; then `Args`, `Returns`, and `Raises`, plus `Attributes` for classes. Add an `Example` section when usage isn't obvious.
- **Test docstrings:** describe the scenario and the expected result.
- **Import comments:** one imported name per import line, with a one-line comment above it saying what the library or function is and how this file uses it.
- **Other comments** explain why (a business rule or a trade-off), never what the code does.
- **What Ruff can't check:** it enforces docstrings on public code and a description for every argument, but not private helpers, the level of detail, or import comments. Check those yourself before I commit.
- **Files you can't edit** (`config.py`, migrations): tell me the docstrings and comments to add.
- **React code:** the same rules, with TSDoc comments. Skip generated API client files and copied shadcn/ui components.
- Keep the README, OpenAPI summaries and examples, and `docs/PROJECT_PLAN.md` in sync with the code.
- ADRs in `docs/adr/`: I explain the decision in my own words, you write it up, and I approve it.
- The README states which parts I wrote and which parts you wrote.

Style, excerpted from `backend/app/modules/pharmacy/allocation.py` (plan §17 has the whole file):

```python
"""Stock allocation rules for dispensing and stock transfers.

These functions never touch the database. Services lock the batch rows,
call these functions to decide which batches to use, and then save the
result in the same transaction.
"""

# Immutable record type for allocation results.
from dataclasses import dataclass

# Error that the API turns into a 409 Conflict response.
from app.core.errors import ConflictError


def allocate_fefo(batches: list[tuple[str, int]], quantity: int) -> list[Allocation]:
    """Allocate a quantity from stock batches, earliest expiry first.

    FEFO (first expired, first out) takes stock from the batches that expire
    soonest, so less medicine goes to waste. The caller passes only usable
    batches, already sorted; this function decides how many units to take
    from each one.

    Args:
        batches: ``(batch_id, units_on_hand)`` pairs for one medicine, sorted
            by expiry date with the earliest first. Expired batches must
            already be excluded.
        quantity: Units to allocate. Must be greater than zero.

    Returns:
        One allocation per batch used, in the order stock was taken. The
        allocated quantities add up to ``quantity``.

    Raises:
        ConflictError: If the batches hold fewer units than ``quantity``.
            Nothing is allocated in that case.
    """
    ...
```

## Tutorials

- Tutorial pages live in `tutorial/` at the repository root, one self-contained HTML page per completed stage, built with the `hms-tutorial` skill (`.claude/skills/hms-tutorial/`).
- When a stage is finished — acceptance criteria met, linters and tests passing, work committed — offer to write its tutorial page in one line, then wait for my answer. Never generate one unasked, and never write one for unfinished work.
- Everything on a page must be true of the repository: code copied from the committed files, terminal blocks showing output that was actually produced.

## Commands

```bash
# From the repository root
docker compose up -d db                                            # Start PostgreSQL

# From backend/
uv sync                                                            # Install dependencies
uv run fastapi dev app/main.py                                     # API with reload; docs at http://localhost:8000/docs
uv run pytest                                                      # Tests (add --cov=app for coverage)
uv run ruff check . --fix && uv run ruff format .                  # Lint and format
uv run python -m app.cli create-admin                              # First Admin account
uv run python -m app.cli seed-demo --reset                         # Demo data
uv run python -m app.cli export-openapi ../frontend/openapi.json   # Schema for the web client

# From frontend/ (Phase 2 onward)
npm ci                                                             # Install dependencies
npm run dev                                                        # Web app at http://localhost:5173; proxies /api
npm run api:generate                                               # Regenerate the typed client from openapi.json
npm run lint && npm run typecheck                                  # ESLint and TypeScript
npm run test                                                       # Vitest
npm run e2e                                                        # Playwright
```

Migrations are mine: never run `alembic revision`, and ask before running `alembic upgrade` or `alembic downgrade`.

## Backend architecture

- Modular monolith. Each module in `backend/app/modules/<name>/` has `router.py`, `schemas.py`, `service.py`, `repository.py`, and `models.py`.
- `router.py`: HTTP only. Validate input, call one service method, declare `response_model`. No queries or business rules.
- `service.py`: business rules, record-level authorization, state transitions, and audit calls. Services own the transaction: one use case, one commit. No `HTTPException`.
- `repository.py`: queries only. Never commits.
- A module may call another module's service, never its repository. `portal` composes other services; `reports` has read-only aggregate queries.
- Services raise domain exceptions from `app/core/errors.py`; exception handlers turn them into the standard error response.
- Synchronous SQLAlchemy 2.x with psycopg 3; database routes are plain `def`, not `async def`.

## Frontend

- React 19, strict TypeScript, and Vite. Code by work area in `frontend/src/features/<area>/`.
- API calls only through TanStack Query hooks built on the generated client in `frontend/src/api/`. After API changes, run `export-openapi` and `npm run api:generate`. Never edit generated files by hand.
- Keep the access token in memory only and refresh through the cookie. Never store tokens in `localStorage`.
- Route guards hide screens a role can't use, but never replace backend checks.
- Forms: React Hook Form with Zod; show errors from the API's standard error format.
- UI: Tailwind CSS and shadcn/ui, with semantic HTML, labeled fields, keyboard support, and visible focus.
- Tests: Vitest and React Testing Library for components; Playwright for end-to-end flows.

## Conventions

- Python 3.13 with type hints; Ruff for lint and format.
- UUID primary keys; `created_at` and `updated_at` as timezone-aware UTC datetimes.
- Enums stored as strings with `Enum(..., native_enum=False)`. Money as `Decimal` in `NUMERIC(12, 2)` columns.
- No hard deletes for clinical, pharmacy, or ticket data; change status instead. Users are deactivated, not deleted.
- Rules that must survive concurrent requests go in the database: unique and partial indexes, CHECK constraints, foreign keys, and row locks.
- Index every foreign key and search column. Avoid N+1 queries with `selectinload`.
- API under `/api/v1`, with plural kebab-case resources. State changes use action endpoints such as `POST /appointments/{id}/check-in`.
- Status codes: 400 can't be processed, 401 unauthenticated, 403 missing permission, 404 not found or outside the user's scope, 409 business conflict, 422 validation error, 429 rate limited.
- Error body: `{"error": {"code": ..., "message": ..., "details": [...], "request_id": ...}}`.
- Lists are paginated with `page` and `size` (maximum 100).
- Conventional Commits: `feat(scope): ...`, `fix(scope): ...`, `test: ...`, `docs: ...`, `refactor: ...`, `chore: ...`.

## Security rules (never break these)

- Every route is explicitly Public, Authenticated, or protected with `require_permission(...)`. Check permissions, never role names.
- Record-level checks live in services. Out-of-scope records return 404.
- Load the current user from the database on every request and reject inactive users.
- Admin and Manager never see clinical data. Managers can never create, promote, or modify Admin or Manager accounts.
- Patients use `/api/v1/portal` endpoints, always scoped to their own record, plus sign-in (`/auth`) and the shared directory (`directory:read`). Every other endpoint rejects the Patient role.
- Refresh tokens are hashed in the database, rotated on use, and sent only in an `HttpOnly`, `SameSite=Strict` cookie that is `Secure` in production.
- Never log or return passwords, password hashes, tokens, or activation codes.
- Secrets come from environment variables only. Never read `backend/.env`, hardcode secrets, or commit them.
- Never weaken, skip, or delete a test or permission check to make something pass. If a test looks wrong, explain why and ask me.

## Definition of Done

Follow the checklist in plan §14: acceptance criteria met, tests covering success, validation, permission, record-level, and conflict cases, migration reviewed, linters and tests passing locally and in CI, OpenAPI documented, detailed docstrings, import comments, and docs updated, review findings resolved, merged and deployed, and I can explain every backend change.
