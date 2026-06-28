from __future__ import annotations
import base64
import json
import logging
import os
import sys
import uuid
from collections import deque
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

_log = logging.getLogger(__name__)

# ─── Path setup — needed so `from model.model import ...` and
#     `from utils.mediapipe_extractor import ...` resolve from any CWD.
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# ─── Constants ────────────────────────────────────────────────────────────────

SEQUENCE_LENGTH: int = 30
MIN_STABLE_COUNT: int = 3
PREDICTION_THRESHOLD: float = 0.55
TOP2_MARGIN_THRESHOLD: float = 0.12
NON_SIGN_LABELS: set = {"nothing", "space", "del", "blank"}
ACTIONS_HOLISTIC: List[str] = []   # populated on first _load_model() call

# model.pth is trained on 1662-dim v1 (holistic with face).
_default_feature_version: str = "v1"
_default_input_size: int = 1662


# ─── Model singleton (lazy-loaded once per process) ───────────────────────────

_MODEL: Any = None
_ACTIONS: List[str] = []
_MODEL_INPUT_SIZE: int = 1662
_LABELS_CACHE: dict = {}


def _load_model() -> None:
    """Load ASLLstmModel + labels from disk. Safe to call repeatedly (idempotent)."""
    global _MODEL, _ACTIONS, _MODEL_INPUT_SIZE

    if _MODEL is not None:
        return

    meta_path = os.path.join(_ROOT, 'model', 'model_meta.json')
    model_path = os.path.join(_ROOT, 'model', 'model.pth')

    if not os.path.exists(model_path) or not os.path.exists(meta_path):
        _log.warning("ASL model not found — recognition will return no predictions.")
        return

    try:
        import torch
        with open(meta_path, encoding='utf-8') as fh:
            meta = json.load(fh)

        _ACTIONS = meta.get('actions', [])
        _MODEL_INPUT_SIZE = meta.get('input_size', 1662)

        # Sync module-level ACTIONS_HOLISTIC so /signs endpoint works
        ACTIONS_HOLISTIC.clear()
        ACTIONS_HOLISTIC.extend(_ACTIONS)

        num_classes = len(_ACTIONS)
        from model.model import ASLLstmModel
        net = ASLLstmModel(input_size=_MODEL_INPUT_SIZE, num_classes=num_classes)
        state = torch.load(model_path, map_location='cpu', weights_only=False)
        net.load_state_dict(state)
        net.eval()
        _MODEL = net
        _log.info(
            "ASLLstmModel loaded: %d classes, input=%d, path=%s",
            num_classes, _MODEL_INPUT_SIZE, model_path,
        )
    except Exception as exc:
        _log.error("Failed to load ASL model: %s", exc, exc_info=True)


# ─── Session management ────────────────────────────────────────────────────────

class _StubExtractor:
    """Used only when MediaPipe is unavailable (import error / missing package)."""
    def process_frame(
        self, frame_bgr: np.ndarray, *, annotate: bool = True, feature_version: str = "v1"
    ) -> Tuple[np.ndarray, List[float], bool]:
        size = 1662 if feature_version == "v1" else 258
        return frame_bgr, [0.0] * size, False


class _Session:
    def __init__(self, mode: str = "holistic", feature_version: str = "v1"):
        self.mode = mode
        self.feature_version = feature_version
        self.sequence: deque = deque(maxlen=SEQUENCE_LENGTH)
        self.history: deque = deque(maxlen=10)
        self._extractor: Any = None

    @property
    def extractor(self):
        """Lazily create one MediaPipeExtractor per session (heavy init)."""
        if self._extractor is None:
            try:
                from utils.mediapipe_extractor import MediaPipeExtractor
                self._extractor = MediaPipeExtractor(mode=self.mode)
                _log.debug("MediaPipeExtractor(%s) created for session.", self.mode)
            except Exception as exc:
                _log.error(
                    "MediaPipeExtractor init failed (%s) — falling back to stub extractor.",
                    exc,
                )
                self._extractor = _StubExtractor()
        return self._extractor


