from __future__ import annotations
import os
from typing import Optional
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session
from backend.database.session import get_db

API_KEYS_REQUIRED = os.getenv("API_KEYS_REQUIRED", "false").lower() == "true"


class _AnonClient:
    id: Optional[int] = None
    client_id: Optional[int] = None
    quota_used: int = 0
    quota_total: int = 999_999
    is_active: bool = True


async def get_current_client_any(
    x_api_key: str = Header(default=""),
    db: Session = Depends(get_db),
):
    if not API_KEYS_REQUIRED:
        return _AnonClient()
    if not x_api_key:
        raise HTTPException(status_code=401, detail="X-API-Key header required")
    return _AnonClient()


async def get_current_client(
    x_api_key: str = Header(default=""),
    db: Session = Depends(get_db),
):
    if not API_KEYS_REQUIRED:
        return _AnonClient()
    if not x_api_key:
        raise HTTPException(status_code=401, detail="X-API-Key header required")
    return _AnonClient()


async def get_admin(
    x_api_key: str = Header(default=""),
    db: Session = Depends(get_db),
):
    if not API_KEYS_REQUIRED:
        return _AnonClient()
    if not x_api_key:
        raise HTTPException(status_code=403, detail="Admin access required")
    return _AnonClient()
