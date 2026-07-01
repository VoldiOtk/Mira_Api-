"""Admin routes for client management."""
from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.auth.dependencies import get_admin
from backend.database.models import ApiKey, AuditLog, Client, Plan, Subscription, UsageLog
from backend.database.session import get_db

router = APIRouter(prefix="/api/v1/admin", tags=["admin-clients"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class ClientDetailResponse(BaseModel):
    id: int
    email: str
    name: str
    organization: Optional[str]
    plan: str
    is_active: bool
    stripe_customer_id: Optional[str]
    created_at: str
    subscription: Optional[Dict[str, Any]]
    api_keys_count: int
    quota_used: int
    quota_total: int


class ClientUsageItem(BaseModel):
    id: int
    endpoint: str
    method: str
    status_code: int
    timestamp: str
    inference_ms: Optional[float]


class ClientUsageResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[ClientUsageItem]


class ApiKeyItem(BaseModel):
    id: int
    key_prefix: str
    name: Optional[str]
    label: Optional[str]
    environment: str
    quota_total: int
    quota_used: int
    is_active: bool
    created_at: str
    last_used_at: Optional[str]
    revoked_at: Optional[str]


class ChangePlanBody(BaseModel):
    plan: str


class CreateClientBody(BaseModel):
    email: str
    name: str
    password: str
    plan: str = "free"
    organization: Optional[str] = None


class UpdateClientBody(BaseModel):
    name: Optional[str] = None
    organization: Optional[str] = None
    plan: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_audit(
    db: Session,
    *,
    actor_type: str = "admin",
    actor_id: Optional[int] = None,
    action: str,
    target_type: Optional[str] = None,
    target_id: Optional[int] = None,
    details: Optional[Dict] = None,
    ip_address: Optional[str] = None,
) -> None:
    log = AuditLog(
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        details=details,
        ip_address=ip_address,
    )
    db.add(log)


def _get_client_or_404(client_id: int, db: Session) -> Client:
    client = db.get(Client, client_id)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": "Client introuvable."},
        )
    return client


def _aggregate_quota(client_id: int, db: Session) -> tuple[int, int]:
    row = (
        db.query(
            func.coalesce(func.sum(ApiKey.quota_total), 0),
            func.coalesce(func.sum(ApiKey.quota_used), 0),
        )
        .filter(ApiKey.client_id == client_id, ApiKey.is_active.is_(True))
        .one()
    )
    return int(row[0] or 0), int(row[1] or 0)


def _build_client_detail(client: Client, db: Session) -> ClientDetailResponse:
    quota_total, quota_used = _aggregate_quota(client.id, db)
    keys_count = (
        db.query(func.count(ApiKey.id))
        .filter(ApiKey.client_id == client.id, ApiKey.is_active.is_(True))
        .scalar()
        or 0
    )
    sub_data: Optional[Dict] = None
    if client.subscription:
        sub = client.subscription
        sub_data = {
            "status": sub.status,
            "plan_id": sub.plan_id,
            "plan_slug": sub.plan.slug if sub.plan else None,
            "stripe_subscription_id": sub.stripe_subscription_id,
            "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
        }
    return ClientDetailResponse(
        id=client.id,
        email=client.email,
        name=client.name,
        organization=client.organization,
        plan=client.plan,
        is_active=client.is_active,
        stripe_customer_id=client.stripe_customer_id,
        created_at=client.created_at.isoformat(),
        subscription=sub_data,
        api_keys_count=keys_count,
        quota_used=quota_used,
        quota_total=quota_total,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/clients/{client_id}",
    response_model=ClientDetailResponse,
    summary="Full client detail (admin)",
)
def get_client_detail(
    client_id: int,
    _admin: dict = Depends(get_admin),
    db: Session = Depends(get_db),
) -> ClientDetailResponse:
    client = _get_client_or_404(client_id, db)
    return _build_client_detail(client, db)


@router.get(
    "/clients/{client_id}/usage",
    response_model=ClientUsageResponse,
    summary="Paginated usage logs for a client (admin)",
)
def get_client_usage(
    client_id: int,
    page: int = 1,
    page_size: int = 50,
    _admin: dict = Depends(get_admin),
    db: Session = Depends(get_db),
) -> ClientUsageResponse:
    _get_client_or_404(client_id, db)
    page_size = min(max(page_size, 1), 200)
    offset = (max(page, 1) - 1) * page_size

    total = (
        db.query(func.count(UsageLog.id))
        .filter(UsageLog.client_id == client_id)
        .scalar()
        or 0
    )
    rows = (
        db.query(UsageLog)
        .filter(UsageLog.client_id == client_id)
        .order_by(UsageLog.timestamp.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )
    items = [
        ClientUsageItem(
            id=r.id,
            endpoint=r.endpoint,
            method=r.method,
            status_code=r.status_code,
            timestamp=r.timestamp.isoformat(),
            inference_ms=r.inference_ms,
        )
        for r in rows
    ]
    return ClientUsageResponse(total=total, page=page, page_size=page_size, items=items)


@router.get(
    "/clients/{client_id}/api-keys",
    response_model=List[ApiKeyItem],
    summary="List API keys for a client (admin, no secrets)",
)
def list_client_api_keys(
    client_id: int,
    _admin: dict = Depends(get_admin),
    db: Session = Depends(get_db),
) -> List[ApiKeyItem]:
    _get_client_or_404(client_id, db)
    keys = (
        db.query(ApiKey)
        .filter(ApiKey.client_id == client_id)
        .order_by(ApiKey.created_at.desc())
        .all()
    )
    return [
        ApiKeyItem(
            id=k.id,
            key_prefix=k.key_prefix,
            name=k.name,
            label=k.label,
            environment=k.environment,
            quota_total=k.quota_total,
            quota_used=k.quota_used,
            is_active=k.is_active,
            created_at=k.created_at.isoformat(),
            last_used_at=k.last_used_at.isoformat() if k.last_used_at else None,
            revoked_at=k.revoked_at.isoformat() if k.revoked_at else None,
        )
        for k in keys
    ]


@router.post(
    "/clients/{client_id}/api-keys/{key_id}/revoke",
    status_code=status.HTTP_200_OK,
    summary="Revoke an API key (admin)",
)
def revoke_api_key(
    client_id: int,
    key_id: int,
    request: Request,
    _admin: dict = Depends(get_admin),
    db: Session = Depends(get_db),
) -> dict:
    _get_client_or_404(client_id, db)
    key = db.query(ApiKey).filter(ApiKey.id == key_id, ApiKey.client_id == client_id).first()
    if key is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": "Clé API introuvable."},
        )
    key.is_active = False
    key.revoked_at = datetime.datetime.now(tz=datetime.timezone.utc)
    _write_audit(
        db,
        action="key.revoke",
        target_type="api_key",
        target_id=key_id,
        details={"client_id": client_id, "key_prefix": key.key_prefix},
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return {"ok": True, "message": f"Clé {key_id} révoquée."}


@router.post(
    "/clients/{client_id}/change-plan",
    status_code=status.HTTP_200_OK,
    summary="Change a client's plan and update subscription (admin)",
)
def admin_change_plan(
    client_id: int,
    body: ChangePlanBody,
    request: Request,
    _admin: dict = Depends(get_admin),
    db: Session = Depends(get_db),
) -> dict:
    client = _get_client_or_404(client_id, db)
    slug = (body.plan or "").strip().lower()
    plan = db.query(Plan).filter(Plan.slug == slug, Plan.is_active.is_(True)).first()
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "unknown_plan", "message": f"Plan inconnu: '{body.plan}'."},
        )

    old_plan = client.plan
    client.plan = slug

    # Update or create subscription
    if client.subscription:
        client.subscription.plan_id = plan.id
        client.subscription.status = "active"
        client.subscription.updated_at = datetime.datetime.now(tz=datetime.timezone.utc)
    else:
        sub = Subscription(client_id=client.id, plan_id=plan.id, status="active")
        db.add(sub)

    # Adjust quota_total on all active keys
    new_quota = plan.monthly_request_limit
    active_keys = (
        db.query(ApiKey)
        .filter(ApiKey.client_id == client_id, ApiKey.is_active.is_(True))
        .all()
    )
    for key in active_keys:
        key.quota_total = new_quota

    _write_audit(
        db,
        action="client.change_plan",
        target_type="client",
        target_id=client_id,
        details={"old_plan": old_plan, "new_plan": slug, "new_quota": new_quota},
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return {"ok": True, "plan": slug, "new_quota": new_quota}


@router.post(
    "/clients/{client_id}/reset-quota",
    status_code=status.HTTP_200_OK,
    summary="Reset quota_used=0 on all active keys (admin)",
)
def reset_client_quota(
    client_id: int,
    request: Request,
    _admin: dict = Depends(get_admin),
    db: Session = Depends(get_db),
) -> dict:
    _get_client_or_404(client_id, db)
    keys = (
        db.query(ApiKey)
        .filter(ApiKey.client_id == client_id, ApiKey.is_active.is_(True))
        .all()
    )
    for key in keys:
        key.quota_used = 0
    _write_audit(
        db,
        action="client.reset_quota",
        target_type="client",
        target_id=client_id,
        details={"keys_reset": len(keys)},
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return {"ok": True, "keys_reset": len(keys)}


@router.post(
    "/clients",
    response_model=ClientDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a client (admin)",
)
def create_client(
    body: CreateClientBody,
    request: Request,
    _admin: dict = Depends(get_admin),
    db: Session = Depends(get_db),
) -> ClientDetailResponse:
    existing = db.query(Client).filter(Client.email == body.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "email_exists", "message": "Cet email est déjà utilisé."},
        )
    plan = db.query(Plan).filter(Plan.slug == body.plan, Plan.is_active.is_(True)).first()

    from passlib.context import CryptContext
    _pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
    hashed = _pwd.hash(body.password)

    client = Client(
        email=body.email,
        name=body.name,
        hashed_password=hashed,
        plan=body.plan,
        organization=body.organization,
        is_active=True,
    )
    db.add(client)
    db.flush()

    if plan:
        sub = Subscription(client_id=client.id, plan_id=plan.id, status="active")
        db.add(sub)

    _write_audit(
        db,
        action="client.create",
        target_type="client",
        target_id=client.id,
        details={"email": body.email, "plan": body.plan},
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(client)
    return _build_client_detail(client, db)


@router.put(
    "/clients/{client_id}",
    response_model=ClientDetailResponse,
    summary="Update client name/org/plan (admin)",
)
def update_client(
    client_id: int,
    body: UpdateClientBody,
    request: Request,
    _admin: dict = Depends(get_admin),
    db: Session = Depends(get_db),
) -> ClientDetailResponse:
    client = _get_client_or_404(client_id, db)
    changes: Dict[str, Any] = {}

    if body.name is not None:
        changes["name"] = body.name
        client.name = body.name
    if body.organization is not None:
        changes["organization"] = body.organization
        client.organization = body.organization
    if body.plan is not None:
        slug = body.plan.strip().lower()
        plan = db.query(Plan).filter(Plan.slug == slug, Plan.is_active.is_(True)).first()
        if plan is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "unknown_plan", "message": f"Plan inconnu: '{body.plan}'."},
            )
        changes["plan"] = slug
        client.plan = slug
        if client.subscription:
            client.subscription.plan_id = plan.id
            client.subscription.updated_at = datetime.datetime.now(tz=datetime.timezone.utc)

    _write_audit(
        db,
        action="client.update",
        target_type="client",
        target_id=client_id,
        details=changes,
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(client)
    return _build_client_detail(client, db)
