from __future__ import annotations
from fastapi import APIRouter

router = APIRouter(prefix="/metrics", tags=["Metrics"])


@router.get("")
async def metrics():
    return {"status": "ok"}
