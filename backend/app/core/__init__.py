"""Cross-cutting infrastructure shared by every backend module.

This package holds code that business modules depend on but that knows
nothing about them: settings, security helpers, permissions, domain errors,
logging, and pagination. Keeping ``core`` free of imports from
``app.modules`` prevents circular dependencies and keeps the modules
independent of each other.
"""
