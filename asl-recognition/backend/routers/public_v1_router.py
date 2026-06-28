"""Public developer API — /v1/...

This router exposes the public-facing API endpoints used by client applications
via MIRA_PUBLIC_API_URL=http://127.0.0.1:8000/v1.

These are separate from the internal /api/v1/client/... (dashboard) endpoints.
Authentication is via X-API-Key header (or open if API_KEYS_REQUIRED=false).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel

from backend.deps.auth import require_api_key

router = APIRouter(prefix="/v1", tags=["Public API"])


# ── GET /v1/models ────────────────────────────────────────────────────────────

@router.get("/models", dependencies=[Depends(require_api_key)])
async def public_list_models():
    """List all published sign language models available via the public API."""
    try:
        from backend.database.session import SessionLocal
        from backend.database.models import SignLanguageModel
        db = SessionLocal()
        try:
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
                        "name": m.name or f"Model #{m.id}",
                        "language_code": m.language_code,
                        "status": m.status,
                        "published_at": str(m.published_at) if m.published_at else None,
                    }
                    for m in models
                ],
                "total": len(models),
            }
        finally:
            db.close()
    except Exception:
        return {"models": [], "total": 0}


# ── POST /v1/inference ────────────────────────────────────────────────────────

class InferenceRequest(BaseModel):
    image: str
    lang: Optional[str] = "fr"
    mode: Optional[str] = "holistic"
    model_id: Optional[str] = None


@router.post("/inference", dependencies=[Depends(require_api_key)])
async def public_inference(body: InferenceRequest):
    """Run sign language inference on a single base64 image frame."""
    try:
        from backend.services.recognition_engine import predict_frame, decode_image_b64
        import asyncio
        frame = decode_image_b64(body.image)
        if frame is None:
            raise HTTPException(status_code=400, detail="Image invalide ou vide")
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: predict_frame(frame, lang=body.lang or "fr", mode=body.mode or "holistic"),
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Realtime sessions (/v1/realtime/sessions) ─────────────────────────────────
# These delegate to the same session store as /api/v1/realtime/sessions.

@router.post("/realtime/sessions", status_code=201, dependencies=[Depends(require_api_key)])
async def public_create_session(
    mode: str = Query("holistic"),
    lang: str = Query("fr"),
):
    """Create a realtime recognition session."""
    import uuid
    import datetime
    from backend.routers.inference_router import _RT_SESSIONS
    session_id = str(uuid.uuid4())
    _RT_SESSIONS[session_id] = {
        "mode": mode,
        "lang": lang,
        "created_at": datetime.datetime.utcnow().isoformat(),
        "frames_processed": 0,
        "predictions": [],
    }
    return {"session_id": session_id, "mode": mode, "lang": lang}


@router.post("/realtime/sessions/{session_id}/frames", dependencies=[Depends(require_api_key)])
async def public_push_frame(session_id: str, body: InferenceRequest):
    """Send a frame to an existing realtime session."""
    from backend.routers.inference_router import _RT_SESSIONS
    if session_id not in _RT_SESSIONS:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' introuvable")
    try:
        from backend.services.recognition_engine import predict_frame, decode_image_b64
        import asyncio
        frame = decode_image_b64(body.image)
        if frame is None:
            raise HTTPException(status_code=400, detail="Image invalide")
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: predict_frame(frame, lang=body.lang or "fr", mode=body.mode or "holistic", session_id=session_id),
        )
        sess = _RT_SESSIONS[session_id]
        sess["frames_processed"] = sess.get("frames_processed", 0) + 1
        if result.get("label"):
            sess.setdefault("predictions", []).append(result.get("label"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/realtime/sessions/{session_id}/results", dependencies=[Depends(require_api_key)])
async def public_get_results(session_id: str):
    """Get recent predictions from a realtime session."""
    from backend.routers.inference_router import _RT_SESSIONS
    if session_id not in _RT_SESSIONS:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' introuvable")
    sess = _RT_SESSIONS[session_id]
    return {
        "session_id": session_id,
        "frames_processed": sess.get("frames_processed", 0),
        "predictions": sess.get("predictions", []),
        "status": "active",
    }


@router.delete("/realtime/sessions/{session_id}", status_code=204, dependencies=[Depends(require_api_key)])
async def public_delete_session(session_id: str):
    """Remove a realtime session."""
    from backend.routers.inference_router import _RT_SESSIONS
    _RT_SESSIONS.pop(session_id, None)
