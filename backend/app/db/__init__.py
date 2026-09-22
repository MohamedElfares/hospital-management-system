"""Database foundation shared by every model and service.

``base`` defines the declarative base class, the constraint naming
convention, and the column mixins that give every table a UUID primary key
and UTC timestamps. ``session`` creates the connection pool and provides one
database session per request. Business modules build their models on
``base`` and receive sessions from ``session``; they never create engines of
their own.
"""