_sessions: Dict[str, _Session] = {}


def get_or_create_session(
    session_id: Optional[str],
    mode: str = "holistic",
    feature_version: str = "v1",
) -> Tuple[str, _Session]:
    sid = session_id or str(uuid.uuid4())
    if sid not in _sessions:
        _sessions[sid] = _Session(mode=mode, feature_version=feature_version)
    return sid, _sessions[sid]


# ─── Image helpers ─────────────────────────────────────────────────────────────

def decode_image_b64(b64_string: str) -> Optional[np.ndarray]:
    try:
        if "," in b64_string:
            b64_string = b64_string.split(",", 1)[1]
        raw = base64.b64decode(b64_string)
        arr = np.frombuffer(raw, np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)
    except Exception:
        return None


def encode_image_b64(image_bgr: np.ndarray) -> Optional[str]:
    try:
        ok, buf = cv2.imencode(".jpg", image_bgr, [cv2.IMWRITE_JPEG_QUALITY, 70])
        if not ok:
            return None
        return base64.b64encode(buf.tobytes()).decode("ascii")
    except Exception:
        return None


# ─── Translation ───────────────────────────────────────────────────────────────

def normalize_lang(lang: str) -> str:
    lang = (lang or "fr").lower().strip()
    mapping = {"french": "fr", "english": "en", "swahili": "sw"}
    return mapping.get(lang, lang)


def find_translation(label: str, lang: str = "fr") -> dict:
    base = {"source_language": "asl", "target_language": lang}
    if not label:
        return {**base, "text": "", "translated_text": "", "fallback": True}

    global _LABELS_CACHE
    if not _LABELS_CACHE:
        labels_path = os.path.join(_ROOT, "data", "knowledge", "labels.json")
        if os.path.exists(labels_path):
            try:
                with open(labels_path, encoding="utf-8") as fh:
                    _LABELS_CACHE = json.load(fh)
            except Exception:
                _LABELS_CACHE = {}

    entry = _LABELS_CACHE.get(label.lower(), _LABELS_CACHE.get(label, {}))
    if isinstance(entry, dict) and entry:
        translated = entry.get(lang, entry.get("en", label))
        return {**base, "text": label, "translated_text": translated, "fallback": False}

    return {**base, "text": label, "translated_text": label, "fallback": True}


# ─── Inference ────────────────────────────────────────────────────────────────

