from __future__ import annotations

import datetime
import json
import logging
import os
from typing import Dict, Optional, Tuple

from fastapi import APIRouter, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database.models import ApiKey, AuditLog, Client, Plan, Subscription
from backend.database.session import SessionLocal

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

# Stripe price ID → plan slug mapping (read from environment)
def _price_to_slug_map() -> Dict[str, str]:
    return {
        os.getenv("STRIPE_PRICE_STARTER", ""): "starter",
        os.getenv("STRIPE_PRICE_PRO", ""): "pro",
        os.getenv("STRIPE_PRICE_ENTERPRISE", ""): "enterprise",
    }


def _get_stripe():
    """Lazy import of stripe so the service starts even without the package."""
    try:
        import stripe  # type: ignore[import]
        return stripe
    except ImportError:
        return None


def _find_client_by_customer(stripe_customer_id: str, db: Session) -> Optional[Client]:
    return (
        db.query(Client)
        .filter(Client.stripe_customer_id == stripe_customer_id)
        .first()
    )


def _write_audit(
    db: Session,
    action: str,
    target_type: str,
    target_id: Optional[int],
    details: Optional[dict] = None,
) -> None:
    db.add(AuditLog(
        actor_type="system",
        action=action,
        target_type=target_type,
        target_id=target_id,
        details=details,
    ))


def _upsert_subscription(
    client: Client,
    plan: Plan,
    stripe_subscription_id: Optional[str],
    period_start: Optional[datetime.datetime],
    period_end: Optional[datetime.datetime],
    db: Session,
) -> None:
    """Create or update the Subscription row for a client."""
    if client.subscription:
        sub = client.subscription
        sub.plan_id = plan.id
        sub.status = "active"
        sub.stripe_subscription_id = stripe_subscription_id or sub.stripe_subscription_id
        sub.current_period_start = period_start or sub.current_period_start
        sub.current_period_end = period_end or sub.current_period_end
        sub.updated_at = datetime.datetime.now(tz=datetime.timezone.utc)
    else:
        sub = Subscription(
            client_id=client.id,
            plan_id=plan.id,
            status="active",
            stripe_subscription_id=stripe_subscription_id,
            current_period_start=period_start,
            current_period_end=period_end,
        )
        db.add(sub)


def _adjust_key_quotas(client: Client, new_quota: int, db: Session) -> None:
    """Set quota_total on all active API keys for a client."""
    active_keys = (
        db.query(ApiKey)
        .filter(ApiKey.client_id == client.id, ApiKey.is_active.is_(True))
        .all()
    )
    for key in active_keys:
        key.quota_total = new_quota


# ---------------------------------------------------------------------------
# Webhook endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/stripe",
    status_code=status.HTTP_200_OK,
    summary="Stripe webhook receiver",
)
async def stripe_webhook(
    request: Request,
    stripe_signature: Optional[str] = Header(None, alias="stripe-signature"),
) -> dict:
    """Process incoming Stripe webhook events.

    Supported events:
    - ``checkout.session.completed``      → upgrade plan + create/update subscription
    - ``invoice.payment_succeeded``       → upgrade plan / top-up credits
    - ``customer.subscription.deleted``   → downgrade to free plan
    - ``customer.subscription.updated``   → sync subscription status
    """
    if not settings.stripe_secret_key:
        logger.info("Stripe webhook received but Stripe is not configured; ignoring.")
        return {"received": True, "configured": False}

    stripe = _get_stripe()
    if stripe is None:
        logger.error("stripe package not installed.")
        return {"received": True, "configured": False}

    stripe.api_key = settings.stripe_secret_key
    payload: bytes = await request.body()

    if settings.stripe_webhook_secret:
        if not stripe_signature:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing stripe-signature header.",
            )
        try:
            event = stripe.Webhook.construct_event(
                payload, stripe_signature, settings.stripe_webhook_secret
            )
        except stripe.error.SignatureVerificationError as exc:
            logger.warning("Stripe signature verification failed: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid stripe-signature.",
            ) from exc
    else:
        try:
            event = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Malformed JSON payload.",
            ) from exc

    event_type: str = event.get("type", "")
    event_data: dict = event.get("data", {}).get("object", {})

    db: Session = SessionLocal()
    try:
        if event_type == "checkout.session.completed":
            _handle_checkout_completed(event_data, db)
        elif event_type == "invoice.payment_succeeded":
            _handle_payment_succeeded(event_data, db)
        elif event_type == "customer.subscription.deleted":
            _handle_subscription_deleted(event_data, db)
        elif event_type == "customer.subscription.updated":
            _handle_subscription_updated(event_data, db)
        else:
            logger.debug("Unhandled Stripe event type: %s", event_type)

        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception("Error processing Stripe event %s: %s", event_type, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal error processing webhook.",
        ) from exc
    finally:
        db.close()

    return {"received": True, "type": event_type}


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------


def _resolve_plan_from_price_id(price_id: Optional[str], db: Session) -> Optional[Plan]:
    """Map a Stripe price ID to a Plan row via env vars."""
    if not price_id:
        return None
    slug = _price_to_slug_map().get(price_id)
    if not slug:
        return None
    return db.query(Plan).filter(Plan.slug == slug, Plan.is_active.is_(True)).first()


def _resolve_plan_from_metadata(metadata: dict, db: Session) -> Optional[Plan]:
    """Try to find a plan from Stripe metadata keys."""
    for key in ("plan", "plan_slug"):
        slug = metadata.get(key)
        if slug:
            plan = db.query(Plan).filter(Plan.slug == slug, Plan.is_active.is_(True)).first()
            if plan:
                return plan
    return None


