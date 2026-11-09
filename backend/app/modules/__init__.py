"""Business modules of the modular monolith, one package per work area.

Each module, such as ``users`` or ``auth``, owns its tables and use cases
and splits them into the same layers, one file each: ``router`` handles
HTTP only, ``schemas`` holds the Pydantic request and response models,
``service`` holds the business rules and owns the transaction,
``repository`` runs the queries and never commits, and ``models`` declares
the tables. A module has only the layers it uses: one without routes of
its own has no ``router``.

A module may call another module's service, never its repository, so each
module's data rules stay in one place: ``auth`` reads accounts through the
users service. Modules depend on ``app.core`` and ``app.db``, and those
packages never import from here, so the platform never depends on a
business area (plan §9).
"""
