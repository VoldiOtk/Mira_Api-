from __future__ import annotations
from fastapi import APIRouter

plans_router = APIRouter(prefix="/api/v1/plans", tags=["Plans"])
subscription_router = APIRouter(prefix="/api/v1/subscription", tags=["Subscription"])
admin_plans_router = APIRouter(prefix="/api/admin/plans", tags=["Plans Admin"])
