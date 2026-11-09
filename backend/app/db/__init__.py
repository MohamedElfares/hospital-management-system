"""Database foundation shared by every model, route, and command.

``base`` defines the declarative base class, the constraint naming
convention, and the column mixins that give every table a UUID primary key
and UTC timestamps. ``session`` builds the one engine and its connection
pool, and hands out sessions: ``get_db`` gives each request its own, and the
CLI opens one with ``SessionLocal``. Models build on ``base``, and services
work in the session they are given, so no business module creates an engine
of its own.

Importing ``base`` needs no settings, so models can be imported without a
``.env`` file. Importing ``session`` builds the engine from
``DATABASE_URL``, so it needs valid settings.
"""
