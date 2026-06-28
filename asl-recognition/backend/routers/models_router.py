from __future__ import annotations
from fastapi import APIRouter

admin_router = APIRouter(prefix="/api/admin/models", tags=["Models Admin"])
public_router = APIRouter(prefix="/api/v1/models", tags=["Models"])
feedback_admin_router = APIRouter(prefix="/api/admin/feedback", tags=["Feedback Admin"])