def _handle_checkout_completed(event_data: dict, db: Session) -> None:
    """Handle checkout.session.completed → upgrade plan + create subscription."""
    stripe_customer_id: Optional[str] = event_data.get("customer")
    stripe_subscription_id: Optional[str] = event_data.get("subscription")
    metadata: dict = event_data.get("metadata", {})

    if not stripe_customer_id:
        logger.warning("checkout.session.completed missing customer id.")
        return

    client = _find_client_by_customer(stripe_customer_id, db)
    if client is None:
        logger.warning("No client found for Stripe customer %s", stripe_customer_id)
        return

    plan = _resolve_plan_from_metadata(metadata, db)
    if plan is None:
        logger.warning("checkout.session.completed: could not resolve plan from metadata %s", metadata)
        return

    client.plan = plan.slug
    _upsert_subscription(
        client=client,
        plan=plan,
        stripe_subscription_id=stripe_subscription_id,
        period_start=None,
        period_end=None,
        db=db,
    )
    _adjust_key_quotas(client, plan.monthly_request_limit, db)
    _write_audit(
        db,
        action="client.checkout_completed",
        target_type="client",
        target_id=client.id,
        details={"plan": plan.slug, "stripe_subscription_id": stripe_subscription_id},
    )
    logger.info("Client %s checkout completed → plan=%s", client.id, plan.slug)


def _handle_payment_succeeded(event_data: dict, db: Session) -> None:
    """Handle invoice.payment_succeeded → upgrade plan and set subscription periods."""
    stripe_customer_id: Optional[str] = event_data.get("customer")
    stripe_subscription_id: Optional[str] = event_data.get("subscription")

    if not stripe_customer_id:
        logger.warning("invoice.payment_succeeded missing customer id.")
        return

    client = _find_client_by_customer(stripe_customer_id, db)
    if client is None:
        logger.warning("No client found for Stripe customer %s", stripe_customer_id)
        return

    # Try to resolve plan from line item price IDs, then metadata
    lines = event_data.get("lines", {}).get("data", [])
    plan: Optional[Plan] = None

    for line in lines:
        price_id = line.get("price", {}).get("id")
        plan = _resolve_plan_from_price_id(price_id, db)
        if plan:
            break
        meta = (
            line.get("price", {}).get("metadata", {})
            or line.get("plan", {}).get("metadata", {})
        )
        plan = _resolve_plan_from_metadata(meta, db)
        if plan:
            break

    if plan is None:
        logger.info("invoice.payment_succeeded for client %s: could not resolve plan.", client.id)
        return

    # Extract period timestamps
    period_start: Optional[datetime.datetime] = None
    period_end: Optional[datetime.datetime] = None
    if lines:
        line_period = lines[0].get("period", {})
        if line_period.get("start"):
            period_start = datetime.datetime.fromtimestamp(
                line_period["start"], tz=datetime.timezone.utc
            )
        if line_period.get("end"):
            period_end = datetime.datetime.fromtimestamp(
                line_period["end"], tz=datetime.timezone.utc
            )

    client.plan = plan.slug
    _upsert_subscription(
        client=client,
        plan=plan,
        stripe_subscription_id=stripe_subscription_id,
        period_start=period_start,
        period_end=period_end,
        db=db,
    )
    _adjust_key_quotas(client, plan.monthly_request_limit, db)
    _write_audit(
        db,
        action="client.payment_succeeded",
        target_type="client",
        target_id=client.id,
        details={"plan": plan.slug, "quota": plan.monthly_request_limit},
    )
    logger.info("Client %s payment succeeded → plan=%s quota=%d", client.id, plan.slug, plan.monthly_request_limit)


def _handle_subscription_deleted(event_data: dict, db: Session) -> None:
    """Downgrade client to free when subscription is cancelled."""
    stripe_customer_id: Optional[str] = event_data.get("customer")
    if not stripe_customer_id:
        logger.warning("customer.subscription.deleted missing customer id.")
        return

    client = _find_client_by_customer(stripe_customer_id, db)
    if client is None:
        logger.warning("No client found for Stripe customer %s", stripe_customer_id)
        return

    free_plan = db.query(Plan).filter(Plan.slug == "free", Plan.is_active.is_(True)).first()
    client.plan = "free"

    if client.subscription:
        client.subscription.status = "cancelled"
        client.subscription.cancelled_at = datetime.datetime.now(tz=datetime.timezone.utc)
        client.subscription.updated_at = datetime.datetime.now(tz=datetime.timezone.utc)
        if free_plan:
            client.subscription.plan_id = free_plan.id

    if free_plan:
        _adjust_key_quotas(client, free_plan.monthly_request_limit, db)

    _write_audit(
        db,
        action="client.subscription_deleted",
        target_type="client",
        target_id=client.id,
        details={"downgraded_to": "free"},
    )
    logger.info("Client %s subscription deleted; downgraded to free.", client.id)


def _handle_subscription_updated(event_data: dict, db: Session) -> None:
    """Sync subscription status changes (paused, past_due, etc.)."""
    stripe_customer_id: Optional[str] = event_data.get("customer")
    stripe_subscription_id: Optional[str] = event_data.get("id")
    new_status: str = event_data.get("status", "active")

    if not stripe_customer_id:
        return

    client = _find_client_by_customer(stripe_customer_id, db)
    if client is None:
        return

    if client.subscription and stripe_subscription_id:
        if client.subscription.stripe_subscription_id == stripe_subscription_id:
            client.subscription.status = new_status
            client.subscription.updated_at = datetime.datetime.now(tz=datetime.timezone.utc)

    _write_audit(
        db,
        action="client.subscription_updated",
        target_type="client",
        target_id=client.id,
        details={"new_status": new_status},
    )
    logger.info("Client %s subscription updated → status=%s", client.id, new_status)
