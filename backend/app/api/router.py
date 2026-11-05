"""The versioned API: every module's routes under ``/api/v1``.

Each module's router declares only its own prefix and tag, such as
``/auth`` and ``auth``, and this router adds the version once, so no
module repeats it and a breaking change could add an ``/api/v2`` router
beside this one (plan §11). A module's router is included here once the
module has routes. The health routes are not included: they stay outside
the versioned API so monitoring never has to follow its version.
"""

# Groups the module routers under one shared prefix.
from fastapi import APIRouter

# The auth routes (sign-in, refresh, sign-out, me, password change), included under /api/v1.
from app.modules.auth.router import router as auth_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router)
