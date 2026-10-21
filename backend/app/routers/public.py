"""
Campus Ballot — Public Router
Unauthenticated endpoints (health check).
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["public"])


@router.get("/health")
def health_check():
    """Simple health check for Render / Docker HEALTHCHECK."""
    return {"status": "ok"}
