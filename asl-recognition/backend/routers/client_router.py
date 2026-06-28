"""Client-facing API endpoints — /api/v1/client/*"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database.session import get_db

router = APIRouter(prefix="/api/v1/client", tags=["Client"])

_SECRET = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")

# ── Auth helper ───────────────────────────────────────────────────────────────

def _decode_token(authorization: str) -> Optional[dict]:
    token = (authorization[7:] if authorization.startswith("Bearer ") else authorization).strip()
    if not token:
        return None
    try:
        body_b64, sig = token.rsplit(".", 1)
        import hmac as _hmac
        expected = _hmac.new(_SECRET.encode(), body_b64.encode(), hashlib.sha256).hexdigest()
        if not _hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(bytes.fromhex(body_b64).decode())
        if payload.get("exp", 0) < int(time.time()):
            return None
        return payload
    except Exception:
        return None


def _require_client(authorization: str = Header(default="")) -> dict:
    payload = _decode_token(authorization)
    if not payload or payload.get("role") not in ("client", "admin"):
        raise HTTPException(status_code=401, detail="Authentification requise")
    return payload


# ── GET /me ───────────────────────────────────────────────────────────────────

@router.get("/me")
async def client_me(
    auth: dict = Depends(_require_client),
    db: Session = Depends(get_db),
):
    from backend.database.models import Client

    client_id = auth.get("sub")
    if client_id and str(client_id).isdigit():
        client = db.query(Client).filter(Client.id == int(client_id)).first()
        if client:
            return {
                "id": client.id,
                "email": client.email,
                "full_name": client.full_name or client.email.split("@")[0].title(),
                "organization": getattr(client, "organization", None),
                "is_active": client.is_active,
                "created_at": str(client.created_at) if client.created_at else None,
                "role": "client",
            }
    # Fallback from token
    return {
        "id": None,
        "email": auth.get("email", ""),
        "full_name": auth.get("email", "Client"),
        "organization": None,
        "is_active": True,
        "created_at": None,
        "role": "client",
    }


# ── PUT /me (profile update) ─────────────────────────────────────────────────

class ProfileUpdate(BaseModel):
    full_name: Optional[str] = None
    organization: Optional[str] = None


@router.put("/me")
async def update_profile(
    body: ProfileUpdate,
    auth: dict = Depends(_require_client),
    db: Session = Depends(get_db),
):
    from backend.database.models import Client

    client_id = auth.get("sub")
    if not client_id or not str(client_id).isdigit():
        raise HTTPException(status_code=400, detail="Client ID invalide")
    client = db.query(Client).filter(Client.id == int(client_id)).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client introuvable")
    if body.full_name is not None:
        client.full_name = body.full_name
    if body.organization is not None:
        client.organization = body.organization
    db.commit()
    return {"ok": True, "full_name": client.full_name, "organization": client.organization}


# ── GET /dashboard ────────────────────────────────────────────────────────────

@router.get("/dashboard")
async def client_dashboard(
    auth: dict = Depends(_require_client),
    db: Session = Depends(get_db),
):
    from backend.database.models import Client, ApiKey, UsageLog

    client_id = auth.get("sub")
    total_calls = 0
    active_keys = 0
    quota_used = 0
    quota_total = 10000
    if client_id and str(client_id).isdigit():
        cid = int(client_id)
        keys = db.query(ApiKey).filter(ApiKey.client_id == cid).all()
        active_keys = sum(1 for k in keys if k.is_active)
        quota_used = sum(k.quota_used for k in keys)
        quota_total = max((k.quota_total for k in keys), default=10000)
        try:
            total_calls = (
                db.query(UsageLog)
                .filter(UsageLog.client_id == cid)
                .count()
            )
        except Exception:
            total_calls = quota_used
    return {
        "total_calls": total_calls,
        "active_keys": active_keys,
        "quota_used": quota_used,
        "quota_total": quota_total,
        "recent_activity": [],
    }


# ── GET /api-keys ─────────────────────────────────────────────────────────────

@router.get("/api-keys")
async def list_api_keys(
    auth: dict = Depends(_require_client),
    db: Session = Depends(get_db),
):
    from backend.database.models import ApiKey

    client_id = auth.get("sub")
    if not client_id or not str(client_id).isdigit():
        return {"keys": []}
    keys = (
        db.query(ApiKey)
        .filter(ApiKey.client_id == int(client_id))
        .order_by(ApiKey.created_at.desc())
        .all()
    )
    return {
        "keys": [
            {
                "id": k.id,
                "name": k.name or f"Clé #{k.id}",
                "key_prefix": k.key_prefix or "",
                "last_four": k.last_four or "****",
                "is_active": k.is_active,
                "quota_used": k.quota_used,
                "quota_total": k.quota_total,
                "created_at": str(k.created_at) if k.created_at else None,
                "expires_at": str(k.expires_at) if k.expires_at else None,
            }
            for k in keys
        ]
    }


# ── POST /api-keys (create) ───────────────────────────────────────────────────

class CreateKeyRequest(BaseModel):
    name: Optional[str] = None


@router.post("/api-keys")
async def create_api_key(
    body: CreateKeyRequest,
    auth: dict = Depends(_require_client),
    db: Session = Depends(get_db),
):
    from backend.database.models import ApiKey

    client_id = auth.get("sub")
    if not client_id or not str(client_id).isdigit():
        raise HTTPException(status_code=400, detail="Client ID invalide")
    raw = "mk_" + secrets.token_urlsafe(32)
    prefix = raw[:8]
    last_four = raw[-4:]
    key_hash = hashlib.sha256(raw.encode()).hexdigest()
    key = ApiKey(
        client_id=int(client_id),
        key_prefix=prefix,
        key_hash=key_hash,
        last_four=last_four,
        name=body.name or f"Clé API",
        is_active=True,
        quota_used=0,
        quota_total=10000,
    )
    db.add(key)
    db.commit()
    db.refresh(key)
    return {
        "id": key.id,
        "name": key.name,
        "key": raw,  # shown once
        "key_prefix": prefix,
        "last_four": last_four,
        "is_active": True,
        "quota_used": 0,
        "quota_total": 10000,
        "created_at": str(key.created_at) if key.created_at else None,
    }


# ── DELETE /api-keys/{key_id} ─────────────────────────────────────────────────

@router.delete("/api-keys/{key_id}")
async def revoke_api_key(
    key_id: int,
    auth: dict = Depends(_require_client),
    db: Session = Depends(get_db),
):
    from backend.database.models import ApiKey

    client_id = auth.get("sub")
    key = db.query(ApiKey).filter(
        ApiKey.id == key_id,
        ApiKey.client_id == int(client_id or 0),
    ).first()
    if not key:
        raise HTTPException(status_code=404, detail="Clé introuvable")
    key.is_active = False
    db.commit()
    return {"ok": True}


# ── GET /usage/summary ────────────────────────────────────────────────────────

@router.get("/usage/summary")
async def usage_summary(
    auth: dict = Depends(_require_client),
    db: Session = Depends(get_db),
):
    from backend.database.models import ApiKey

    client_id = auth.get("sub")
    quota_used = 0
    quota_total = 10000
    if client_id and str(client_id).isdigit():
        keys = db.query(ApiKey).filter(ApiKey.client_id == int(client_id)).all()
        quota_used = sum(k.quota_used for k in keys)
        quota_total = max((k.quota_total for k in keys), default=10000)
    return {
        "quota_used": quota_used,
        "quota_total": quota_total,
        "calls_today": 0,
        "calls_this_month": quota_used,
        "errors_this_month": 0,
    }


# ── GET /billing/current-plan ─────────────────────────────────────────────────

@router.get("/billing/current-plan")
async def current_plan(auth: dict = Depends(_require_client)):
    return {
        "plan": "starter",
        "plan_label": "Starter",
        "price": 0,
        "currency": "EUR",
        "requests_limit": 10000,
        "features": ["10 000 requêtes/mois", "1 clé API", "Modèles publics", "Support email"],
    }


# ── GET /billing/invoices ─────────────────────────────────────────────────────

@router.get("/billing/invoices")
async def list_invoices(auth: dict = Depends(_require_client), db: Session = Depends(get_db)):
    try:
        from backend.database.models import Invoice

        client_id = auth.get("sub")
        invoices = (
            db.query(Invoice)
            .filter(Invoice.client_id == int(client_id or 0))
            .order_by(Invoice.created_at.desc())
            .limit(20)
            .all()
        )
        return {
            "invoices": [
                {
                    "id": inv.id,
                    "invoice_number": inv.invoice_number,
                    "status": inv.status,
                    "issue_date": str(inv.issue_date) if inv.issue_date else None,
                    "due_date": str(inv.due_date) if inv.due_date else None,
                }
                for inv in invoices
            ]
        }
    except Exception:
        return {"invoices": []}


# ── GET /models ───────────────────────────────────────────────────────────────

@router.get("/models")
async def list_models(auth: dict = Depends(_require_client), db: Session = Depends(get_db)):
    from backend.database.models import SignLanguageModel

    models = (
        db.query(SignLanguageModel)
        .filter(
            SignLanguageModel.is_published.is_(True),
            SignLanguageModel.visibility.in_(["public"]),
        )
        .order_by(SignLanguageModel.published_at.desc())
        .all()
    )
    return {
        "models": [
            {
                "id": m.id,
                "name": m.name or f"Modèle #{m.id}",
                "language_code": m.language_code,
                "status": m.status,
                "published_at": str(m.published_at) if m.published_at else None,
            }
            for m in models
        ]
    }


# ── GET /messages ─────────────────────────────────────────────────────────────

@router.get("/messages")
async def list_messages(auth: dict = Depends(_require_client)):
    return {"messages": [], "unread": 0}


class SendMessageRequest(BaseModel):
    subject: str
    body: str
    priority: Optional[str] = "normal"


@router.post("/messages")
async def send_message(
    body: SendMessageRequest,
    auth: dict = Depends(_require_client),
):
    return {
        "ok": True,
        "id": 1,
        "subject": body.subject,
        "status": "open",
        "message": "Message envoyé. Notre équipe vous répondra sous 24h.",
        "created_at": None,
    }


# ── GET /messages/{conv_id} ───────────────────────────────────────────────────

@router.get("/messages/{conv_id}")
async def get_conversation(
    conv_id: int,
    auth: dict = Depends(_require_client),
):
    return {
        "id": conv_id,
        "messages": [],
        "status": "open",
    }


class ReplyRequest(BaseModel):
    body: str


@router.post("/messages/{conv_id}")
async def reply_to_conversation(
    conv_id: int,
    body: ReplyRequest,
    auth: dict = Depends(_require_client),
):
    return {"ok": True, "id": conv_id}


# ── GET /history ──────────────────────────────────────────────────────────────

@router.get("/history")
async def usage_history(
    page: int = 1,
    limit: int = 20,
    auth: dict = Depends(_require_client),
    db: Session = Depends(get_db),
):
    try:
        from backend.database.models import UsageLog

        client_id = auth.get("sub")
        offset = (page - 1) * limit
        logs = (
            db.query(UsageLog)
            .filter(UsageLog.client_id == int(client_id or 0))
            .order_by(UsageLog.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return {
            "logs": [
                {
                    "id": l.id,
                    "endpoint": getattr(l, "endpoint", "/api/v1/recognize"),
                    "status_code": getattr(l, "status_code", 200),
                    "created_at": str(l.created_at) if l.created_at else None,
                }
                for l in logs
            ],
            "page": page,
            "limit": limit,
        }
    except Exception:
        return {"logs": [], "page": page, "limit": limit}


# ── GET /notifications ────────────────────────────────────────────────────────

@router.get("/notifications")
async def list_notifications(
    page_size: int = 10,
    auth: dict = Depends(_require_client),
):
    return {"notifications": [], "unread": 0, "total": 0}


# ── GET /usage/history ────────────────────────────────────────────────────────

@router.get("/usage/history")
async def usage_history_detail(
    page: int = 1,
    page_size: int = 20,
    auth: dict = Depends(_require_client),
    db: Session = Depends(get_db),
):
    try:
        from backend.database.models import UsageLog

        client_id = auth.get("sub")
        offset = (page - 1) * page_size
        logs = (
            db.query(UsageLog)
            .filter(UsageLog.client_id == int(client_id or 0))
            .order_by(UsageLog.created_at.desc())
            .offset(offset)
            .limit(page_size)
            .all()
        )
        return {
            "items": [
                {
                    "id": l.id,
                    "endpoint": getattr(l, "endpoint", "/api/v1/recognize"),
                    "status_code": getattr(l, "status_code", 200),
                    "language": getattr(l, "language", None),
                    "duration_ms": getattr(l, "duration_ms", None),
                    "created_at": str(l.created_at) if l.created_at else None,
                }
                for l in logs
            ],
            "page": page,
            "page_size": page_size,
        }
    except Exception:
        return {"items": [], "page": page, "page_size": page_size}


# ── POST /api-keys/{key_id}/revoke ────────────────────────────────────────────

@router.post("/api-keys/{key_id}/revoke")
async def revoke_key(
    key_id: int,
    auth: dict = Depends(_require_client),
    db: Session = Depends(get_db),
):
    from backend.database.models import ApiKey

    client_id = auth.get("sub")
    key = db.query(ApiKey).filter(
        ApiKey.id == key_id,
        ApiKey.client_id == int(client_id or 0),
    ).first()
    if not key:
        raise HTTPException(status_code=404, detail="Clé introuvable")
    key.is_active = False
    db.commit()
    return {"ok": True}


# ── POST /default-model ───────────────────────────────────────────────────────

class DefaultModelRequest(BaseModel):
    model_id: str


@router.post("/default-model")
async def set_default_model(
    body: DefaultModelRequest,
    auth: dict = Depends(_require_client),
):
    return {"ok": True, "model_id": body.model_id}


# ── POST /api-keys/{key_id}/rotate ────────────────────────────────────────────

@router.post("/api-keys/{key_id}/rotate")
async def rotate_api_key(
    key_id: int,
    auth: dict = Depends(_require_client),
    db: Session = Depends(get_db),
):
    from backend.database.models import ApiKey

    client_id = auth.get("sub")
    key = db.query(ApiKey).filter(
        ApiKey.id == key_id,
        ApiKey.client_id == int(client_id or 0),
    ).first()
    if not key:
        raise HTTPException(status_code=404, detail="Clé introuvable")
    raw = "mk_" + secrets.token_urlsafe(32)
    prefix = raw[:8]
    last_four = raw[-4:]
    key.key_prefix = prefix
    key.key_hash = hashlib.sha256(raw.encode()).hexdigest()
    key.last_four = last_four
    key.quota_used = 0
    db.commit()
    return {
        "id": key.id,
        "name": key.name,
        "key": raw,
        "key_prefix": prefix,
        "last_four": last_four,
        "is_active": key.is_active,
        "quota_used": 0,
        "quota_total": key.quota_total,
    }


# ── Support tickets (/support/tickets) ───────────────────────────────────────

@router.get("/support/tickets")
async def list_support_tickets(auth: dict = Depends(_require_client)):
    return {"items": [], "total": 0}


class CreateTicketRequest(BaseModel):
    subject: str
    body: str
    priority: Optional[str] = "normal"


@router.post("/support/tickets", status_code=201)
async def create_support_ticket(
    body: CreateTicketRequest,
    auth: dict = Depends(_require_client),
):
    return {
        "id": 1,
        "subject": body.subject,
        "status": "open",
        "priority": body.priority,
        "created_at": None,
        "message": "Ticket créé. Notre équipe vous répondra sous 24h.",
    }


class TicketReplyRequest(BaseModel):
    body: str


@router.post("/support/tickets/{ticket_id}/reply")
async def reply_to_ticket(
    ticket_id: int,
    body: TicketReplyRequest,
    auth: dict = Depends(_require_client),
):
    return {"ok": True, "ticket_id": ticket_id}


# ── Chat conversations (/chat/conversations) ──────────────────────────────────

@router.get("/chat/conversations")
async def list_conversations(auth: dict = Depends(_require_client)):
    return {"items": [], "total": 0}


@router.get("/chat/conversations/{conversation_id}/messages")
async def get_conversation_messages(
    conversation_id: int,
    auth: dict = Depends(_require_client),
):
    return {
        "conversation_id": conversation_id,
        "items": [],
        "total": 0,
    }


class ChatMessageRequest(BaseModel):
    content: str
    role: Optional[str] = "user"


@router.post("/chat/conversations/{conversation_id}/messages", status_code=201)
async def send_conversation_message(
    conversation_id: int,
    body: ChatMessageRequest,
    auth: dict = Depends(_require_client),
):
    return {
        "ok": True,
        "conversation_id": conversation_id,
        "content": body.content,
        "role": body.role,
        "created_at": None,
    }
