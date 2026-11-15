"""Cross-cutting infrastructure shared by every backend module.

This package holds code that business modules depend on but that knows
nothing about them: settings, security helpers, roles and permissions,
domain errors, and logging, with pagination helpers to follow.
``core`` never imports from ``app.modules`` (plan §9), so any module can
import it without creating a circular import.
"""
