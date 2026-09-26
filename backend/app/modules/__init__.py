"""Business modules of the modular monolith, one package per work area.

Each module, such as ``users``, owns its tables and use cases and follows
the same layers: ``router`` handles HTTP only, ``service`` holds business
rules and owns the transaction, ``repository`` runs queries, and ``models``
declares the tables. A module may call another module's service, never its
repository, so each module's data rules stay in one place. Modules depend
on ``app.core`` and ``app.db``; those packages never import from here.
"""
