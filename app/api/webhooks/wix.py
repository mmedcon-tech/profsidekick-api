"""
Wix payment webhook handler.

Wix Automations fires a POST to this endpoint every time an order is paid.

Authentication — two supported methods (use whichever matches your Wix setup):

  Method A — Velo Code (recommended):
    The Wix "Run Velo Code" action sets  X-Webhook-Secret: <secret>  in the
    request headers. Backend verifies this header.

  Method B — URL query parameter (fallback, no Velo required):
    Append ?secret=<secret> to the endpoint URL in the "Send HTTP Request"
    action. Backend checks the query param if the header is absent.
    Less ideal (secret visible in server access logs) but functional.

Idempotency:
  Each Wix order ID is stored in processed_wix_orders. Duplicate webhook
  deliveries are silently acknowledged without double-crediting.
"""

import json
import logging
import secrets
import uuid
from decimal import Decimal
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database.connection import get_db
from app.database.models import ProcessedWixOrder, User
from app.services.billing_service import add_credits

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _verify_secret(header_secret: Optional[str], query_secret: Optional[str]) -> None:
    """
    Accept the shared secret from either the X-Webhook-Secret header (Velo path)
    or the ?secret= query parameter (standard HTTP request path).
    """
    configured = settings.wix_webhook_secret
    if not configured:
        logger.warning(
            "WIX_WEBHOOK_SECRET is not set — webhook endpoint is unprotected. "
            "Set this env var before going to production."
        )
        return

    provided = header_secret or query_secret
    if not provided or not secrets.compare_digest(configured, provided):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing webhook secret.",
        )


def _extract(payload: Dict[str, Any], *paths: str) -> Optional[Any]:
    """
    Walk dot-separated key paths and return the first one that resolves.
    E.g. _extract(p, "order.buyerInfo.email", "buyerEmail", "buyer.email")
    """
    for path in paths:
        node = payload
        for key in path.split("."):
            if not isinstance(node, dict):
                node = None
                break
            node = node.get(key)
        if node is not None:
            return node
    return None


def _get_product_credit_map() -> Dict[str, int]:
    """Parse WIX_PRODUCT_CREDIT_MAP from settings (JSON string)."""
    try:
        raw = json.loads(settings.wix_product_credit_map)
        return {str(k): int(v) for k, v in raw.items()}
    except Exception:
        logger.error("WIX_PRODUCT_CREDIT_MAP is not valid JSON — no products mapped.")
        return {}


def _extract_order_id(payload: Dict[str, Any]) -> Optional[str]:
    return _extract(
        payload,
        "_id",
        "order.id",
        "orderId",
        "id",
        "data.order.id",
        "data.orderId",
    )


def _extract_buyer_email(payload: Dict[str, Any]) -> Optional[str]:
    return _extract(
        payload,
        "order.buyerInfo.email",
        "buyerInfo.email",
        "buyer.email",
        "buyerEmail",
        "data.order.buyerInfo.email",
        "contactDetails.email",
        "email",
    )


def _extract_line_items(payload: Dict[str, Any]) -> list:
    """Return raw line items list, trying common Wix payload paths."""
    items = _extract(
        payload,
        "order.lineItems",
        "lineItems",
        "data.order.lineItems",
    )
    return items if isinstance(items, list) else []


