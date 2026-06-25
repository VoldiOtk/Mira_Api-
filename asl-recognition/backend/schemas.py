"""
Pydantic schemas for the Mira ASL recognition API.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


class RecognizeResponse(BaseModel):
    """Response schema for a single inference frame."""

    label: Optional[str] = None
    raw_label: Optional[str] = None
    preview_label: Optional[str] = None
    confidence: float = 0.0
    stable: bool = False
    top2_margin: Optional[float] = None

    # Sequence tracking fields (populated when a builder is attached)
    confirmed_sequence: Optional[List[str]] = None
    pending_sign: Optional[str] = None

    class Config:
        extra = "allow"
