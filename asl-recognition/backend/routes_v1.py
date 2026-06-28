from __future__ import annotations
from fastapi import APIRouter

router = APIRouter(prefix="/api/v1")


@router.get("/health", tags=["Health"])
async def health():
    return {"status": "ok", "service": "Mira API v1"}