def _extract_product_id(item: Dict[str, Any]) -> Optional[str]:
    return _extract(
        item,
        "catalogReference.catalogItemId",
        "productId",
        "catalogItemId",
        "id",
    )


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post("/wix-payment")
async def wix_payment_webhook(
    request: Request,
    x_webhook_secret: Optional[str] = Header(None, alias="X-Webhook-Secret"),
    secret: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Receive Wix order-paid events and credit the buyer's account.

    Returns 200 for every valid request — including duplicates and orders for
    unregistered buyers — so Wix does not retry unnecessarily.
    """
    _verify_secret(x_webhook_secret, secret)

    try:
        payload: Dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request body must be valid JSON.",
        )

    logger.debug("Wix webhook payload received: %s", json.dumps(payload, default=str))

    # ── 1. Extract order ID ──────────────────────────────────────────────────
    order_id = _extract_order_id(payload)
    if not order_id:
        logger.warning(
            "Wix webhook: could not extract order_id — payload keys: %s",
            list(payload.keys()),
        )
        return {"received": True, "warning": "order_id not found — no credits added"}

    # ── 2. Idempotency check ─────────────────────────────────────────────────
    existing = (
        db.query(ProcessedWixOrder)
        .filter(ProcessedWixOrder.wix_order_id == str(order_id))
        .first()
    )
    if existing:
        logger.info("Wix webhook: order %s already processed — skipping", order_id)
        return {"received": True, "status": "already_processed"}

    # ── 3. Extract buyer email ───────────────────────────────────────────────
    buyer_email = _extract_buyer_email(payload)
    if not buyer_email:
        logger.warning(
            "Wix webhook: could not extract buyer email for order %s", order_id
        )
        _record_processed(db, order_id, user_id=None, credits_added=Decimal("0"))
        return {"received": True, "warning": "buyer email not found — no credits added"}

    # ── 4. Look up ProfSidekick user ─────────────────────────────────────────
    user = db.query(User).filter(User.email == buyer_email.lower().strip()).first()
    if not user:
        logger.warning(
            "Wix webhook: no ProfSidekick account for email '%s' (order %s). "
            "User must register first, then contact support to apply credits.",
            buyer_email,
            order_id,
        )
        _record_processed(db, order_id, user_id=None, credits_added=Decimal("0"))
        return {
            "received": True,
            "warning": "no account found for buyer email — credits not applied",
        }

    # ── 5. Map line items → credits ──────────────────────────────────────────
    product_map = _get_product_credit_map()
    line_items = _extract_line_items(payload)
    total_credits_usd = Decimal("0")

    for item in line_items:
        product_id = _extract_product_id(item)
        if not product_id:
            continue
        credits = product_map.get(str(product_id), 0)
        if credits <= 0:
            logger.info(
                "Wix webhook: product_id '%s' not in WIX_PRODUCT_CREDIT_MAP — skipped",
                product_id,
            )
            continue
        quantity = int(item.get("quantity", 1))
        total_credits = credits * quantity
        # Convert credits → USD for billing_service.add_credits (it converts back)
        credits_per_usd = int(settings.credits_per_usd)
        amount_usd = Decimal(str(total_credits)) / Decimal(str(credits_per_usd))
        total_credits_usd += amount_usd
        logger.info(
            "Wix webhook: order %s — product %s qty %d → %d credits ($%s USD)",
            order_id,
            product_id,
            quantity,
            total_credits,
            amount_usd,
        )

    if total_credits_usd == Decimal("0"):
        logger.warning(
            "Wix webhook: order %s had no recognised products — check WIX_PRODUCT_CREDIT_MAP",
            order_id,
        )
        _record_processed(db, order_id, user_id=user.id, credits_added=Decimal("0"))
        return {
            "received": True,
            "warning": "no recognised products in order — check WIX_PRODUCT_CREDIT_MAP",
        }

    # ── 6. Credit the account ────────────────────────────────────────────────
    add_credits(user.id, total_credits_usd, db)
    actual_credits = total_credits_usd * Decimal(str(settings.credits_per_usd))
    _record_processed(db, order_id, user_id=user.id, credits_added=actual_credits)

    logger.info(
        "Wix webhook: credited %.4f credits to user %s (order %s)",
        actual_credits,
        user.id,
        order_id,
    )
    return {
        "received": True,
        "status": "credited",
        "credits_added": str(actual_credits),
        "user_email": buyer_email,
    }


def _record_processed(
    db: Session,
    wix_order_id: str,
    user_id: Optional[Any],
    credits_added: Decimal,
) -> None:
    record = ProcessedWixOrder(
        id=uuid.uuid4(),
        wix_order_id=str(wix_order_id),
        user_id=user_id,
        credits_added=credits_added,
    )
    db.add(record)
    db.commit()
