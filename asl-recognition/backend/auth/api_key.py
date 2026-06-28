from __future__ import annotations
import hashlib
import os


def verify_api_key(raw_key: str, stored_hash: str) -> bool:
    return hashlib.sha256(raw_key.encode()).hexdigest() == stored_hash


def key_prefix_from_full(raw_key: str) -> str:
    return raw_key[:8] if len(raw_key) >= 8 else raw_key
