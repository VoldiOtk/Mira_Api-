"""
Unified admin router — all /api/v1/admin/* endpoints.
Requires a valid admin JWT (role == "admin") on every route.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database.session import get_db

router = APIRouter(prefix="/api/v1/admin", tags=["Admin"])

_SECRET = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")


# ── Auth dependency ────────────────────────────────────────────────────────────

def _require_admin(authorization: str = Header(default="")) -> dict:
    token = (authorization[7:] if authorization.startswith("Bearer ") else authorization).strip()
    if not token:
        raise HTTPException(status_code=401, detail="Token admin requis")
    try:
        import hmac as _hmac
        body_hex, sig = token.rsplit(".", 1)
        expected = _hmac.new(_SECRET.encode(), body_hex.encode(), hashlib.sha256).hexdigest()
        if not _hmac.compare_digest(sig, expected):
            raise HTTPException(status_code=401, detail="Token invalide")
        payload = json.loads(bytes.fromhex(body_hex).decode())
        if payload.get("exp", 0) < int(time.time()):
            raise HTTPException(status_code=401, detail="Token expiré")
        if payload.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Accès admin requis")
        return payload
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Token invalide")


# ══════════════════════════════════════════════════════════════════════════════
#  DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/dashboard/summary")
async def dashboard_summary(
    auth: dict = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    from backend.database.models import Client, ApiKey
    import sqlalchemy as sa
    total_clients = db.query(Client).count()
    active_clients = db.query(Client).filter(Client.is_active.is_(True)).count()
    blocked_clients = db.query(Client).filter(Client.is_active.is_(False)).count()
    total_keys = db.query(ApiKey).count()
    active_keys = db.query(ApiKey).filter(ApiKey.is_active.is_(True)).count()
    total_calls = int(db.query(ApiKey).with_entities(
        sa.func.coalesce(sa.func.sum(ApiKey.quota_used), 0)
    ).scalar() or 0)
    total_quota_total = int(db.query(ApiKey).with_entities(
        sa.func.coalesce(sa.func.sum(ApiKey.quota_total), 0)
    ).scalar() or 0)
    try:
        from backend.database.models import SignLanguageModel
        total_models = db.query(SignLanguageModel).count()
        published_models = db.query(SignLanguageModel).filter(SignLanguageModel.is_published.is_(True)).count()
    except Exception:
        total_models = published_models = 0
    try:
        from backend.database.models import Dataset
        total_datasets = db.query(Dataset).count()
        valid_datasets = db.query(Dataset).filter(Dataset.status == "valid").count()
    except Exception:
        total_datasets = valid_datasets = 0
    try:
        from backend.database.models import TrainingJob
        total_training_jobs = db.query(TrainingJob).count()
        running_jobs = db.query(TrainingJob).filter(TrainingJob.status == "running").count()
    except Exception:
        total_training_jobs = running_jobs = 0
    return {
        "total_clients": total_clients,
        "active_clients": active_clients,
        "blocked_clients": blocked_clients,
        "new_clients_this_month": 0,
        "total_api_keys": total_keys,
        "active_api_keys": active_keys,
        "total_api_calls": total_calls,
        "api_calls_today": 0,
        "api_calls_this_month": total_calls,
        "total_quota_used": total_calls,
        "total_quota_total": total_quota_total or 10000,
        "error_rate": 0.0,
        "revenue_this_month": 0.0,
        "revenue_total": 0.0,
        "total_models": total_models,
        "published_models": published_models,
        "total_datasets": total_datasets,
        "valid_datasets": valid_datasets,
        "total_training_jobs": total_training_jobs,
        "running_jobs": running_jobs,
        "by_plan": {"free": 0, "starter": active_clients, "pro": 0, "enterprise": 0},
    }


@router.get("/dashboard/revenue")
async def dashboard_revenue(
    period: str = "month",
    auth: dict = Depends(_require_admin),
):
    return {
        "period": period,
        "total_mrr": 0,
        "total_arr": 0,
        "currency": "EUR",
        "breakdown": [],
    }


@router.get("/dashboard/request-sources")
async def dashboard_request_sources(auth: dict = Depends(_require_admin)):
    return {"sources": [], "total": 0}


@router.get("/dashboard/top-languages")
async def dashboard_top_languages(auth: dict = Depends(_require_admin)):
    return {"languages": [], "total": 0}


@router.get("/dashboard/usage-history")
async def dashboard_usage_history(
    months: int = 6,
    auth: dict = Depends(_require_admin),
):
    import datetime
    now = datetime.datetime.utcnow()
    history = []
    for i in range(months - 1, -1, -1):
        d = now - datetime.timedelta(days=30 * i)
        history.append({"label": d.strftime("%b %Y"), "calls": 0})
    return {"history": history, "total": 0}


@router.get("/dashboard/support-summary")
async def dashboard_support_summary(auth: dict = Depends(_require_admin)):
    return {
        "total_tickets": 0,
        "open_tickets": 0,
        "resolved_tickets": 0,
        "avg_response_hours": None,
        "note": "Aucun ticket de support pour le moment.",
    }


# ══════════════════════════════════════════════════════════════════════════════
#  CLIENTS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/clients")
async def list_clients(
    page: int = 1,
    limit: int = 20,
    search: str = "",
    auth: dict = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    from backend.database.models import Client, ApiKey
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
    result = []
    for c in clients:
        keys = db.query(ApiKey).filter(ApiKey.client_id == c.id).all()
        result.append({
            "id": c.id,
            "email": c.email,
            "full_name": c.full_name or "",
            "organization": getattr(c, "organization", "") or "",
            "is_active": c.is_active,
            "created_at": str(c.created_at) if c.created_at else None,
            "plan": "starter",
            "api_keys_count": len(keys),
            "quota_used": sum(k.quota_used for k in keys),
            "quota_total": max((k.quota_total for k in keys), default=10000),
        })
    return {"clients": result, "total": total, "page": page, "limit": limit}


@router.get("/clients/{client_id}/api-keys")
async def admin_client_api_keys(
    client_id: int,
    auth: dict = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    from backend.database.models import ApiKey
    keys = db.query(ApiKey).filter(ApiKey.client_id == client_id).all()
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
            }
            for k in keys
        ]
    }


@router.post("/clients/{client_id}/api-keys/{key_id}/revoke")
async def admin_revoke_key(
    client_id: int,
    key_id: int,
    auth: dict = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    from backend.database.models import ApiKey
    key = db.query(ApiKey).filter(ApiKey.id == key_id, ApiKey.client_id == client_id).first()
    if not key:
        raise HTTPException(status_code=404, detail="Clé introuvable")
    key.is_active = False
    db.commit()
    return {"ok": True}


class ChangePlanRequest(BaseModel):
    plan: str


@router.post("/clients/{client_id}/change-plan")
async def admin_change_plan(
    client_id: int,
    body: ChangePlanRequest,
    auth: dict = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    from backend.database.models import Client
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client introuvable")
    return {"ok": True, "client_id": client_id, "plan": body.plan}


@router.post("/clients/{client_id}/reset-quota")
async def admin_reset_quota(
    client_id: int,
    auth: dict = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    from backend.database.models import ApiKey
    db.query(ApiKey).filter(ApiKey.client_id == client_id).update({"quota_used": 0})
    db.commit()
    return {"ok": True}


# ══════════════════════════════════════════════════════════════════════════════
#  MODELS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/models/")
async def admin_list_models(
    auth: dict = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    from backend.database.models import SignLanguageModel
    models = db.query(SignLanguageModel).order_by(SignLanguageModel.created_at.desc()).all()
    return {
        "models": [
            {
                "id": m.id,
                "name": m.name or f"Modèle #{m.id}",
                "slug": m.slug,
                "language_code": m.language_code,
                "status": m.status,
                "is_published": m.is_published,
                "published_at": str(m.published_at) if m.published_at else None,
                "visibility": getattr(m, "visibility", "public"),
                "created_at": str(m.created_at) if m.created_at else None,
            }
            for m in models
        ]
    }


@router.get("/models/{model_id}")
async def admin_get_model(
    model_id: int,
    auth: dict = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    from backend.database.models import SignLanguageModel
    m = db.query(SignLanguageModel).filter(SignLanguageModel.id == model_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="Modèle introuvable")
    return {"id": m.id, "name": m.name, "language_code": m.language_code, "status": m.status,
            "is_published": m.is_published, "visibility": getattr(m, "visibility", "public")}


@router.post("/models/{model_id}/publish")
async def admin_publish_model(
    model_id: int,
    auth: dict = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    from backend.database.models import SignLanguageModel
    import datetime
    m = db.query(SignLanguageModel).filter(SignLanguageModel.id == model_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="Modèle introuvable")
    m.is_published = True
    m.status = "published"
    m.published_at = datetime.datetime.utcnow()
    db.commit()
    return {"ok": True, "model_id": model_id}


@router.post("/models/{model_id}/archive")
async def admin_archive_model(
    model_id: int,
    auth: dict = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    from backend.database.models import SignLanguageModel
    m = db.query(SignLanguageModel).filter(SignLanguageModel.id == model_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="Modèle introuvable")
    m.is_published = False
    m.status = "archived"
    db.commit()
    return {"ok": True}


class VisibilityRequest(BaseModel):
    visibility: str


@router.post("/models/{model_id}/visibility")
async def admin_set_model_visibility(
    model_id: int,
    body: VisibilityRequest,
    auth: dict = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    from backend.database.models import SignLanguageModel
    m = db.query(SignLanguageModel).filter(SignLanguageModel.id == model_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="Modèle introuvable")
    m.visibility = body.visibility
    db.commit()
    return {"ok": True}


@router.get("/models/{model_id}/versions")
async def admin_model_versions(model_id: int, auth: dict = Depends(_require_admin)):
    return {"versions": []}


@router.post("/models/{model_id}/rollback")
async def admin_model_rollback(model_id: int, auth: dict = Depends(_require_admin)):
    return {"ok": True}


# ══════════════════════════════════════════════════════════════════════════════
#  KNOWLEDGE BASES
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/knowledge-bases/")
async def admin_list_kb(
    auth: dict = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    # The React component does Array.isArray(t.data) — must return a plain array.
    try:
        from backend.database.models import KnowledgeBase
        kbs = db.query(KnowledgeBase).order_by(KnowledgeBase.created_at.desc()).all()
        return [
            {
                "id": kb.id,
                "name": kb.name,
                "slug": kb.slug,
                "language_code": kb.language_code,
                "language_name": getattr(kb, "language_name", None),
                "status": kb.status,
                "description": getattr(kb, "description", None),
                "total_classes": kb.total_classes or 0,
                "total_images": kb.total_images or 0,
                "total_videos": kb.total_videos or 0,
                "total_files": kb.total_files or 0,
                "root_path": kb.root_path,
                "last_scanned_at": str(kb.last_scanned_at) if kb.last_scanned_at else None,
                "created_at": str(kb.created_at) if kb.created_at else None,
            }
            for kb in kbs
        ]
    except Exception:
        return []


# GET /knowledge-bases/scan-all must be declared BEFORE /knowledge-bases/{kb_id}
# so FastAPI matches the literal segment first.
@router.get("/knowledge-bases/scan-all")
@router.post("/knowledge-bases/scan-all")
async def admin_scan_all_kb(auth: dict = Depends(_require_admin), db: Session = Depends(get_db)):
    try:
        from backend.services.knowledge_scanner import sync_knowledge_bases
        created = sync_knowledge_bases(db)
        from backend.database.models import KnowledgeBase
        total = db.query(KnowledgeBase).count()
        return {"ok": True, "created": len(created), "total": total}
    except Exception as e:
        return {"ok": False, "detail": str(e)}


@router.get("/knowledge-bases/{kb_id}")
async def admin_get_kb(kb_id: int, auth: dict = Depends(_require_admin), db: Session = Depends(get_db)):
    try:
        from backend.database.models import KnowledgeBase
        kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
        if not kb:
            raise HTTPException(status_code=404, detail="Base de connaissances introuvable")
        return {
            "id": kb.id,
            "name": kb.name,
            "slug": kb.slug,
            "status": kb.status,
            "language_code": kb.language_code,
            "language_name": getattr(kb, "language_name", None),
            "description": getattr(kb, "description", None),
            "root_path": kb.root_path,
            "total_classes": kb.total_classes or 0,
            "total_images": kb.total_images or 0,
            "total_videos": kb.total_videos or 0,
            "total_files": kb.total_files or 0,
            "last_scanned_at": str(kb.last_scanned_at) if kb.last_scanned_at else None,
            "created_at": str(kb.created_at) if kb.created_at else None,
        }
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=404, detail="Base de connaissances introuvable")


@router.delete("/knowledge-bases/{kb_id}")
async def admin_delete_kb(kb_id: int, auth: dict = Depends(_require_admin), db: Session = Depends(get_db)):
    from backend.database.models import KnowledgeBase
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Base de connaissances introuvable")
    db.delete(kb)
    db.commit()
    return {"ok": True}


@router.post("/knowledge-bases/{kb_id}/scan")
async def admin_scan_kb(kb_id: int, auth: dict = Depends(_require_admin), db: Session = Depends(get_db)):
    from backend.database.models import KnowledgeBase
    from backend.services.knowledge_scanner import _count_dir
    import datetime
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Base de connaissances introuvable")
    counts = _count_dir(kb.root_path)
    kb.total_classes = counts["total_classes"]
    kb.total_images = counts["total_images"]
    kb.total_videos = counts["total_videos"]
    kb.total_files = counts["total_files"]
    kb.status = "ready"
    kb.last_scanned_at = datetime.datetime.utcnow()
    db.commit()
    return {"ok": True, "kb_id": kb_id, **counts}


@router.get("/knowledge-bases/{kb_id}/labels")
async def admin_kb_labels(kb_id: int, auth: dict = Depends(_require_admin), db: Session = Depends(get_db)):
    import json
    from backend.database.models import KnowledgeBase
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb:
        return {"labels": {}, "count": 0}
    if kb.labels_file_path and os.path.isfile(kb.labels_file_path):
        try:
            with open(kb.labels_file_path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return {"labels": data, "count": len(data)}
            if isinstance(data, list):
                labels = {str(x): {"en": str(x)} for x in data}
                return {"labels": labels, "count": len(labels)}
        except Exception:
            pass
    # Fallback: build labels from class subdirectories
    if kb.root_path and os.path.isdir(kb.root_path):
        labels = {}
        for entry in sorted(os.scandir(kb.root_path), key=lambda e: e.name):
            if entry.is_dir(follow_symlinks=False):
                labels[entry.name] = {"en": entry.name}
        return {"labels": labels, "count": len(labels)}
    return {"labels": {}, "count": 0}


@router.get("/knowledge-bases/{kb_id}/tree")
async def admin_kb_tree(
    kb_id: int,
    depth: int = 2,
    auth: dict = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    from backend.database.models import KnowledgeBase

    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb or not kb.root_path or not os.path.isdir(kb.root_path):
        return {"root_path": "", "tree": []}

    def _build(path: str, remaining_depth: int, limit: int) -> list:
        nodes = []
        try:
            entries = sorted(os.scandir(path), key=lambda e: (e.is_file(), e.name.lower()))
        except OSError:
            return nodes
        for i, entry in enumerate(entries):
            if i >= limit:
                left = sum(1 for _ in os.scandir(path)) - limit
                nodes.append({"name": f"… {left} autre(s)", "type": "file", "extension": "", "size": None})
                break
            if entry.is_dir(follow_symlinks=False):
                try:
                    child_count = sum(1 for _ in os.scandir(entry.path))
                except OSError:
                    child_count = 0
                children = _build(entry.path, remaining_depth - 1, 20) if remaining_depth > 1 else []
                nodes.append({
                    "name": entry.name,
                    "type": "dir",
                    "children_count": child_count,
                    "children": children,
                })
            else:
                try:
                    size = entry.stat(follow_symlinks=False).st_size
                except OSError:
                    size = None
                nodes.append({
                    "name": entry.name,
                    "type": "file",
                    "extension": os.path.splitext(entry.name)[1].lower(),
                    "size": size,
                })
        return nodes

    tree = _build(kb.root_path, depth, limit=100)
    return {"root_path": kb.root_path, "tree": tree}


@router.post("/knowledge-bases/{kb_id}/train")
async def admin_kb_train(kb_id: int, auth: dict = Depends(_require_admin)):
    return {"ok": True, "job_id": None}


@router.post("/knowledge-bases/{kb_id}/validate")
async def admin_kb_validate(kb_id: int, auth: dict = Depends(_require_admin)):
    return {"ok": True, "valid": True}


@router.post("/knowledge-bases/upload")
async def admin_kb_upload(auth: dict = Depends(_require_admin)):
    return {"ok": True}


# ══════════════════════════════════════════════════════════════════════════════
#  TRAINING JOBS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/training/jobs")
async def admin_list_training_jobs(
    auth: dict = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    from backend.database.models import TrainingJob
    jobs = db.query(TrainingJob).order_by(TrainingJob.created_at.desc()).limit(50).all()
    return {
        "jobs": [
            {
                "id": j.id,
                "language_code": j.language_code,
                "status": j.status,
                "progress": j.progress,
                "created_at": str(j.created_at) if j.created_at else None,
            }
            for j in jobs
        ]
    }


@router.post("/training/jobs/{job_id}/cancel")
async def admin_cancel_training(
    job_id: int,
    auth: dict = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    from backend.database.models import TrainingJob
    job = db.query(TrainingJob).filter(TrainingJob.id == job_id).first()
    if job:
        job.status = "cancelled"
        db.commit()
    return {"ok": True}


# ══════════════════════════════════════════════════════════════════════════════
#  DATASETS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/datasets/")
async def admin_list_datasets(
    auth: dict = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    from backend.database.models import Dataset
    datasets = db.query(Dataset).all()
    return {
        "datasets": [
            {"id": d.id, "name": d.name, "language_code": d.language_code,
             "status": d.status, "created_at": str(d.created_at) if d.created_at else None}
            for d in datasets
        ]
    }


@router.get("/datasets/{dataset_id}")
async def admin_get_dataset(dataset_id: int, auth: dict = Depends(_require_admin), db: Session = Depends(get_db)):
    from backend.database.models import Dataset
    d = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="Dataset introuvable")
    return {"id": d.id, "name": d.name, "language_code": d.language_code, "status": d.status}


@router.post("/datasets/{dataset_id}/validate")
async def admin_validate_dataset(dataset_id: int, auth: dict = Depends(_require_admin)):
    return {"ok": True, "valid": True}


# ══════════════════════════════════════════════════════════════════════════════
#  ERRORS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/errors/summary")
async def admin_errors_summary(auth: dict = Depends(_require_admin)):
    return {"total_errors": 0, "errors_today": 0, "top_endpoints": []}


@router.get("/errors")
async def admin_list_errors(
    page: int = 1,
    limit: int = 20,
    auth: dict = Depends(_require_admin),
):
    return {"errors": [], "total": 0, "page": page, "limit": limit}


# ══════════════════════════════════════════════════════════════════════════════
#  FEEDBACK
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/feedback/stats")
async def admin_feedback_stats(auth: dict = Depends(_require_admin)):
    return {"total": 0, "pending": 0, "reviewed": 0}


@router.get("/feedback")
async def admin_list_feedback(
    page: int = 1,
    limit: int = 20,
    auth: dict = Depends(_require_admin),
):
    return {"feedback": [], "total": 0, "page": page, "limit": limit}


@router.post("/feedback/{feedback_id}/review")
async def admin_review_feedback(
    feedback_id: int,
    auth: dict = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    return {"ok": True}


# ══════════════════════════════════════════════════════════════════════════════
#  MESSAGES
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/messages")
async def admin_list_messages(auth: dict = Depends(_require_admin)):
    return {"messages": [], "unread": 0}


@router.get("/messages/{message_id}")
async def admin_get_message(message_id: int, auth: dict = Depends(_require_admin)):
    raise HTTPException(status_code=404, detail="Message introuvable")


@router.post("/messages/{message_id}/read")
async def admin_mark_message_read(message_id: int, auth: dict = Depends(_require_admin)):
    return {"ok": True}


# ══════════════════════════════════════════════════════════════════════════════
#  INVOICES
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/invoices/")
async def admin_list_invoices(
    page: int = 1,
    limit: int = 20,
    auth: dict = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    try:
        from backend.database.models import Invoice
        total = db.query(Invoice).count()
        invoices = db.query(Invoice).order_by(Invoice.created_at.desc()).offset((page-1)*limit).limit(limit).all()
        return {
            "invoices": [
                {
                    "id": inv.id,
                    "invoice_number": inv.invoice_number,
                    "client_id": inv.client_id,
                    "client_name": inv.client_name,
                    "client_email": inv.client_email,
                    "status": inv.status,
                    "issue_date": str(inv.issue_date) if inv.issue_date else None,
                    "due_date": str(inv.due_date) if inv.due_date else None,
                }
                for inv in invoices
            ],
            "total": total, "page": page, "limit": limit
        }
    except Exception:
        return {"invoices": [], "total": 0, "page": page, "limit": limit}


@router.get("/invoices/{invoice_id}")
async def admin_get_invoice(invoice_id: int, auth: dict = Depends(_require_admin), db: Session = Depends(get_db)):
    try:
        from backend.database.models import Invoice
        inv = db.query(Invoice).filter(Invoice.id == invoice_id).first()
        if not inv:
            raise HTTPException(status_code=404, detail="Facture introuvable")
        return {"id": inv.id, "invoice_number": inv.invoice_number, "status": inv.status}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=404, detail="Facture introuvable")


# ══════════════════════════════════════════════════════════════════════════════
#  PLANS
# ══════════════════════════════════════════════════════════════════════════════

_PLANS = [
    {"id": "free",       "name": "Free",       "price": 0,    "requests_limit": 1000,  "features": ["1 000 req/mois", "Support email"]},
    {"id": "starter",    "name": "Starter",    "price": 0,    "requests_limit": 10000, "features": ["10 000 req/mois", "1 clé API", "Support email"]},
    {"id": "pro",        "name": "Pro",        "price": 29,   "requests_limit": 100000,"features": ["100 000 req/mois", "5 clés API", "Support prioritaire"]},
    {"id": "enterprise", "name": "Enterprise", "price": 99,   "requests_limit": 0,     "features": ["Illimité", "Clés illimitées", "SLA garanti"]},
]


@router.get("/plans")
async def admin_list_plans(auth: dict = Depends(_require_admin)):
    return {"plans": _PLANS}


class PlanUpdate(BaseModel):
    name: Optional[str] = None
    price: Optional[float] = None
    requests_limit: Optional[int] = None


@router.put("/plans/{plan_id}")
async def admin_update_plan(plan_id: str, body: PlanUpdate, auth: dict = Depends(_require_admin)):
    return {"ok": True, "plan_id": plan_id}


# ══════════════════════════════════════════════════════════════════════════════
#  NOTIFICATIONS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/notifications")
async def admin_notifications(
    limit: int = 20,
    auth: dict = Depends(_require_admin),
):
    return {"notifications": [], "unread": 0}


@router.get("/support/tickets")
async def admin_support_tickets(
    page: int = 1,
    limit: int = 20,
    status: str = "",
    auth: dict = Depends(_require_admin),
):
    return {"items": [], "total": 0, "page": page, "limit": limit}


@router.get("/support/tickets/{ticket_id}")
async def admin_get_support_ticket(
    ticket_id: int,
    auth: dict = Depends(_require_admin),
):
    from fastapi import HTTPException
    raise HTTPException(status_code=404, detail="Ticket introuvable")


@router.post("/support/tickets/{ticket_id}/reply")
async def admin_reply_support_ticket(
    ticket_id: int,
    body: dict,
    auth: dict = Depends(_require_admin),
):
    return {"ok": True, "ticket_id": ticket_id}