def predict_frame(
    frame: np.ndarray,
    *,
    lang: str = "fr",
    mode: str = "holistic",
    session_id: Optional[str] = None,
    annotate: bool = True,
    top_k: int = 3,
) -> dict:
    """Run MediaPipe + LSTM on a single BGR frame; accumulates a 30-frame sequence."""
    _load_model()

    sid, sess = get_or_create_session(session_id, mode, _default_feature_version)
    image_bgr, keypoints, hands_present = sess.extractor.process_frame(
        frame, annotate=annotate, feature_version=sess.feature_version
    )
    sess.sequence.append(keypoints)

    lang_norm = normalize_lang(lang)

    prediction_label: str = ""
    confidence: float = 0.0
    top2_margin: float = 0.0
    top_predictions: Optional[List[dict]] = None

    if _MODEL is not None and len(sess.sequence) == SEQUENCE_LENGTH and hands_present:
        try:
            import torch
            import torch.nn.functional as F

            seq = np.array(list(sess.sequence), dtype=np.float32)  # (30, input_size)
            x = torch.from_numpy(seq).unsqueeze(0)                  # (1, 30, input_size)

            with torch.no_grad():
                logits = _MODEL(x)
                probs = F.softmax(logits, dim=-1)[0]

            probs_np: np.ndarray = probs.numpy()
            top_idxs = np.argsort(probs_np)[::-1][:max(top_k, 2)]

            best_idx = int(top_idxs[0])
            best_conf = float(probs_np[best_idx])
            second_conf = float(probs_np[top_idxs[1]]) if len(top_idxs) > 1 else 0.0
            top2_margin = best_conf - second_conf

            best_label = _ACTIONS[best_idx] if best_idx < len(_ACTIONS) else str(best_idx)

            if (
                best_conf >= PREDICTION_THRESHOLD
                and top2_margin >= TOP2_MARGIN_THRESHOLD
                and best_label.lower() not in NON_SIGN_LABELS
            ):
                prediction_label = best_label
                confidence = best_conf

            top_predictions = [
                {
                    "label": _ACTIONS[i] if i < len(_ACTIONS) else str(i),
                    "confidence": round(float(probs_np[i]), 4),
                    "translated_text": find_translation(
                        _ACTIONS[i] if i < len(_ACTIONS) else str(i), lang_norm
                    )["translated_text"],
                }
                for i in top_idxs[:top_k]
                if float(probs_np[i]) >= 0.05
            ] or None

        except Exception as exc:
            _log.error("LSTM inference error: %s", exc, exc_info=True)

    # Stability: same sign must appear MIN_STABLE_COUNT times in recent history
    is_stable = False
    stable_label = ""
    if prediction_label and prediction_label.lower() not in NON_SIGN_LABELS:
        sess.history.append(prediction_label)
        stable_label = max(set(sess.history), key=sess.history.count)
        is_stable = sess.history.count(stable_label) >= MIN_STABLE_COUNT
    elif not prediction_label:
        # No prediction — slowly drain history so stale signs don't persist
        if sess.history:
            sess.history.popleft()

    label_out: Optional[str] = stable_label if is_stable else (prediction_label or None)
    if label_out and label_out.lower() in NON_SIGN_LABELS:
        label_out = None
        is_stable = False

    translation_info = find_translation(label_out or "", lang_norm)

    # Preview: best prediction even below threshold (helps UI show progress)
    preview_label: Optional[str] = None
    preview_translation: Optional[str] = None
    if top_predictions and not label_out:
        preview_label = top_predictions[0]["label"]
        preview_translation = top_predictions[0]["translated_text"]

    # Human-readable hint
    message: Optional[str] = None
    if mode == "holistic" and len(sess.sequence) < SEQUENCE_LENGTH:
        remaining = SEQUENCE_LENGTH - len(sess.sequence)
        if lang_norm == "en":
            message = f"Holistic mode: send {remaining} more image(s) with the same session_id."
        else:
            message = f"Mode holistic : envoyez encore {remaining} image(s) avec le même session_id."

    # Low-confidence suggestion
    suggestion: Optional[str] = None
    if not hands_present:
        suggestion = "Aucune main détectée. Assurez-vous que vos mains sont visibles."
    elif _MODEL is not None and len(sess.sequence) == SEQUENCE_LENGTH:
        if confidence < 0.40:
            suggestion = "Signe non reconnu. Essayez avec un meilleur éclairage ou un autre angle."
        elif confidence < PREDICTION_THRESHOLD:
            suggestion = "Confiance faible. Continuez à signer pour accumuler plus de frames."
        elif top2_margin < TOP2_MARGIN_THRESHOLD and confidence > 0.0:
            suggestion = "Le signe est ambigu entre plusieurs prédictions. Signez plus lentement."

    return {
        "session_id": sid,
        "label": label_out,
        "translation": translation_info["translated_text"] if label_out else None,
        "preview_label": preview_label,
        "preview_translation": preview_translation,
        "confidence": round(confidence, 4),
        "margin": round(top2_margin, 4),
        "stable": is_stable,
        "hands_detected": hands_present,
        "sequence_len": len(sess.sequence),
        "sequence_required": SEQUENCE_LENGTH if mode == "holistic" else 1,
        "lang": lang_norm,
        "mode": mode,
        "image": encode_image_b64(image_bgr) if annotate else None,
        "message": message,
        "top_predictions": top_predictions,
        "suggestion": suggestion,
        "raw_label": label_out,
        "translated_text": translation_info["translated_text"],
        "source_language": "asl",
        "target_language": lang_norm,
        "translation_fallback": translation_info["fallback"],
        "confirmed_sequence": [],
    }
