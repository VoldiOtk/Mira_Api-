from __future__ import annotations
from fastapi import APIRouter

router = APIRouter(prefix="/api/admin")
access_router = APIRouter(prefix="/access")


@router.get("/health", tags=["Admin"])
async def admin_health():
    return {"status": "ok", "service": "Mira Admin"}
