from __future__ import annotations
from fastapi import APIRouter

admin_router = APIRouter(prefix="/api/admin/messages", tags=["Messages Admin"])
client_router = APIRouter(prefix="/api/v1/messages", tags=["Messages"])
