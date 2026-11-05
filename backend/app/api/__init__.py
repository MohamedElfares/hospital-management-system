"""HTTP wiring shared by every module: the versioned API, health checks, and caller dependencies.

``router`` gathers each module's routes under ``/api/v1``. ``health``
serves the liveness and readiness checks outside that prefix, so
monitoring never has to follow the API's version. ``deps`` holds the
dependencies a route declares to identify the caller, from the bearer
token to the active user, with the password-change gate on by default.
This package connects HTTP to the modules' services and holds no
business rules of its own.

This file makes the folder a regular package, like every other folder of
application code. Without it, Python would still import the folder, as a
namespace package, but coverage.py would skip it when it looks for files
no test ran, so an untested module here would be missing from the
coverage report instead of counting as 0%.
"""
