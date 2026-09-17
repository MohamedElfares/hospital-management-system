"""Hospital Management System backend application.

The ``app`` package holds the FastAPI application: ``core`` contains
cross-cutting infrastructure such as settings, security, and errors; ``db``
contains the database session and base models; ``api`` wires dependencies
and routers; and ``modules`` contains one package per business area
(patients, appointments, pharmacy, and so on).
"""
