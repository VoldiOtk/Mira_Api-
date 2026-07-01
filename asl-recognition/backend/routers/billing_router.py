"""Billing / plans / subscription endpoints for the Mira SaaS frontends.

Three routers are exported and mounted in ``backend/app.py``:

* ``plans_router``        — plan catalogue (``/api/v1/plans``).
* ``subscription_router`` — authenticated client's current plan (``/api/v1/subscription``).
* ``admin_plans_router``  — admin CRUD for plans (``/api/v1/admin/plans``).
"""
from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.auth.dependencies import get_admin, get_current_client_jwt
from backend.database.models import ApiKey, Client, Plan, Subscription
from backend.database.session import get_db

plans_router = APIRouter(prefix="/api/v1/plans", tags=["plans"])
subscription_router = APIRouter(prefix="/api/v1/subscription", tags=["subscription"])
admin_plans_router = APIRouter(prefix="/api/v1/admin/plans", tags=["admin-plans"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class PlanResponse(BaseModel):
    id: int
    slug: str
    name: str
    monthly_price: Optional[float] = None
    annual_price: Optional[float] = None
    currency: str
    monthly_request_limit: int
    rate_limit_per_minute: int
    max_api_keys: int
    support_level: str
    allow_webhooks: bool
    allow_premium_models: bool
    features: Optional[List[str]] = None

    class Config:
        from_attributes = True


class SubscriptionResponse(BaseModel):
    plan: str
    status: str
    current_period_end: Optional[str] = None
    quota_total: int
    quota_used: int


class ChangePlanRequest(BaseModel):
    plan: str


class ChangePlanResponse(BaseModel):
    ok: bool
    plan: str
    message: str


class CreatePlanRequest(BaseModel):
    name: str
    slug: str
    description: Optional[str] = None
    monthly_price: Optional[float] = None
    annual_price: Optional[float] = None
    currency: str = "EUR"
    monthly_request_limit: int
    rate_limit_per_minute: int = 60
    max_api_keys: int = 3
    max_file_size_mb: int = 10
    max_models: int = 3
    allow_premium_models: bool = False
    allow_webhooks: bool = False
    allow_detailed_logs: bool = False
    allow_team_members: bool = False
    support_level: str = "community"
    features: Optional[List[str]] = None


class UpdatePlanRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    monthly_price: Optional[float] = None
    annual_price: Optional[float] = None
    monthly_request_limit: Optional[int] = None
    rate_limit_per_minute: Optional[int] = None
    max_api_keys: Optional[int] = None
    max_file_size_mb: Optional[int] = None
    max_models: Optional[int] = None
    allow_premium_models: Optional[bool] = None
    allow_webhooks: Optional[bool] = None
    allow_detailed_logs: Optional[bool] = None
    allow_team_members: Optional[bool] = None
    support_level: Optional[str] = None
    features: Optional[List[str]] = None
    is_active: Optional[bool] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _client_quota(client: Client, db: Session) -> tuple[int, int]:
    """Return (quota_total, quota_used) aggregated over active keys."""
    row = (
        db.query(
            func.coalesce(func.sum(ApiKey.quota_total), 0),
            func.coalesce(func.sum(ApiKey.quota_used), 0),
        )
        .filter(ApiKey.client_id == client.id, ApiKey.is_active.is_(True))
        .one()
    )
    return int(row[0] or 0), int(row[1] or 0)


def _plan_to_response(plan: Plan) -> PlanResponse:
    features = plan.features if isinstance(plan.features, list) else []
    return PlanResponse(
        id=plan.id,
        slug=plan.slug,
        name=plan.name,
        monthly_price=plan.monthly_price,
        annual_price=plan.annual_price,
        currency=plan.currency,
        monthly_request_limit=plan.monthly_request_limit,
        rate_limit_per_minute=plan.rate_limit_per_minute,
        max_api_keys=plan.max_api_keys,
        support_level=plan.support_level,
        allow_webhooks=plan.allow_webhooks,
        allow_premium_models=plan.allow_premium_models,
        features=features,
    )


# ---------------------------------------------------------------------------
# Public plan catalogue
# ---------------------------------------------------------------------------


@plans_router.get(
    "",
    response_model=List[PlanResponse],
    summary="Public list of subscription plans",
)
def list_plans(db: Session = Depends(get_db)) -> List[PlanResponse]:
    plans = db.query(Plan).filter(Plan.is_active.is_(True)).order_by(Plan.id).all()
    return [_plan_to_response(p) for p in plans]


# ---------------------------------------------------------------------------
# Client subscription
# ---------------------------------------------------------------------------


@subscription_router.get(
    "",
    response_model=SubscriptionResponse,
    summary="Current client's subscription",
)
def get_subscription(
    client: Client = Depends(get_current_client_jwt),
    db: Session = Depends(get_db),
) -> SubscriptionResponse:
    quota_total, quota_used = _client_quota(client, db)
    period_end: Optional[str] = None
    if client.subscription and client.subscription.current_period_end:
        period_end = client.subscription.current_period_end.isoformat()
    sub_status = "active" if client.is_active else "blocked"
    if client.subscription:
        sub_status = client.subscription.status
    return SubscriptionResponse(
        plan=client.plan,
        status=sub_status,
        current_period_end=period_end,
        quota_total=quota_total,
        quota_used=quota_used,
    )


@subscription_router.post(
    "/change",
    response_model=ChangePlanResponse,
    summary="Change the current client's plan",
)
def change_subscription(
    body: ChangePlanRequest,
    client: Client = Depends(get_current_client_jwt),
    db: Session = Depends(get_db),
) -> ChangePlanResponse:
    """Update Client.plan and create/update the Subscription row."""
    slug = (body.plan or "").strip().lower()
    plan = db.query(Plan).filter(Plan.slug == slug, Plan.is_active.is_(True)).first()
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "unknown_plan", "message": f"Plan inconnu: '{body.plan}'."},
        )

    client.plan = slug

    if client.subscription:
        client.subscription.plan_id = plan.id
        client.subscription.status = "active"
        client.subscription.updated_at = datetime.datetime.now(tz=datetime.timezone.utc)
    else:
        sub = Subscription(
            client_id=client.id,
            plan_id=plan.id,
            status="active",
        )
        db.add(sub)

    db.commit()
    db.refresh(client)
    return ChangePlanResponse(
        ok=True,
        plan=client.plan,
        message=f"Plan mis à jour vers '{client.plan}'.",
    )


