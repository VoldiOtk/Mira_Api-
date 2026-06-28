from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database.session import get_db

router = APIRouter(prefix="/api/v1/auth", tags=["Auth"])

_SECRET = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
_ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@mira.com")
# No default — fail closed if not configured. Set ADMIN_PASSWORD in .env.
_ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD") or ""

# Auto-signup is disabled by default. Set MIRA_ALLOW_AUTO_SIGNUP=true only
# in controlled local-dev environments — never in production.
_ALLOW_AUTO_SIGNUP = os.getenv("MIRA_ALLOW_AUTO_SIGNUP", "false").lower() == "true"

# ── Password hashing (PBKDF2-SHA256, 260 000 iterations, random salt) ─────────
# Using stdlib only — no extra dependency. Constant-time comparison via hmac.
_PBKDF2_ITERS = 260_000


def _hash_password(password: str) -> str:
    salt = os.urandom(32)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERS)
    return base64.b64encode(salt + key).decode("ascii")


def _verify_password(password: str, stored: str) -> bool:
    try:
        raw = base64.b64decode(stored.encode("ascii"))
        salt, stored_key = raw[:32], raw[32:]
        key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERS)
        return hmac.compare_digest(key, stored_key)
    except Exception:
        return False


# ── Token helpers ─────────────────────────────────────────────────────────────

def _make_token(payload: dict, expiry_hours: int = 24) -> str:
    payload = dict(payload)
    payload["exp"] = int(time.time()) + expiry_hours * 3600
    body = json.dumps(payload, separators=(",", ":"))
    body_hex = body.encode().hex()
    sig = hmac.new(_SECRET.encode(), body_hex.encode(), hashlib.sha256).hexdigest()
    return f"{body_hex}.{sig}"


