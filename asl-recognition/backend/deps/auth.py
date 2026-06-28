from __future__ import annotations
import os
from fastapi import Header, HTTPException, status

API_KEYS_REQUIRED = os.getenv("API_KEYS_REQUIRED", "false").lower() == "true"


async def require_api_key(x_api_key: str = Header(default="")):
    if not API_KEYS_REQUIRED:
        return x_api_key
    valid_keys = [k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()]
    if not valid_keys:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API key authentication enabled but no keys configured",
        )
    if x_api_key not in valid_keys:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid API key")
    return x_api_key
