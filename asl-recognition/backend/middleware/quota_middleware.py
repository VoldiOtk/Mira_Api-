from __future__ import annotations

import asyncio
import datetime
import logging
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import update
from sqlalchemy.orm import Session

from backend.database.models import ApiKey, UsageLog

logger = logging.getLogger(__name__)

# Quota alert thresholds (percent)
_ALERT_THRESHOLDS = (80, 95)


async def check_and_decrement_quota(
    api_key: ApiKey,
    db: Session,
    *,
    endpoint: str = "",
    method: str = "",
    status_code: int = 200,
    model_id: Optional[int] = None,
    inference_ms: Optional[float] = None,
) -> None:
    """Atomically consume one unit of quota, enforce rate limiting, and write a UsageLog row.

    Raises:
        HTTPException 429 when rate limit is exceeded (checked first).
        HTTPException 429 when quota is exhausted.
    """
    # ------------------------------------------------------------------
    # Rate limit check — runs before decrementing quota
    # ------------------------------------------------------------------
    rate_limit = _get_rate_limit_for_key(api_key, db)
    if rate_limit > 0:
        from backend.middleware.rate_limit_middleware import check_rate_limit, get_redis_client
        redis = get_redis_client()
        await check_rate_limit(api_key.id, rate_limit, redis_client=redis)

    # ------------------------------------------------------------------
    # Atomic quota decrement
    # ------------------------------------------------------------------
    result = db.execute(
        update(ApiKey)
        .where(
            ApiKey.id == api_key.id,
            ApiKey.is_active.is_(True),
            ApiKey.quota_used < ApiKey.quota_total,
        )
        .values(
            quota_used=ApiKey.quota_used + 1,
            last_used_at=datetime.datetime.now(tz=datetime.timezone.utc),
        )
        .execution_options(synchronize_session="fetch")
    )

    if result.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="API quota exhausted. Please upgrade your plan or purchase more credits.",
        )

    # ------------------------------------------------------------------
    # Refresh to get latest quota values for alert check
    # ------------------------------------------------------------------
    db.refresh(api_key)
    _maybe_send_quota_alert(api_key)

    # ------------------------------------------------------------------
    # Write usage log
    # ------------------------------------------------------------------
    log = UsageLog(
        api_key_id=api_key.id,
        client_id=api_key.client_id,
        endpoint=endpoint,
        method=method,
        status_code=status_code,
        model_id=model_id,
        inference_ms=inference_ms,
        timestamp=datetime.datetime.now(tz=datetime.timezone.utc),
    )
    db.add(log)
    db.commit()

    logger.debug(
        "Quota decremented for api_key_id=%s client_id=%s endpoint=%s",
        api_key.id,
        api_key.client_id,
        endpoint,
    )


def _get_rate_limit_for_key(api_key: ApiKey, db: Session) -> int:
    """Return the rate_limit_per_minute from the client's active plan, or 60 as default."""
    from backend.database.models import Client, Plan, Subscription

    try:
        client = db.get(Client, api_key.client_id)
        if client and client.subscription and client.subscription.plan:
            return client.subscription.plan.rate_limit_per_minute
    except Exception as exc:
        logger.warning("Could not resolve plan rate limit for key %s: %s", api_key.id, exc)
    return 60


def _maybe_send_quota_alert(api_key: ApiKey) -> None:
    """Fire-and-forget quota alert email when usage crosses 80% or 95%."""
    if api_key.quota_total <= 0:
        return
    percent = int((api_key.quota_used / api_key.quota_total) * 100)

    for threshold in _ALERT_THRESHOLDS:
        # Trigger when the usage just crossed the threshold (within 1 unit)
        prev_percent = int(((api_key.quota_used - 1) / api_key.quota_total) * 100)
        if prev_percent < threshold <= percent:
            asyncio.create_task(_send_alert_task(api_key, percent))
            break


async def _send_alert_task(api_key: ApiKey, percent_used: int) -> None:
    """Background task: fetch client info and send quota alert email."""
    from backend.database.session import SessionLocal
    from backend.database.models import Client
    from backend.services.email_service import send_quota_alert_email

    db = SessionLocal()
    try:
        client = db.get(Client, api_key.client_id)
        if client:
            send_quota_alert_email(
                client_email=client.email,
                client_name=client.name,
                percent_used=percent_used,
                quota_used=api_key.quota_used,
                quota_total=api_key.quota_total,
            )
    except Exception as exc:
        logger.warning("Quota alert email failed for key %s: %s", api_key.id, exc)
    finally:
        db.close()


def log_usage(
    db: Session,
    *,
    api_key_id: Optional[int] = None,
    client_id: Optional[int] = None,
    endpoint: str,
    method: str,
    status_code: int,
    model_id: Optional[int] = None,
    inference_ms: Optional[float] = None,
) -> UsageLog:
    """Write a UsageLog row without touching quota.

    Useful for logging unauthenticated or admin requests that should not
    decrement any quota counter.
    """
    log = UsageLog(
        api_key_id=api_key_id,
        client_id=client_id,
        endpoint=endpoint,
        method=method,
        status_code=status_code,
        model_id=model_id,
        inference_ms=inference_ms,
        timestamp=datetime.datetime.now(tz=datetime.timezone.utc),
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log
