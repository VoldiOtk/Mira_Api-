"""Inference router — multi-model sign recognition endpoints.

Prefix: /api/v1
Auth:   get_current_client dependency

Endpoints:
  POST /recognize                     — base64 image → sign
  POST /recognize/upload              — multipart image → sign
  POST /recognize/batch               — 1-60 base64 frames → sign
  POST /recognize/video               — video file → timestamped segments
  POST /recognize/feedback            — correction feedback loop
  GET  /signs                         — catalog of supported signs
  POST /admin/models/{model_id}/test  — model playground (admin only)
  POST /realtime/sessions             — create realtime session
  POST /realtime/sessions/{sid}/frames — send a frame to a realtime session
  DELETE /realtime/sessions/{sid}     — remove a realtime session
  GET  /realtime/sessions/{sid}/status — session state info
  GET  /realtime/sessions/{sid}/results — recent predictions from a session
  POST /realtime/sessions/{sid}/finalize — finalize sequence with LLM translation
  GET  /quota/status                  — current API key quota info
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
import torch
from pydantic import BaseModel as _BaseModel
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from sqlalchemy.orm import Session
from backend.limiter import limiter

from backend.auth.dependencies import get_admin, get_current_client, get_current_client_any
from backend.config import settings
from backend.database import models as db_models
from backend.database.session import get_db
from backend.schemas import (
    BatchRecognizeRequest,
    BatchRecognizeResponse,
    FeedbackRequest,
    ModelTestResponse,
    QuotaStatusResponse,
    RealtimeSessionResponse,
    RealtimeSessionStatus,
    RecognizeRequest,
    RecognizeResponse,
    SignInfo,
    SignsResponse,
    VideoRecognizeResponse,
    VideoSegment,
)
from backend.services.recognition_engine import (
    SEQUENCE_LENGTH,
    decode_image_b64,
    find_translation,
    predict_frame,
)
from backend.services.sign_sequence_builder import get_or_create_builder, remove_builder
from backend.services.knowledge_base_resolver import get_knowledge_resolver
from utils.llm_provider import get_llm_provider

router = APIRouter(prefix="/api/v1", tags=["Inference"])

# ---------------------------------------------------------------------------
# Model cache: maps model_id → (model_nn, actions, input_size, feature_version, model_type, device)
# ---------------------------------------------------------------------------
_MODEL_CACHE: Dict[int, Tuple] = {}
_MODEL_CACHE_DIR = os.path.join(os.sep + "tmp", "models")

_MODEL_DOWNLOAD_LOCKS: Dict[int, threading.Lock] = {}
_LOCKS_MUTEX = threading.Lock()

_SUPPORTED_LANGS = {"en", "fr", "sw"}


def _get_model_lock(model_id: int) -> threading.Lock:
    with _LOCKS_MUTEX:
        if model_id not in _MODEL_DOWNLOAD_LOCKS:
            _MODEL_DOWNLOAD_LOCKS[model_id] = threading.Lock()
        return _MODEL_DOWNLOAD_LOCKS[model_id]


def _local_model_dir(model_id: int) -> str:
    return os.path.join(_MODEL_CACHE_DIR, str(model_id))


def _load_s3_model(model_id: int, db: Session) -> Tuple:
    """Download model.pth + metadata.json from S3 (once), load into memory, cache.

    Returns (model_nn, actions, input_size, feature_version, model_type, device).
    """
    if model_id in _MODEL_CACHE:
        return _MODEL_CACHE[model_id]

    with _get_model_lock(model_id):
        if model_id in _MODEL_CACHE:
            return _MODEL_CACHE[model_id]

        registry = db.query(db_models.SignLanguageModel).get(model_id)
        if not registry:
            raise HTTPException(status_code=404, detail=f"Model {model_id} not found")
        if registry.status != "ready":
            raise HTTPException(
                status_code=400,
                detail=f"Model {model_id} is not ready (status='{registry.status}')",
            )

        local_dir = _local_model_dir(model_id)
        model_local = os.path.join(local_dir, "model.pth")
        meta_local = os.path.join(local_dir, "metadata.json")

        if not os.path.exists(model_local):
            os.makedirs(local_dir, exist_ok=True)
            from backend.storage.s3_client import download_file

            model_s3_key = registry.model_path
            # Support both metadata.json (new) and model_meta.json (legacy)
            meta_s3_key = model_s3_key.replace("model.pth", "metadata.json")
            meta_s3_legacy = model_s3_key.replace("model.pth", "model_meta.json")

            try:
                download_file(settings.s3_bucket_models, model_s3_key, model_local)
                try:
                    download_file(settings.s3_bucket_models, meta_s3_key, meta_local)
                except Exception:
                    download_file(settings.s3_bucket_models, meta_s3_legacy, meta_local)
            except Exception as exc:
                raise HTTPException(
                    status_code=502, detail=f"Could not download model: {exc}"
                ) from exc

        with open(meta_local, encoding="utf-8") as fh:
            meta = json.load(fh)

        actions: List[str] = meta.get("actions", [])
        input_size: int = meta.get("input_size", 1662)
        feature_version: str = meta.get("feature_version", "v2" if input_size == 258 else "v1")
        model_type: str = meta.get("model_type", "lstm")
        num_classes: int = len(actions)

        import sys
        model_src_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "..", "model"
        )
        if model_src_dir not in sys.path:
            sys.path.insert(0, os.path.abspath(model_src_dir))

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        if model_type == "transformer":
            from model.model import ASLTransformerModel  # type: ignore[import]
            model_nn = ASLTransformerModel(
                input_size=input_size,
                num_classes=num_classes,
            ).to(device)
        else:
            from model.model import ASLLstmModel  # type: ignore[import]
            model_nn = ASLLstmModel(
                input_size=input_size,
                num_classes=num_classes,
            ).to(device)

        try:
            state_dict = torch.load(model_local, map_location=device, weights_only=True)
        except TypeError:
            state_dict = torch.load(model_local, map_location=device)
        model_nn.load_state_dict(state_dict)
        model_nn.eval()

        cached = (model_nn, actions, input_size, feature_version, model_type, device)
        _MODEL_CACHE[model_id] = cached
        return cached


def _predict_with_s3_model(
    frame_bgr: np.ndarray,
    model_id: int,
    db: Session,
    *,
    lang: str = "fr",
    mode: str = "holistic",
    session_id: Optional[str] = None,
    annotate: bool = True,
    top_k: int = 1,
) -> dict:
    """Run inference using a dynamically loaded S3 model."""
    from backend.services.recognition_engine import (
        MIN_STABLE_COUNT,
        NON_SIGN_LABELS,
        PREDICTION_THRESHOLD,
        TOP2_MARGIN_THRESHOLD,
        encode_image_b64,
        get_or_create_session,
    )

    model_nn, actions, input_size, feature_version, model_type, device = _load_s3_model(
        model_id, db
    )

    lang_norm = lang if lang in _SUPPORTED_LANGS else "fr"
    sid, sess = get_or_create_session(session_id, mode, feature_version)

    image_bgr, keypoints, hands_present = sess.extractor.process_frame(
        frame_bgr, annotate=annotate, feature_version=feature_version
    )
    sess.sequence.append(keypoints)

    prediction_label = ""
    confidence = 0.0
    top2_margin = 0.0
    probs_tensor: Optional[Any] = None

    if sess.mode == "holistic":
        seq = list(sess.sequence)
        if len(seq) == SEQUENCE_LENGTH and hands_present:
            with torch.no_grad():
                tensor_in = torch.tensor([seq], dtype=torch.float32).to(device)
                res = model_nn(tensor_in)[0]
                probs = torch.softmax(res, dim=0)
                probs_tensor = probs
                idx = int(torch.argmax(probs).item())
                confidence = float(probs[idx].item())
                topk = torch.topk(probs, k=min(2, probs.shape[0])).values
                top2_margin = (
                    float((topk[0] - topk[1]).item())
                    if topk.shape[0] >= 2
                    else float(topk[0].item())
                )
            if (
                idx < len(actions)
                and confidence >= PREDICTION_THRESHOLD
                and top2_margin >= TOP2_MARGIN_THRESHOLD
            ):
                prediction_label = actions[idx]
    else:
        if hands_present:
            with torch.no_grad():
                tensor_in = torch.tensor([keypoints], dtype=torch.float32).to(device)
                res = model_nn(tensor_in)[0]
                probs = torch.softmax(res, dim=0)
                probs_tensor = probs
                idx = int(torch.argmax(probs).item())
                confidence = float(probs[idx].item())
                topk = torch.topk(probs, k=min(2, probs.shape[0])).values
                top2_margin = (
                    float((topk[0] - topk[1]).item())
                    if topk.shape[0] >= 2
                    else float(topk[0].item())
                )
            if (
                idx < len(actions)
                and confidence >= PREDICTION_THRESHOLD
                and top2_margin >= TOP2_MARGIN_THRESHOLD
            ):
                prediction_label = actions[idx]

    if prediction_label and prediction_label.lower() in NON_SIGN_LABELS:
        prediction_label = ""
        sess.history.clear()

    stable_label = ""
    is_stable = False
    if prediction_label:
        sess.history.append(prediction_label)
        stable_label = max(set(sess.history), key=sess.history.count)
        is_stable = sess.history.count(stable_label) >= MIN_STABLE_COUNT

    label_out = stable_label if is_stable else (prediction_label or None)
    translation = find_translation(label_out, lang_norm)["text"] if label_out else None
    preview_label = prediction_label or (stable_label if is_stable else "")
    preview_translation = (
        find_translation(preview_label, lang_norm)["text"] if preview_label else None
    )

    message = None
    if sess.mode == "holistic" and len(sess.sequence) < SEQUENCE_LENGTH:
        remaining = SEQUENCE_LENGTH - len(sess.sequence)
        message = (
            f"Holistic mode: send {remaining} more image(s) with the same session_id."
            if lang_norm == "en"
            else f"Mode holistic : envoyez encore {remaining} image(s) avec le même session_id."
        )

    # Task 1: Top-K predictions
    top_predictions: Optional[List[dict]] = None
    if top_k > 1 and probs_tensor is not None and actions:
        k_actual = min(top_k, probs_tensor.shape[0], len(actions))
        topk_result = torch.topk(probs_tensor, k=k_actual)
        top_predictions = []
        for prob_val, class_idx in zip(
            topk_result.values.tolist(), topk_result.indices.tolist()
        ):
            if prob_val >= 0.05 and class_idx < len(actions):
                top_predictions.append({
                    "label": actions[class_idx],
                    "confidence": round(float(prob_val), 4),
                })
        if not top_predictions:
            top_predictions = None

    # Task 2: Low confidence suggestion
    suggestion: Optional[str] = None
    if not hands_present:
        suggestion = "Aucune main détectée. Assurez-vous que vos mains sont visibles."
    elif confidence < 0.40:
        suggestion = "Signe non reconnu. Essayez avec un meilleur éclairage ou un autre angle."
    elif confidence < PREDICTION_THRESHOLD:
        suggestion = "Confiance faible. Continuez à signer pour accumuler plus de frames."
    elif top2_margin < TOP2_MARGIN_THRESHOLD and confidence > 0.0:
        suggestion = "Le signe est ambigu entre plusieurs prédictions. Signez plus lentement."

    return {
        "session_id": sid,
        "label": label_out,
        "translation": translation,
        "preview_label": preview_label or None,
        "preview_translation": preview_translation,
        "confidence": round(confidence, 4),
        "margin": round(top2_margin, 4),
        "stable": is_stable,
        "hands_detected": hands_present,
        "sequence_len": len(sess.sequence),
        "sequence_required": SEQUENCE_LENGTH if sess.mode == "holistic" else 1,
        "lang": lang_norm,
        "mode": sess.mode,
        "image": encode_image_b64(image_bgr) if annotate else None,
        "message": message,
        "top_predictions": top_predictions,
        "suggestion": suggestion,
    }


# ---------------------------------------------------------------------------
# Task 3: Smart model selector
# ---------------------------------------------------------------------------

def _select_best_model(lang: str, db: Session, client) -> Optional[int]:
    """Auto-select the best published model for a language.

    Returns model_id or None (use default local model).
    """
    models = (
        db.query(db_models.SignLanguageModel)
        .filter(
            db_models.SignLanguageModel.is_published.is_(True),
            db_models.SignLanguageModel.language_code == lang.lower(),
        )
        .order_by(db_models.SignLanguageModel.published_at.desc())
        .all()
    )
    if not models:
        return None  # fall back to local default model

    # For now: return the most recently published model
    return models[0].id


def _log_usage(
    db: Session,
    client,
    endpoint: str,
    model_id: Optional[int],
    status_code: int,
) -> None:
    try:
        log = db_models.UsageLog(
            client_id=getattr(client, "client_id", None),
            api_key_id=getattr(client, "id", None),
            endpoint=endpoint,
            method="POST",
            model_id=model_id,
            status_code=status_code,
        )
        db.add(log)
        if hasattr(client, "quota_used"):
            client.quota_used = client.quota_used + 1
            db.add(client)
        db.commit()
    except Exception:
        db.rollback()


# ─── /recognize ────────────────────────────────────────────────────────────

@router.post("/recognize", response_model=RecognizeResponse)
@limiter.limit("60/minute")
async def recognize_json(
    request: Request,
    body: RecognizeRequest,
    model_id: Optional[int] = Query(None, description="Use a specific model from the registry"),
    annotate: bool = Query(True, description="Include annotated image in response (set false to reduce bandwidth)"),
    top_k: int = Query(1, ge=1, le=10, description="Return top-K predictions (max 10)"),
    target_language: str = Query("fr", description="Target language for translation: en | fr | sw"),
    client=Depends(get_current_client_any),
    db: Session = Depends(get_db),
):
    """Sign → Text: send a base64 image, receive the detected ASL sign and translation.

    - `mode=holistic`: reuse the same `session_id` across ~30 consecutive images.
    - `mode=hands`: a single image is enough (letter / alphabet).
    - `annotate=false`: skip image encoding (~50-70 % less bandwidth).
    - `top_k`: include top-K softmax predictions above 0.05 confidence.
    - `target_language`: translation language (en | fr | sw, default fr).
    """
    frame = decode_image_b64(body.image)
    if frame is None:
        raise HTTPException(status_code=400, detail="Invalid image or unreadable base64.")

    auto_selected_model: Optional[int] = None

    if model_id is not None:
        result = _predict_with_s3_model(
            frame, model_id, db,
            lang=body.lang, mode=body.mode, session_id=body.session_id,
            annotate=annotate, top_k=top_k,
        )
    else:
        # Task 3: auto-select a published model for non-default languages
        if body.lang not in ("fr", ""):
            auto_model_id = _select_best_model(body.lang, db, client)
            if auto_model_id is not None:
                model_id = auto_model_id
                auto_selected_model = auto_model_id
                result = _predict_with_s3_model(
                    frame, model_id, db,
                    lang=body.lang, mode=body.mode, session_id=body.session_id,
                    annotate=annotate, top_k=top_k,
                )
            else:
                result = predict_frame(
                    frame, lang=body.lang, mode=body.mode,
                    session_id=body.session_id, annotate=annotate, top_k=top_k,
                )
        else:
            result = predict_frame(
                frame, lang=body.lang, mode=body.mode,
                session_id=body.session_id, annotate=annotate, top_k=top_k,
            )

    result["auto_selected_model"] = auto_selected_model
    translation_info = find_translation(result.get("label") or "", target_language)
    result["raw_label"] = result.get("label")
    result["translated_text"] = translation_info["translated_text"]
    result["source_language"] = translation_info["source_language"]
    result["target_language"] = translation_info["target_language"]
    result["translation_fallback"] = translation_info["fallback"]
    _log_usage(db, client, "/recognize", model_id, 200)
    return RecognizeResponse(**result)


@router.post("/recognize/upload", response_model=RecognizeResponse)
async def recognize_upload(
    file: UploadFile = File(..., description="JPEG or PNG image file"),
    lang: str = Form("fr"),
    mode: str = Form("holistic"),
    session_id: Optional[str] = Form(None),
    model_id: Optional[int] = Query(None, description="Use a specific model from the registry"),
    annotate: bool = Query(True, description="Include annotated image in response"),
    top_k: int = Query(1, ge=1, le=10, description="Return top-K predictions (max 10)"),
    target_language: str = Query("fr", description="Target language for translation: en | fr | sw"),
    client=Depends(get_current_client_any),
    db: Session = Depends(get_db),
):
    """Same as `/recognize` but with multipart file upload."""
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file.")

    arr = np.frombuffer(raw, np.uint8)
    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if frame is None:
        raise HTTPException(status_code=400, detail="Unsupported image format.")

    auto_selected_model: Optional[int] = None

    if model_id is not None:
        result = _predict_with_s3_model(
            frame, model_id, db,
            lang=lang, mode=mode, session_id=session_id,
            annotate=annotate, top_k=top_k,
        )
    else:
        if lang not in ("fr", ""):
            auto_model_id = _select_best_model(lang, db, client)
            if auto_model_id is not None:
                model_id = auto_model_id
                auto_selected_model = auto_model_id
                result = _predict_with_s3_model(
                    frame, model_id, db,
                    lang=lang, mode=mode, session_id=session_id,
                    annotate=annotate, top_k=top_k,
                )
            else:
                result = predict_frame(
                    frame, lang=lang, mode=mode,
                    session_id=session_id, annotate=annotate, top_k=top_k,
                )
        else:
            result = predict_frame(
                frame, lang=lang, mode=mode,
                session_id=session_id, annotate=annotate, top_k=top_k,
            )

    result["auto_selected_model"] = auto_selected_model
    translation_info = find_translation(result.get("label") or "", target_language)
    result["raw_label"] = result.get("label")
    result["translated_text"] = translation_info["translated_text"]
    result["source_language"] = translation_info["source_language"]
    result["target_language"] = translation_info["target_language"]
    result["translation_fallback"] = translation_info["fallback"]
    _log_usage(db, client, "/recognize/upload", model_id, 200)
    return RecognizeResponse(**result)


# ─── /recognize/batch ──────────────────────────────────────────────────────

@router.post("/recognize/batch", response_model=BatchRecognizeResponse)
async def recognize_batch(
    body: BatchRecognizeRequest,
    model_id: Optional[int] = Query(None),
    annotate: bool = Query(False, description="Include annotated image for last frame only"),
    client=Depends(get_current_client_any),
    db: Session = Depends(get_db),
):
    """Send 1-60 frames in a single HTTP call.

    Frames are processed in order through the same session so the sequence
    accumulates normally. Only the result from the last frame is returned.
    Use this instead of 30 separate /recognize calls to reduce HTTP overhead.
    """
    lang_norm = body.lang if body.lang in _SUPPORTED_LANGS else "fr"
    last_result: Optional[dict] = None

    for i, img_b64 in enumerate(body.frames):
        frame = decode_image_b64(img_b64)
        if frame is None:
            raise HTTPException(
                status_code=400, detail=f"Frame {i}: invalid image or unreadable base64."
            )
        is_last = i == len(body.frames) - 1
        if model_id is not None:
            last_result = _predict_with_s3_model(
                frame, model_id, db,
                lang=lang_norm, mode=body.mode, session_id=body.session_id,
                annotate=(annotate and is_last),
            )
        else:
            last_result = predict_frame(
                frame, lang=lang_norm, mode=body.mode,
                session_id=body.session_id, annotate=(annotate and is_last),
            )
        # Update session_id from first frame so subsequent frames reuse it
        body.session_id = last_result["session_id"]

    _log_usage(db, client, "/recognize/batch", model_id, 200)
    return BatchRecognizeResponse(
        **{k: v for k, v in last_result.items() if k not in ("image", "top_predictions", "suggestion", "auto_selected_model")},
        frames_processed=len(body.frames),
    )


# ─── /recognize/video ──────────────────────────────────────────────────────

_VIDEO_SAMPLE_EVERY_N = int(os.getenv("VIDEO_SAMPLE_EVERY_N_FRAMES", "3"))
_VIDEO_MAX_MB = float(os.getenv("VIDEO_MAX_MB", "50"))


@router.post("/recognize/video", response_model=VideoRecognizeResponse)
async def recognize_video(
    file: UploadFile = File(..., description="Video file (mp4, avi, webm, mov)"),
    lang: str = Form("fr"),
    model_id: Optional[int] = Query(None),
    client=Depends(get_current_client_any),
    db: Session = Depends(get_db),
):
    """Upload a video file and receive timestamped sign segments.

    The video is sampled every N frames (default 3, configurable via
    VIDEO_SAMPLE_EVERY_N_FRAMES env var). Each stable sign detection produces
    one segment entry with its timestamp.
    """
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty video file.")
    if len(raw) > _VIDEO_MAX_MB * 1024 * 1024:
        raise HTTPException(
            status_code=413, detail=f"Video too large (max {_VIDEO_MAX_MB:.0f} MB)."
        )

    # Write to a temp file — OpenCV VideoCapture needs a real path
    suffix = os.path.splitext(file.filename or "video.mp4")[1] or ".mp4"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(raw)
        tmp_path = tmp.name

    lang_norm = lang if lang in _SUPPORTED_LANGS else "fr"
    segments: List[VideoSegment] = []
    frames_processed = 0
    duration_s = 0.0
    import uuid as _uuid
    session_id = str(_uuid.uuid4())
    last_stable_label = ""

    try:
        cap = cv2.VideoCapture(tmp_path)
        if not cap.isOpened():
            raise HTTPException(status_code=400, detail="Could not open video file.")

        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration_s = total_frames / fps

        frame_idx = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if frame_idx % _VIDEO_SAMPLE_EVERY_N == 0:
                timestamp_s = round(frame_idx / fps, 3)
                if model_id is not None:
                    result = _predict_with_s3_model(
                        frame, model_id, db,
                        lang=lang_norm, mode="holistic",
                        session_id=session_id, annotate=False,
                    )
                else:
                    result = predict_frame(
                        frame, lang=lang_norm, mode="holistic",
                        session_id=session_id, annotate=False,
                    )
                session_id = result["session_id"]
                label = result.get("label")
                if label and label != last_stable_label and result.get("stable"):
                    segments.append(VideoSegment(
                        timestamp_s=timestamp_s,
                        label=label,
                        translation=result.get("translation"),
                        confidence=result.get("confidence", 0.0),
                    ))
                    last_stable_label = label
                frames_processed += 1
            frame_idx += 1
        cap.release()
    finally:
        os.unlink(tmp_path)

    _log_usage(db, client, "/recognize/video", model_id, 200)
    return VideoRecognizeResponse(
        duration_s=round(duration_s, 3),
        frames_processed=frames_processed,
        segments=segments,
        language=lang_norm,
    )


# ─── /recognize/feedback ───────────────────────────────────────────────────

@router.post("/recognize/feedback", status_code=201)
async def recognize_feedback(
    body: FeedbackRequest,
    client=Depends(get_current_client_any),
    db: Session = Depends(get_db),
):
    """Submit a correction when the model predicted the wrong sign.

    These records are stored in `recognition_feedbacks` and used in future
    training cycles to improve accuracy.
    """
    fb = db_models.RecognitionFeedback(
        client_id=getattr(client, "client_id", None),
        api_key_id=getattr(client, "id", None),
        model_id=body.model_id,
        session_id=body.session_id,
        predicted_label=body.predicted_label,
        correct_label=body.correct_label,
        confidence=body.confidence,
    )
    db.add(fb)
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="Could not save feedback.") from exc

    return {"status": "saved", "id": fb.id}


# ─── /signs ────────────────────────────────────────────────────────────────

@router.get("/signs", response_model=SignsResponse)
async def list_signs(
    lang: str = Query("fr", description="fr | en"),
    model_id: Optional[int] = Query(None, description="Signs for a specific registry model"),
    client=Depends(get_current_client_any),
    db: Session = Depends(get_db),
):
    """Return the catalog of signs supported by the currently loaded model.

    Useful for mobile/web clients to build autocomplete or sign pickers.
    """
    from backend.services.recognition_engine import (
        ACTIONS_HOLISTIC,
        _default_feature_version,
        _default_input_size,
    )
    import json as _json

    lang_norm = lang if lang in _SUPPORTED_LANGS else "fr"

    if model_id is not None:
        model_nn, actions, input_size, feature_version, model_type, _ = _load_s3_model(
            model_id, db
        )
        registry = db.query(db_models.SignLanguageModel).get(model_id)
        model_name = registry.name if registry else None
    else:
        actions = ACTIONS_HOLISTIC
        input_size = _default_input_size
        feature_version = _default_feature_version
        model_type = "lstm"
        model_name = None

    base_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "knowledge"
    )
    labels_path = os.path.join(base_dir, "labels.json")
    with open(labels_path, "r", encoding="utf-8") as fh:
        labels_db = _json.load(fh)

    signs = []
    for label in actions:
        key = label.lower()
        entry = labels_db.get(key, {})
        signs.append(SignInfo(
            label=label,
            fr=entry.get("fr", label),
            en=entry.get("en", label),
        ))

    return SignsResponse(
        model_name=model_name,
        language_code=lang_norm,
        input_size=input_size,
        feature_version=feature_version,
        model_type=model_type,
        count=len(signs),
        signs=signs,
    )


# ─── Task 4: Model Playground ──────────────────────────────────────────────

@router.post(
    "/admin/models/{model_id}/test",
    response_model=ModelTestResponse,
    tags=["Admin"],
)
async def test_model(
    model_id: int,
    file: UploadFile = File(..., description="JPEG or PNG image to run inference on"),
    lang: str = Form("fr"),
    mode: str = Form("holistic"),
    _admin=Depends(get_admin),
    db: Session = Depends(get_db),
):
    """Admin-only: run a single-image inference test against a specific registered model.

    Returns detailed inference stats including top predictions, latency, and model metadata.
    """
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file.")

    arr = np.frombuffer(raw, np.uint8)
    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if frame is None:
        raise HTTPException(status_code=400, detail="Unsupported image format.")

    model_nn, actions, input_size, feature_version, model_type, device = _load_s3_model(
        model_id, db
    )

    from backend.services.recognition_engine import (
        PREDICTION_THRESHOLD,
        TOP2_MARGIN_THRESHOLD,
        get_or_create_session,
    )

    lang_norm = lang if lang in _SUPPORTED_LANGS else "fr"
    _, sess = get_or_create_session(None, mode, feature_version)

    image_bgr, keypoints, hands_present = sess.extractor.process_frame(
        frame, annotate=False, feature_version=feature_version
    )
    sess.sequence.append(keypoints)

    t0 = time.perf_counter()
    prediction_label: Optional[str] = None
    confidence = 0.0
    top_predictions: List[dict] = []

    if sess.mode == "holistic":
        seq = list(sess.sequence)
        if hands_present and seq:
            with torch.no_grad():
                # Pad sequence to SEQUENCE_LENGTH if needed for single-frame test
                while len(seq) < SEQUENCE_LENGTH:
                    seq = [seq[0]] + seq
                seq = seq[-SEQUENCE_LENGTH:]
                tensor_in = torch.tensor([seq], dtype=torch.float32).to(device)
                res = model_nn(tensor_in)[0]
                probs = torch.softmax(res, dim=0)
                idx = int(torch.argmax(probs).item())
                confidence = float(probs[idx].item())
                k_actual = min(10, probs.shape[0], len(actions))
                topk_result = torch.topk(probs, k=k_actual)
                for prob_val, class_idx in zip(
                    topk_result.values.tolist(), topk_result.indices.tolist()
                ):
                    if prob_val >= 0.05 and class_idx < len(actions):
                        top_predictions.append({
                            "label": actions[class_idx],
                            "confidence": round(float(prob_val), 4),
                        })
                if idx < len(actions) and confidence >= PREDICTION_THRESHOLD:
                    prediction_label = actions[idx]
    else:
        if hands_present:
            with torch.no_grad():
                tensor_in = torch.tensor([keypoints], dtype=torch.float32).to(device)
                res = model_nn(tensor_in)[0]
                probs = torch.softmax(res, dim=0)
                idx = int(torch.argmax(probs).item())
                confidence = float(probs[idx].item())
                k_actual = min(10, probs.shape[0], len(actions))
                topk_result = torch.topk(probs, k=k_actual)
                for prob_val, class_idx in zip(
                    topk_result.values.tolist(), topk_result.indices.tolist()
                ):
                    if prob_val >= 0.05 and class_idx < len(actions):
                        top_predictions.append({
                            "label": actions[class_idx],
                            "confidence": round(float(prob_val), 4),
                        })
                if idx < len(actions) and confidence >= PREDICTION_THRESHOLD:
                    prediction_label = actions[idx]

    inference_time_ms = (time.perf_counter() - t0) * 1000.0

    registry = db.query(db_models.SignLanguageModel).get(model_id)
    model_name = registry.name if registry else None

    return ModelTestResponse(
        model_id=model_id,
        model_name=model_name,
        label=prediction_label,
        confidence=round(confidence, 4),
        top_predictions=top_predictions,
        inference_time_ms=round(inference_time_ms, 3),
        hands_detected=hands_present,
        input_size=input_size,
        feature_version=feature_version,
        model_type=model_type,
    )


# ─── Task 5: Realtime Session API ─────────────────────────────────────────

# Realtime sessions are stored separately with extra metadata beyond _Session
_RT_SESSIONS: Dict[str, dict] = {}
_RT_SESSION_TTL = 600.0  # 10 minutes


def _purge_rt_sessions() -> None:
    now = time.time()
    expired = [
        sid for sid, meta in _RT_SESSIONS.items()
        if now - meta["last_used"] > _RT_SESSION_TTL
    ]
    for sid in expired:
        del _RT_SESSIONS[sid]


@router.post("/realtime/sessions", response_model=RealtimeSessionResponse, status_code=201, tags=["Realtime"])
async def create_realtime_session(
    mode: str = Query("holistic", description="holistic | hands"),
    lang: str = Query("fr", description="fr | en"),
    model_id: Optional[int] = Query(None, description="Use a specific published model for this session"),
    target_language: str = Query("fr", description="Target language for translation: en | fr | sw"),
    client=Depends(get_current_client_any),
    db: Session = Depends(get_db),
):
    """Create a named realtime session. Returns session_id for use in subsequent frame calls."""
    import datetime
    import uuid

    _purge_rt_sessions()

    from backend.services.recognition_engine import (
        _default_feature_version,
        get_or_create_session,
    )

    feature_version = _default_feature_version  # default
    if model_id is not None:
        registry = db.query(db_models.SignLanguageModel).get(model_id)
        if not registry:
            raise HTTPException(status_code=404, detail=f"Model {model_id} not found")
        if not registry.is_published:
            raise HTTPException(status_code=400, detail=f"Model {model_id} is not published")
        # Try to get feature version from model metadata
        local_dir = _local_model_dir(model_id)
        meta_local = os.path.join(local_dir, "metadata.json")
        if os.path.exists(meta_local):
            with open(meta_local) as fh:
                meta = json.load(fh)
            feature_version = meta.get("feature_version", "v2")

    sid = str(uuid.uuid4())
    get_or_create_session(sid, mode, feature_version)

    now = time.time()
    expires_at = datetime.datetime.utcfromtimestamp(now + _RT_SESSION_TTL).isoformat() + "Z"
    _RT_SESSIONS[sid] = {
        "mode": mode,
        "lang": lang,
        "model_id": model_id,
        "target_language": target_language,
        "client_id": getattr(client, "client_id", None),
        "api_key_id": getattr(client, "id", None),
        "created_at": now,
        "last_used": now,
        "frames_received": 0,
        "predictions_count": 0,
        "credits_used": 0,
        "last_predictions": [],
        "average_confidence": 0.0,
        "status": "active",
        # Sequence tracking (SignSequenceBuilder)
        "confirmed_sequence": [],
        "last_natural_translation": None,
        "last_literal_translation": None,
        "last_translation_provider": None,
    }

    return RealtimeSessionResponse(session_id=sid, expires_at=expires_at, mode=mode, lang=lang, model_id=model_id)


@router.post("/realtime/sessions/{session_id}/frames", response_model=RecognizeResponse, tags=["Realtime"])
async def realtime_push_frame(
    session_id: str,
    body: RecognizeRequest,
    annotate: bool = Query(False, description="Include annotated image in response"),
    top_k: int = Query(1, ge=1, le=10, description="Return top-K predictions"),
    target_language: str = Query("fr", description="Target language for translation: en | fr | sw"),
    client=Depends(get_current_client_any),
    db: Session = Depends(get_db),
):
    """Send a base64 frame to an existing realtime session and get a prediction."""
    if session_id not in _RT_SESSIONS:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")

    # Quota check
    quota_used = getattr(client, "quota_used", 0)
    quota_total = getattr(client, "quota_total", 1)
    if quota_used >= quota_total:
        raise HTTPException(status_code=429, detail="Quota épuisé. Rechargez votre abonnement.")

    frame = decode_image_b64(body.image)
    if frame is None:
        raise HTTPException(status_code=400, detail="Invalid image.")

    meta = _RT_SESSIONS[session_id]
    meta["last_used"] = time.time()
    meta["frames_received"] = meta.get("frames_received", 0) + 1

    lang = meta.get("lang", "fr")
    mode = meta.get("mode", "holistic")
    rt_model_id = meta.get("model_id")
    # Use session-stored target_language; Query param overrides if explicitly set to non-default
    rt_target_language = meta.get("target_language", "fr")
    # If caller passes a non-default target_language via Query, it takes priority
    effective_target_language = target_language if target_language != "fr" else rt_target_language

    if rt_model_id is not None:
        result = _predict_with_s3_model(frame, rt_model_id, db, lang=lang, mode=mode, session_id=session_id, annotate=annotate, top_k=top_k)
    else:
        result = predict_frame(frame, lang=lang, mode=mode, session_id=session_id, annotate=annotate, top_k=top_k)

    result["auto_selected_model"] = rt_model_id
    translation_info = find_translation(result.get("label") or "", effective_target_language)
    result["raw_label"] = result.get("label")
    result["translated_text"] = translation_info["translated_text"]
    result["source_language"] = translation_info["source_language"]
    result["target_language"] = translation_info["target_language"]
    result["translation_fallback"] = translation_info["fallback"]

    # SignSequenceBuilder integration
    builder = get_or_create_builder(session_id)
    builder_result = builder.push_prediction(
        result.get("label") or "",
        result.get("confidence", 0.0),
    )
    if builder_result.get("confirmed"):
        meta["confirmed_sequence"] = builder.get_sequence()
    result["confirmed_sequence"] = meta.get("confirmed_sequence", [])
    result["pending_sign"] = builder_result.get("pending_sign")

    # Track prediction if valid
    if result.get("label"):
        meta["predictions_count"] = meta.get("predictions_count", 0) + 1
        meta["credits_used"] = meta.get("credits_used", 0) + 1
        pred_entry = {
            "label": result["label"],
            "translation": result.get("translation"),
            "confidence": result.get("confidence", 0.0),
            "ts": time.time(),
        }
        last_preds = meta.get("last_predictions", [])
        last_preds.append(pred_entry)
        if len(last_preds) > 10:
            last_preds.pop(0)
        meta["last_predictions"] = last_preds

        # Update average confidence
        all_conf = [p["confidence"] for p in last_preds]
        meta["average_confidence"] = sum(all_conf) / len(all_conf) if all_conf else 0.0

        # Decrement quota
        try:
            client.quota_used = quota_used + 1
            db.commit()
        except Exception:
            db.rollback()

        _log_usage(db, client, "/realtime/frames", rt_model_id, 200)

    return RecognizeResponse(**result)


@router.delete(
    "/realtime/sessions/{session_id}",
    status_code=204,
    tags=["Realtime"],
)
async def delete_realtime_session(
    session_id: str,
    client=Depends(get_current_client_any),
):
    """Remove a realtime session. Returns 204 No Content."""
    from backend.services.recognition_engine import _sessions as _engine_sessions

    _RT_SESSIONS.pop(session_id, None)
    _engine_sessions.pop(session_id, None)
    remove_builder(session_id)
    return None


@router.get(
    "/realtime/sessions/{session_id}/status",
    response_model=RealtimeSessionStatus,
    tags=["Realtime"],
)
async def get_realtime_session_status(
    session_id: str,
    client=Depends(get_current_client_any),
):
    """Return current state of a realtime session."""
    from backend.services.recognition_engine import (
        SEQUENCE_LENGTH as _SEQ_LEN,
        _default_feature_version,
        _sessions as _engine_sessions,
    )

    if session_id not in _RT_SESSIONS:
        raise HTTPException(status_code=404, detail=f"Realtime session '{session_id}' not found.")

    meta = _RT_SESSIONS[session_id]
    engine_sess = _engine_sessions.get(session_id)

    seq_len = len(engine_sess.sequence) if engine_sess else 0
    seq_required = _SEQ_LEN if (engine_sess and engine_sess.mode == "holistic") else 1
    fv = engine_sess.feature_version if engine_sess else _default_feature_version
    mode = meta.get("mode", "holistic")

    return RealtimeSessionStatus(
        session_id=session_id,
        sequence_len=seq_len,
        sequence_required=seq_required,
        feature_version=fv,
        mode=mode,
        last_used=meta["last_used"],
    )


@router.get("/realtime/sessions/{session_id}/results", tags=["Realtime"])
async def get_realtime_session_results(
    session_id: str,
    client=Depends(get_current_client_any),
):
    """Return recent predictions from a realtime session."""
    if session_id not in _RT_SESSIONS:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")

    meta = _RT_SESSIONS[session_id]
    builder = get_or_create_builder(session_id)
    return {
        "session_id": session_id,
        "status": meta.get("status", "active"),
        "frames_received": meta.get("frames_received", 0),
        "predictions_count": meta.get("predictions_count", 0),
        "credits_used": meta.get("credits_used", 0),
        "average_confidence": round(meta.get("average_confidence", 0.0), 4),
        "last_predictions": meta.get("last_predictions", []),
        "model_id": meta.get("model_id"),
        "lang": meta.get("lang", "fr"),
        "mode": meta.get("mode", "holistic"),
        "confirmed_sequence": builder.get_sequence(),
        "sequence_length": len(builder.get_sequence()),
        "should_finalize": builder.should_auto_finalize(),
        "last_natural_translation": meta.get("last_natural_translation"),
        "last_literal_translation": meta.get("last_literal_translation"),
        "last_translation_provider": meta.get("last_translation_provider"),
    }


# ─── Realtime: Finalize sequence → LLM translation ───────────────────────

class FinalizeRequest(_BaseModel):
    lang: str = "fr"
    force: bool = False  # finalize even if builder says no


@router.post("/realtime/sessions/{session_id}/finalize", tags=["Realtime"])
async def finalize_realtime_session(
    session_id: str,
    body: FinalizeRequest,
    client=Depends(get_current_client_any),
):
    """Finalize an active realtime session: run LLM translation on the accumulated sign sequence.

    Returns a structured translation dict with natural_translation, literal_translation,
    intent, confidence, provider, and the raw signs list.
    """
    import asyncio

    if session_id not in _RT_SESSIONS:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")

    meta = _RT_SESSIONS[session_id]
    builder = get_or_create_builder(session_id)
    signs = builder.get_sequence()

    if not signs:
        return {
            "session_id": session_id,
            "signs": [],
            "natural_translation": "",
            "literal_translation": "",
            "intent": "",
            "confidence": 0.0,
            "provider": "none",
            "fallback": True,
            "message": "No signs accumulated yet.",
        }

    lang = body.lang if body.lang in ("en", "fr", "sw") else meta.get("target_language", "fr")

    kb_resolver = get_knowledge_resolver()
    kb_context = kb_resolver.resolve_signs(signs)

    llm_provider = get_llm_provider()
    translation = await llm_provider.translate_sequence(signs, kb_context, lang=lang)

    # Cache translation result in session metadata
    meta["last_natural_translation"] = translation.get("natural_translation")
    meta["last_literal_translation"] = translation.get("literal_translation")
    meta["last_translation_provider"] = translation.get("provider")

    return {
        "session_id": session_id,
        "signs": signs,
        **translation,
    }


# ─── Task 6: Quota Status ─────────────────────────────────────────────────

@router.get(
    "/quota/status",
    response_model=QuotaStatusResponse,
    tags=["Quota"],
)
async def quota_status(
    client=Depends(get_current_client_any),
):
    """Return the current API key's quota usage and alert level.

    alert_level:
    - "ok"       if quota_percent < 80 %
    - "warning"  if 80 % <= quota_percent < 95 %
    - "critical" if 95 % <= quota_percent <= 100 %
    - "exceeded" if quota_percent > 100 %
    """
    import datetime

    quota_used: int = getattr(client, "quota_used", 0)
    quota_limit: int = getattr(client, "quota_total", 1)

    if quota_limit <= 0:
        quota_limit = 1  # guard against division by zero

    quota_percent = round((quota_used / quota_limit) * 100.0, 2)

    if quota_percent > 100.0:
        alert_level = "exceeded"
    elif quota_percent >= 95.0:
        alert_level = "critical"
    elif quota_percent >= 80.0:
        alert_level = "warning"
    else:
        alert_level = "ok"

    # First day of next month
    today = datetime.date.today()
    if today.month == 12:
        reset_date = datetime.date(today.year + 1, 1, 1)
    else:
        reset_date = datetime.date(today.year, today.month + 1, 1)

    return QuotaStatusResponse(
        quota_used=quota_used,
        quota_limit=quota_limit,
        quota_percent=quota_percent,
        alert_level=alert_level,
        reset_date=reset_date.isoformat(),
    )


# ─── Gemini sentence builder ─────────────────────────────────────────────────

class BuildSentenceRequest(_BaseModel):
    signs: List[str]
    mode: str = "conversation"  # "conversation" | "alphabet"
    lang: str = "fr"


@router.post("/translate/build-sentence", tags=["Translate"])
async def build_sentence(
    body: BuildSentenceRequest,
    client=Depends(get_current_client_any),
):
    """Build a natural sentence from an accumulated sequence of signs using Gemini.

    - mode=conversation : signs are full ASL words → Gemini builds a sentence.
    - mode=alphabet     : signs are individual letters → joined into words then
                          passed to Gemini for natural language correction.
    """
    import sys
    import os as _os
    # Ensure project root on path for utils import
    _root = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    if _root not in sys.path:
        sys.path.insert(0, _root)

    from utils.gemini_client import GeminiTranslator

    signs = [s.strip() for s in body.signs if s.strip()]
    if not signs:
        return {
            "sentence": "",
            "raw_signs": [],
            "sign_sequence": "",
            "mode": body.mode,
            "lang": body.lang,
            "gemini_used": False,
        }

    if body.mode == "alphabet":
        # Letters separated by spaces (space = word boundary) → reconstruct words
        sign_sequence = "".join(signs)
    else:
        sign_sequence = " ".join(signs)

    lang = body.lang if body.lang in ("en", "fr", "sw") else "fr"

    translator = GeminiTranslator()
    sentence = await translator.translate_asl(sign_sequence, lang=lang)

    return {
        "sentence": sentence,
        "raw_signs": signs,
        "sign_sequence": sign_sequence,
        "mode": body.mode,
        "lang": lang,
        "gemini_used": True,
    }
