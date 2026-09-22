# ADR-0002: Synchronous SQLAlchemy instead of async

- **Status:** Accepted
- **Date:** 2026-09-22
- **Milestone:** 1.1 Foundation

## Context

FastAPI supports both `async def` and plain `def` routes, and SQLAlchemy 2 offers both a
synchronous API and `AsyncSession` with an async driver. The choice affects every service
and repository written from Milestone 1.2 onward, so it is made once, now.

This project is also a way to learn the architecture: async adds a second set of rules on
top of the ones being learned (sessions, transactions, locking), and a mistake in those
rules is silent rather than loud.

The expected load is a portfolio demo on free hosting: one worker, a handful of concurrent
requests, and a connection pool of 5 with 5 overflow (`app/db/session.py`).

## Decision

Use **synchronous** SQLAlchemy with psycopg 3, and declare database routes as plain `def`.

FastAPI runs a plain `def` route in a **worker thread** (Starlette's
`run_in_threadpool`), so the blocking database call happens off the event loop, which
stays free to accept other requests. With the versions installed here, anyio's default
limit is **40 worker threads**, well above the 10 connections the pool can hand out.

## Alternatives considered

**`async def` routes with `AsyncSession` and an async driver.** Rejected for now: it buys
concurrency this project does not need, and costs clarity it does need. Every service
would be `await`-ed, tests would need an async fixture setup, and libraries used later
must all be async-capable.

**`async def` routes that call the synchronous session.** Rejected outright, and this is
the dangerous option rather than merely an unnecessary one: a blocking call inside a
coroutine **blocks the event loop**, so one slow query stalls every other request in the
process. Mixing the two styles is worse than either style used consistently.

## Consequences

**Gained**

- Ordinary, readable code: no `await` on every repository call, and tracebacks that show
  the actual call stack.
- Simpler tests: the suite uses a plain `Session` in a transaction that is rolled back,
  with no async fixtures or event-loop management.
- Fewer ways to go wrong while the transaction rules are still being learned.

**Given up**

- Concurrency is bounded by the thread pool and the connection pool rather than by the
  event loop, so throughput per process is lower than a fully async stack could reach.
- Each request handled this way occupies a thread for the length of its database work.

**The rule this imposes**

> A route that touches the database is `def`. If a route is `async def`, it must not make
> a blocking call.

**When to revisit**

- Sustained concurrent load where threads, not the database, are the limit.
- Work that is mostly waiting on other network services — several external APIs per
  request — where async would let one thread serve many waits.

Either would justify a new ADR that supersedes this one; migrating means changing the
session type, the repositories and the route signatures, which is mechanical but touches
every module.

## References

- Plan §10 (tech stack, "About ADR-0002"), `backend/app/db/session.py` (pool settings),
  `CLAUDE.md` (database routes are plain `def`).
