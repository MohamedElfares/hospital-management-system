"""Hospital Management System backend: the FastAPI application and its maintenance CLI.

``main`` builds the application, and ``cli`` holds the maintenance
commands, such as ``create-admin``. The packages divide the rest of the
work by layer. ``core`` holds cross-cutting infrastructure: settings,
password and token security, roles, domain errors, and logging. ``db``
holds the declarative base and column mixins that every model shares, and
the engine and sessions that every request and command uses. ``api``
connects HTTP to the modules: the versioned router, the health checks, and
the dependencies that identify the caller. ``modules`` holds one package
per business area: ``users`` and ``auth`` today, with patients,
appointments, the pharmacy, and the rest added by later milestones
(plan §18).

``core`` and ``db`` never import from ``api`` or ``modules``, so the
platform never depends on a business area (plan §9).
"""
