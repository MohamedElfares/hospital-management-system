# ADR-0001: A modular monolith instead of microservices

- **Status:** Accepted
- **Date:** 2026-09-22
- **Milestone:** 1.1 Foundation

## Context

The system covers patients, appointments, clinical visits, prescriptions, a multi-branch
pharmacy, customer service and a patient portal (plan §2). These areas are closely
connected rather than independent: checking a patient in opens a visit, a visit produces a
prescription, and dispensing that prescription deducts stock. Several of those steps have
to happen **in one transaction** or not at all — dispensing decrements batches, writes
movement rows, changes the prescription's status and records an audit entry together.

The project is built and maintained by one developer, as a portfolio piece, on free
hosting. So the cost of operating the architecture matters as much as its design.

## Decision

Build one FastAPI application, split internally into modules under
`backend/app/modules/<name>/`, each owning its own tables, and deploy it as a single
container.

Module boundaries are explicit, so they stay real even though everything runs in one
process (plan §9):

- Each module has `router.py`, `schemas.py`, `service.py`, `repository.py` and `models.py`.
- A module may call another module's **service**, never its repository or its tables.
- `core/` holds cross-cutting infrastructure and never imports from `modules/`.

## Alternatives considered

**Microservices, one per area (patients, appointments, pharmacy, …).** Rejected: for this
system it adds cost without solving a problem it has.

- Calls between services would replace ordinary function calls, with serialization,
  retries and timeouts to design.
- Operations that must be atomic today — dispensing, transfers, booking — would become
  distributed transactions needing sagas or compensating actions.
- Each service would need its own deployment, configuration, authentication between
  services, logging and monitoring.
- Free-tier hosting gives one always-on service; several would mean several cold starts.

**One application with no module boundaries.** Rejected: it works at first and then rots.
Without the layering rules above, routers acquire queries, business rules spread, and
extracting anything later becomes a rewrite.

## Consequences

**Gained**

- One database and one transaction, so the rules that must hold under concurrency can be
  enforced with constraints, row locks and a single commit.
- One process to run, test, deploy and debug; a request can be followed end to end in one
  log stream.
- Refactoring across module boundaries is a normal code change, not a contract
  negotiation.

**Given up**

- **Independent scaling.** The pharmacy cannot be scaled separately from the portal; the
  whole application scales together.
- **Independent deployment.** Any change redeploys everything, so a bad release affects
  every area at once.
- **Isolation.** A memory leak or a crash takes down the whole process, not one service.

**Accepted risks and mitigations**

- Boundaries can erode. Mitigated by the dependency rules in plan §9, enforced in review:
  no module imports another module's repository, and services own the transaction.
- If one area genuinely needs its own scaling or deployment later, it can be extracted:
  its tables and its service interface are already separate, so the work is replacing
  in-process calls with an API, rather than untangling shared code.

## References

- Plan §9 (architecture and repository structure), §8.3 (dispensing in one transaction),
  §16 (deployment on one Render service).
