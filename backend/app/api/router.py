"""The versioned API: every module's routes under ``/api/v1``.

Each module's router declares only its own prefix, such as ``/auth``, and
this router adds the version in one place. A future ``/api/v2`` could then
sit beside it without touching any module. The health routes are not
included here: they stay outside the versioned API so monitoring never has
to follow its version.
"""

# Groups the module routers under one shared prefix.
from fastapi import APIRouter

# Sign-in routes, served under /api/v1/auth.
from app.modules.auth.router import router as auth_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router)
