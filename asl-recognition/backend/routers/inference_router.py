"""
inference_router.py — Realtime session management and ASL inference endpoints.

Provides:
  POST   /realtime/sessions                          — create a session
  DELETE /realtime/sessions/{session_id}             — delete a session
  POST   /realtime/sessions/{session_id}/frame       — push a video frame
  POST   /realtime/sessions/{session_id}/finalize    — finalize & translate
  GET    /realtime/sessions/{session_id}/results     — get session state
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.schemas import RecognizeResponse
from backend.services.sign_sequence_builder import get_or_create_builder, remove_builder

router = APIRouter()

# ---------------------------------------------------------------------------
# In-memory session store
# ---------------------------------------------------------------------------
_RT_SESSIONS: Dict[str, Dict[str, Any]] = {}

# ---------------------------------------------------------------------------
# Minimal auth dependency (accept any bearer token; replace with real auth)
# ---------------------------------------------------------------------------
_bearer = HTTPBearer(auto_error=False)


def get_current_client_any(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
):
    """Accept any bearer token (or no auth) — replace with real auth logic."""
    return credentials  # caller can inspect if needed


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------


@router.post("/realtime/sessions", tags=["Realtime"])
async def create_realtime_session(
    client=Depends(get_current_client_any),
):
    """Create a new realtime inference session."""
    session_id = str(uuid.uuid4())
    _RT_SESSIONS[session_id] = {
        "session_id": session_id,
        "frames_received": 0,
        "credits_used": 0,
        "average_confidence": 0.0,
        "status": "active",
        # Sequence tracking
        "confirmed_sequence": [],
        "last_natural_translation": "",
        "last_literal_translation": "",
        "last_translation_provider": "",
        "auto_finalize_triggered": False,
    }
    return {"session_id": session_id, "status": "active"}


@router.delete("/realtime/sessions/{session_id}", tags=["Realtime"])
async def delete_realtime_session(
    session_id: str,
    client=Depends(get_current_client_any),
):
    """Delete a realtime session and clean up its sequence builder."""
    if session_id not in _RT_SESSIONS:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    remove_builder(session_id)
    del _RT_SESSIONS[session_id]
    return {"session_id": session_id, "status": "deleted"}


# ---------------------------------------------------------------------------
# Frame push
# ---------------------------------------------------------------------------


@router.post(
    "/realtime/sessions/{session_id}/frame",
    response_model=None,
    tags=["Realtime"],
)
async def realtime_push_frame(
    session_id: str,
    payload: Dict[str, Any],
    client=Depends(get_current_client_any),
):
    """
    Push a single inference result frame into the session.

    Expected payload keys (all optional):
      label        — recognised sign label
      raw_label    — raw model output label
      confidence   — prediction confidence (0.0–1.0)
      stable       — whether the prediction is considered stable
      top2_margin  — margin between top-2 probabilities
      preview_label — transient label for UI preview
    """
    if session_id not in _RT_SESSIONS:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")

    meta = _RT_SESSIONS[session_id]
    meta["frames_received"] = meta.get("frames_received", 0) + 1

    # Build a result dict from payload
    result: Dict[str, Any] = {
        "label": payload.get("label"),
        "raw_label": payload.get("raw_label"),
        "preview_label": payload.get("preview_label"),
        "confidence": float(payload.get("confidence", 0.0)),
        "stable": bool(payload.get("stable", False)),
        "top2_margin": payload.get("top2_margin"),
    }

    # Update rolling average confidence
    n = meta["frames_received"]
    prev_avg = meta.get("average_confidence", 0.0)
    meta["average_confidence"] = prev_avg + (result["confidence"] - prev_avg) / n

    # Update sequence builder
    builder = get_or_create_builder(session_id)
    label = result.get("label") or result.get("raw_label")
    if label and result.get("stable"):
        push_result = builder.push_prediction(label, result.get("confidence", 0.0))
        meta["confirmed_sequence"] = push_result["sequence"]
        result["confirmed_sequence"] = push_result["sequence"]
        result["pending_sign"] = push_result.get("pending_sign")
    else:
        result["confirmed_sequence"] = meta.get("confirmed_sequence", [])
        result["pending_sign"] = result.get("label") or result.get("preview_label")

    return result


# ---------------------------------------------------------------------------
# Finalize
# ---------------------------------------------------------------------------


@router.post("/realtime/sessions/{session_id}/finalize", tags=["Realtime"])
async def finalize_realtime_session(
    session_id: str,
    lang: str = Query("fr"),
    client=Depends(get_current_client_any),
):
    """
    Finalize a realtime session: take confirmed_sequence, run it through LLM provider,
    return structured translation.
    """
    if session_id not in _RT_SESSIONS:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")

    meta = _RT_SESSIONS[session_id]
    confirmed_sequence = meta.get("confirmed_sequence", [])

    if not confirmed_sequence:
        # Try to get from builder
        builder = get_or_create_builder(session_id)
        confirmed_sequence = builder.get_sequence()

    if not confirmed_sequence:
        return {
            "session_id": session_id,
            "natural_translation": "",
            "literal_translation": "",
            "confirmed_sequence": [],
            "provider": "none",
            "message": "No confirmed signs in sequence. Keep signing.",
        }

    # Import KB resolver and LLM provider
    from backend.services.knowledge_base_resolver import get_knowledge_resolver
    from utils.llm_provider import get_llm_provider

    lang_norm = lang if lang in {"en", "fr", "sw"} else "fr"
    resolver = get_knowledge_resolver()
    kb_context = resolver.resolve_signs(confirmed_sequence)
    kb_context_str = resolver.build_llm_context(confirmed_sequence, lang_norm)

    provider = get_llm_provider()
    translation_result = await provider.translate_sequence(
        signs=confirmed_sequence,
        kb_context=kb_context_str,
        lang=lang_norm,
    )

    # Store in session
    meta["last_natural_translation"] = translation_result.get("natural_translation", "")
    meta["last_literal_translation"] = translation_result.get("literal_translation", "")
    meta["last_translation_provider"] = translation_result.get("provider", "unknown")

    return {
        "session_id": session_id,
        **translation_result,
        "confirmed_sequence": confirmed_sequence,
    }


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@router.get("/realtime/sessions/{session_id}/results", tags=["Realtime"])
async def get_realtime_session_results(
    session_id: str,
    client=Depends(get_current_client_any),
):
    """Get current session state: confirmed sequence + last translation."""
    if session_id not in _RT_SESSIONS:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    meta = _RT_SESSIONS[session_id]
    builder = get_or_create_builder(session_id)
    return {
        "session_id": session_id,
        "confirmed_sequence": builder.get_sequence(),
        "pending_sign": None,
        "last_natural_translation": meta.get("last_natural_translation", ""),
        "last_literal_translation": meta.get("last_literal_translation", ""),
        "last_translation_provider": meta.get("last_translation_provider", ""),
        "frames_received": meta.get("frames_received", 0),
        "credits_used": meta.get("credits_used", 0),
        "average_confidence": meta.get("average_confidence", 0.0),
        "status": meta.get("status", "active"),
        "should_finalize": builder.should_auto_finalize(),
    }