# ---------------------------------------------------------------------------
# Admin CRUD for plans
# ---------------------------------------------------------------------------


@admin_plans_router.post(
    "",
    response_model=PlanResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new plan (admin)",
)
def create_plan(
    body: CreatePlanRequest,
    _admin: dict = Depends(get_admin),
    db: Session = Depends(get_db),
) -> PlanResponse:
    existing = db.query(Plan).filter(Plan.slug == body.slug).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "slug_exists", "message": f"Un plan avec le slug '{body.slug}' existe déjà."},
        )
    plan = Plan(
        name=body.name,
        slug=body.slug,
        description=body.description,
        monthly_price=body.monthly_price,
        annual_price=body.annual_price,
        currency=body.currency,
        monthly_request_limit=body.monthly_request_limit,
        rate_limit_per_minute=body.rate_limit_per_minute,
        max_api_keys=body.max_api_keys,
        max_file_size_mb=body.max_file_size_mb,
        max_models=body.max_models,
        allow_premium_models=body.allow_premium_models,
        allow_webhooks=body.allow_webhooks,
        allow_detailed_logs=body.allow_detailed_logs,
        allow_team_members=body.allow_team_members,
        support_level=body.support_level,
        features=body.features or [],
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return _plan_to_response(plan)


@admin_plans_router.put(
    "/{plan_id}",
    response_model=PlanResponse,
    summary="Update a plan (admin)",
)
def update_plan(
    plan_id: int,
    body: UpdatePlanRequest,
    _admin: dict = Depends(get_admin),
    db: Session = Depends(get_db),
) -> PlanResponse:
    plan = db.get(Plan, plan_id)
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": "Plan introuvable."},
        )
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(plan, field, value)
    plan.updated_at = datetime.datetime.now(tz=datetime.timezone.utc)
    db.commit()
    db.refresh(plan)
    return _plan_to_response(plan)


@admin_plans_router.delete(
    "/{plan_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate a plan (admin)",
)
def delete_plan(
    plan_id: int,
    _admin: dict = Depends(get_admin),
    db: Session = Depends(get_db),
) -> None:
    plan = db.get(Plan, plan_id)
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": "Plan introuvable."},
        )
    plan.is_active = False
    plan.updated_at = datetime.datetime.now(tz=datetime.timezone.utc)
    db.commit()