def _verify_token(token: str) -> Optional[dict]:
    try:
        body_hex, sig = token.rsplit(".", 1)
        expected = hmac.new(_SECRET.encode(), body_hex.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(bytes.fromhex(body_hex).decode())
        if payload.get("exp", 0) < int(time.time()):
            return None
        return payload
    except Exception:
        return None


# ── Admin Login ───────────────────────────────────────────────────────────────

class AdminLoginRequest(BaseModel):
    password: str
    email: Optional[str] = None


@router.post("/admin/login")
async def admin_login(body: AdminLoginRequest):
    if not _ADMIN_PASSWORD:
        raise HTTPException(status_code=503, detail="Serveur non configuré : ADMIN_PASSWORD manquant")
    # The React admin SPA sends only {password}. Email is optional and checked
    # only when provided — the server-side env var is always authoritative.
    pass_ok = hmac.compare_digest(body.password, _ADMIN_PASSWORD)
    if body.email is not None:
        email_ok = hmac.compare_digest(body.email, _ADMIN_EMAIL)
        if not (email_ok and pass_ok):
            raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")
    elif not pass_ok:
        raise HTTPException(status_code=401, detail="Mot de passe incorrect")
    admin_email = body.email or _ADMIN_EMAIL
    token = _make_token(
        {"sub": "admin", "email": admin_email, "role": "admin"},
        expiry_hours=24,
    )
    return {
        "access_token": token,
        "token": token,
        "token_type": "bearer",
        "user": {"id": 0, "email": admin_email, "role": "admin", "name": "Administrateur"},
    }


# ── Client Register ───────────────────────────────────────────────────────────

class ClientRegisterRequest(BaseModel):
    email: str
    password: str
    full_name: Optional[str] = None


@router.post("/client/register", status_code=201)
async def client_register(body: ClientRegisterRequest, db: Session = Depends(get_db)):
    from backend.database.models import Client

    existing = db.query(Client).filter(Client.email == body.email).first()
    if existing:
        raise HTTPException(status_code=409, detail="Un compte avec cet email existe déjà")
    client = Client(
        email=body.email,
        full_name=body.full_name or body.email.split("@")[0].title(),
        hashed_password=_hash_password(body.password),
        is_active=True,
    )
    db.add(client)
    db.commit()
    db.refresh(client)
    token = _make_token(
        {"sub": str(client.id), "email": client.email, "role": "client"},
        expiry_hours=24,
    )
    return {
        "access_token": token,
        "token": token,
        "token_type": "bearer",
        "user": {
            "id": client.id,
            "email": client.email,
            "full_name": client.full_name,
            "role": "client",
        },
    }


# ── Client Login ──────────────────────────────────────────────────────────────

class ClientLoginRequest(BaseModel):
    email: str
    password: str


@router.post("/client/login")
async def client_login(body: ClientLoginRequest, db: Session = Depends(get_db)):
    from backend.database.models import Client

    client = db.query(Client).filter(Client.email == body.email).first()

    if not client:
        # Auto-signup only when MIRA_ALLOW_AUTO_SIGNUP=true (local dev only).
        # Disabled by default to prevent account enumeration / bypass.
        if not _ALLOW_AUTO_SIGNUP:
            raise HTTPException(status_code=401, detail="Identifiants invalides")
        client = Client(
            email=body.email,
            full_name=body.email.split("@")[0].title(),
            hashed_password=_hash_password(body.password),
            is_active=True,
        )
        db.add(client)
        db.commit()
        db.refresh(client)
    else:
        stored = getattr(client, "hashed_password", None)
        # Fail closed: a missing or empty hash is never a valid credential.
        if not stored:
            raise HTTPException(status_code=401, detail="Identifiants invalides")
        # Detect legacy SHA-256 hash (64-char hex, no padding) and re-hash on success.
        if len(stored) == 64 and all(c in "0123456789abcdef" for c in stored):
            legacy_ok = hmac.compare_digest(
                hashlib.sha256(body.password.encode()).hexdigest(), stored
            )
            if not legacy_ok:
                raise HTTPException(status_code=401, detail="Identifiants invalides")
            # Upgrade to PBKDF2
            client.hashed_password = _hash_password(body.password)
            db.commit()
        elif not _verify_password(body.password, stored):
            raise HTTPException(status_code=401, detail="Identifiants invalides")

    token = _make_token(
        {"sub": str(client.id), "email": client.email, "role": "client"},
        expiry_hours=24,
    )
    return {
        "access_token": token,
        "token": token,
        "token_type": "bearer",
        "user": {
            "id": client.id,
            "email": client.email,
            "full_name": client.full_name or client.email.split("@")[0].title(),
            "role": "client",
        },
    }


# ── Verify token (utility) ────────────────────────────────────────────────────

@router.get("/me")
async def auth_me(authorization: str = Header(default="")):
    token = (authorization[7:] if authorization.startswith("Bearer ") else authorization).strip()
    payload = _verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Token invalide ou expiré")
    return payload


# ── Admin helpers (require admin token) ───────────────────────────────────────

def _require_admin_token(authorization: str = Header(default="")) -> dict:
    token = (authorization[7:] if authorization.startswith("Bearer ") else authorization).strip()
    payload = _verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Token invalide ou expiré")
    if payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Accès admin requis")
    return payload


# ── Admin: list clients ────────────────────────────────────────────────────────

@router.get("/admin/clients")
async def admin_list_clients(
    page: int = 1,
    limit: int = 20,
    search: str = "",
    auth: dict = Depends(_require_admin_token),
    db: Session = Depends(get_db),
):
    from backend.database.models import Client
    import sqlalchemy as sa
    q = db.query(Client)
    if search:
        q = q.filter(
            sa.or_(
                Client.email.ilike(f"%{search}%"),
                Client.full_name.ilike(f"%{search}%"),
            )
        )
    total = q.count()
    clients = q.order_by(Client.created_at.desc()).offset((page - 1) * limit).limit(limit).all()
    return {
        "clients": [
            {
                "id": c.id,
                "email": c.email,
                "full_name": c.full_name or "",
                "is_active": c.is_active,
                "created_at": str(c.created_at) if c.created_at else None,
                "plan": "starter",
            }
            for c in clients
        ],
        "total": total,
        "page": page,
        "limit": limit,
    }


@router.post("/admin/clients/{client_id}/activate")
async def admin_activate_client(
    client_id: int,
    auth: dict = Depends(_require_admin_token),
    db: Session = Depends(get_db),
):
    from backend.database.models import Client
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client introuvable")
    client.is_active = True
    db.commit()
    return {"ok": True, "client_id": client_id, "is_active": True}


@router.post("/admin/clients/{client_id}/block")
async def admin_block_client(
    client_id: int,
    auth: dict = Depends(_require_admin_token),
    db: Session = Depends(get_db),
):
    from backend.database.models import Client
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client introuvable")
    client.is_active = False
    db.commit()
    return {"ok": True, "client_id": client_id, "is_active": False}


@router.get("/admin/subscriptions")
async def admin_list_subscriptions(
    auth: dict = Depends(_require_admin_token),
    db: Session = Depends(get_db),
):
    from backend.database.models import Client
    clients = db.query(Client).filter(Client.is_active.is_(True)).all()
    return {
        "subscriptions": [
            {
                "client_id": c.id,
                "email": c.email,
                "plan": "starter",
                "status": "active",
                "created_at": str(c.created_at) if c.created_at else None,
            }
            for c in clients
        ],
        "total": len(clients),
    }


# ── Admin: password reset ──────────────────────────────────────────────────────

import secrets as _secrets
import datetime as _datetime


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


@router.post("/admin/forgot-password")
async def admin_forgot_password(body: ForgotPasswordRequest, db: Session = Depends(get_db)):
    if not hmac.compare_digest(body.email, _ADMIN_EMAIL):
        return {"ok": True, "message": "Si l'email est correct, un lien a été envoyé."}

    raw_token = _secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    now = _datetime.datetime.utcnow()
    expires = now + _datetime.timedelta(hours=1)

    try:
        from sqlalchemy import text
        db.execute(
            text("INSERT INTO admin_password_resets (token_hash, used, created_at, expires_at) VALUES (:h, 0, :c, :e)"),
            {"h": token_hash, "c": now.isoformat(), "e": expires.isoformat()},
        )
        db.commit()
    except Exception:
        pass

    reset_url = f"{os.getenv('APP_BASE_URL', 'http://127.0.0.1:8000')}/admin/reset-password?token={raw_token}"
    print(f"[AdminReset] Token URL (dev only): {reset_url}")

    return {"ok": True, "message": "Si l'email est correct, un lien a été envoyé.", "dev_token": raw_token}


@router.post("/admin/reset-password")
async def admin_reset_password(body: ResetPasswordRequest, db: Session = Depends(get_db)):
    token_hash = hashlib.sha256(body.token.encode()).hexdigest()
    now = _datetime.datetime.utcnow().isoformat()
    try:
        from sqlalchemy import text
        row = db.execute(
            text("SELECT id, used, expires_at FROM admin_password_resets WHERE token_hash=:h LIMIT 1"),
            {"h": token_hash},
        ).fetchone()
    except Exception:
        raise HTTPException(status_code=400, detail="Token invalide ou expiré")

    if not row or row[1] or row[2] < now:
        raise HTTPException(status_code=400, detail="Token invalide ou expiré")

    if len(body.new_password) < 8:
        raise HTTPException(status_code=422, detail="Mot de passe trop court (min 8 caractères)")

    try:
        from sqlalchemy import text
        db.execute(
            text("UPDATE admin_password_resets SET used=1 WHERE token_hash=:h"),
            {"h": token_hash},
        )
        db.execute(
            text("INSERT OR REPLACE INTO admin_settings (key, value) VALUES ('hashed_password', :v)"),
            {"v": _hash_password(body.new_password)},
        )
        db.commit()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"ok": True, "message": "Mot de passe réinitialisé avec succès."}
