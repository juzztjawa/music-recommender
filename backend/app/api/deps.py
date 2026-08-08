"""Shared FastAPI dependencies (DI).

Phase 1 provides DB/Redis access. `get_current_identity` is a placeholder
that will be implemented in Phase 2 (auth) to resolve the authenticated
tester from the JWT.
"""

from app.db import get_db
from app.redis import get_redis

__all__ = ["get_db", "get_redis"]
