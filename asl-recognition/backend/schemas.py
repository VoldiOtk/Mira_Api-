from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator


# ---------------------------------------------------------------------------
# Auth — password reset
# ---------------------------------------------------------------------------

class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=1)
    new_password: str = Field(..., description="Nouveau mot de passe (min. 8 caractères)")


class MessageResponse(BaseModel):
    message: str
    dev_reset_link: Optional[str] = None


# ---------------------------------------------------------------------------
# Inference — single frame
# ---------------------------------------------------------------------------

class RecognizeRequest(BaseModel):
    image: str = Field(..., description="Image JPEG/PNG en base64 (avec ou sans préfixe data:image/...)")
    lang: str = Field("fr", description="fr | en")
    mode: str = Field("holistic", description="holistic | hands")
    session_id: Optional[str] = Field(
        None,
        description="ID de session pour accumuler 30 frames (mode holistic). Réutiliser le même ID entre images.",
    )

    @field_validator("image")
    @classmethod
    def image_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Image ne peut pas être vide")
        if len(v) > 14_000_000:
            raise ValueError("Image trop grande (max ~10 MB)")
        return v


class RecognizeResponse(BaseModel):
    session_id: str
    label: Optional[str] = None
    translation: Optional[str] = None
    preview_label: Optional[str] = None
    preview_translation: Optional[str] = None
    confidence: float = 0.0
    margin: float = 0.0
    stable: bool = False
    hands_detected: bool = False
    sequence_len: Optional[int] = None
    sequence_required: Optional[int] = None
    lang: str = "fr"
    mode: str = "holistic"
    image: Optional[str] = Field(None, description="Image annotée (MediaPipe) en base64 JPEG. Absent si annotate=false.")
    message: Optional[str] = None
    top_predictions: Optional[List[dict]] = None
    suggestion: Optional[str] = None
    auto_selected_model: Optional[int] = None
    raw_label: Optional[str] = None
    translated_text: Optional[str] = None
    source_language: Optional[str] = None
    target_language: Optional[str] = None
    translation_fallback: Optional[bool] = None
    # Sequence tracking (SignSequenceBuilder)
    confirmed_sequence: Optional[List[str]] = None
    pending_sign: Optional[str] = None


# ---------------------------------------------------------------------------
# Inference — batch (30 frames in one call)
# ---------------------------------------------------------------------------

class BatchRecognizeRequest(BaseModel):
    frames: List[str] = Field(
        ...,
        min_length=1,
        max_length=60,
        description="Liste d'images en base64 (1-60 frames). Traitées dans l'ordre.",
    )
    lang: str = Field("fr", description="fr | en")
    mode: str = Field("holistic", description="holistic | hands")
    session_id: Optional[str] = Field(
        None,
        description="ID de session persistant. Si absent, une nouvelle session est créée.",
    )


class BatchRecognizeResponse(BaseModel):
    session_id: str
    label: Optional[str] = None
    translation: Optional[str] = None
    confidence: float = 0.0
    margin: float = 0.0
    stable: bool = False
    hands_detected: bool = False
    sequence_len: Optional[int] = None
    sequence_required: Optional[int] = None
    lang: str = "fr"
    mode: str = "holistic"
    frames_processed: int = 0
    message: Optional[str] = None


# ---------------------------------------------------------------------------
# Inference — video file
# ---------------------------------------------------------------------------

class VideoSegment(BaseModel):
    timestamp_s: float
    label: str
    translation: Optional[str] = None
    confidence: float


class VideoRecognizeResponse(BaseModel):
    duration_s: float
    frames_processed: int
    segments: List[VideoSegment]
    language: str


# ---------------------------------------------------------------------------
# Inference — feedback (correction boucle d'amélioration)
# ---------------------------------------------------------------------------

class FeedbackRequest(BaseModel):
    session_id: Optional[str] = None
    predicted_label: str = Field(..., description="Ce que le modèle a prédit", max_length=128)
    correct_label: str = Field(..., description="Le vrai signe effectué", max_length=128)
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    model_id: Optional[int] = None

    @field_validator("predicted_label", "correct_label")
    @classmethod
    def label_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Le label ne peut pas être vide")
        return v


# ---------------------------------------------------------------------------
# Signs catalog
# ---------------------------------------------------------------------------

class SignInfo(BaseModel):
    label: str
    fr: str
    en: str


class SignsResponse(BaseModel):
    model_name: Optional[str] = None
    language_code: str
    input_size: int
    feature_version: str
    model_type: str
    count: int
    signs: List[SignInfo]


# ---------------------------------------------------------------------------
# Text-to-sign
# ---------------------------------------------------------------------------

class TextToSignRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=200)
    lang: str = Field("fr", description="fr | en")
    include_media_base64: bool = Field(
        True,
        description="Inclure le média (image JPEG ou vidéo MP4) encodé en base64",
    )


class SignItemResponse(BaseModel):
    type: str
    asl_label: str
    label_en: str
    label_fr: str
    translation: str
    media_url: Optional[str] = None
    media_full_url: Optional[str] = Field(
        None,
        description="URL absolue du média (base de la requête + media_url). À utiliser côté mobile.",
    )
    media_mime: Optional[str] = None
    media_base64: Optional[str] = None
    start_sec: float = 0.0
    end_sec: float = 0.0
    note: Optional[str] = None


class TextToSignResponse(BaseModel):
    query: str
    lang: str
    signs: List[SignItemResponse]
    found: int
    missing: List[str]
    message: str
    vocabulary_size: int = 0


# ---------------------------------------------------------------------------
# Model playground
# ---------------------------------------------------------------------------

class ModelTestResponse(BaseModel):
    model_id: int
    model_name: Optional[str] = None
    label: Optional[str] = None
    confidence: float
    top_predictions: List[dict]
    inference_time_ms: float
    hands_detected: bool
    input_size: int
    feature_version: str
    model_type: str


# ---------------------------------------------------------------------------
# Realtime sessions
# ---------------------------------------------------------------------------

class RealtimeSessionResponse(BaseModel):
    session_id: str
    expires_at: str
    mode: str
    lang: str = "fr"
    model_id: Optional[int] = None


class RealtimeSessionStatus(BaseModel):
    session_id: str
    sequence_len: int
    sequence_required: int
    feature_version: str
    mode: str
    last_used: float


# ---------------------------------------------------------------------------
# Quota
# ---------------------------------------------------------------------------

class QuotaStatusResponse(BaseModel):
    quota_used: int
    quota_limit: int
    quota_percent: float
    alert_level: str  # "ok" | "warning" | "critical" | "exceeded"
    reset_date: str
