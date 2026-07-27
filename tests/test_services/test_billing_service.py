"""Unit tests for billing_service — all DB interaction is mocked."""

import uuid
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.services.billing_service import (
    CREDITS_PER_USD,
    _generate_access_code,
    calculate_cost,
    charge_usage,
    get_active_balance,
)


# ---------------------------------------------------------------------------
# _generate_access_code
# ---------------------------------------------------------------------------


def test_generate_access_code_format():
    code = _generate_access_code()
    parts = code.split("-")
    assert len(parts) == 3
    for part in parts:
        assert len(part) == 4
        assert part.isupper()
        assert part.isalnum()


# ---------------------------------------------------------------------------
# get_active_balance
# ---------------------------------------------------------------------------


def _make_db():
    return MagicMock()


def _make_access_code(remaining: Decimal = Decimal("10"), active=True, expired=False):
    ac = MagicMock()
    ac.is_active = active
    ac.remaining_credits = remaining
    ac.code = "TEST-CODE-0001"
    ac.issued_by = "pytest"
    from datetime import datetime, timedelta

    ac.expires_at = (datetime.utcnow() - timedelta(days=1)) if expired else None
    return ac


def test_get_active_balance_access_code_priority():
    db = _make_db()
    access_code = _make_access_code(remaining=Decimal("50"))
    redemption = MagicMock()
    redemption.access_code = access_code
    redemption.access_code_id = uuid.uuid4()

    # Simulate query chain returning redemption
    db.query.return_value.join.return_value.filter.return_value.filter.return_value.order_by.return_value.first.return_value = (
        redemption
    )

    result = get_active_balance(uuid.uuid4(), db)
    assert result["source"] == "access_code"
    assert result["balance"] == Decimal("50")


def test_get_active_balance_falls_back_to_purchased():
    db = _make_db()
    # No redemption found
    db.query.return_value.join.return_value.filter.return_value.filter.return_value.order_by.return_value.first.return_value = (
        None
    )
    credit_balance = MagicMock()
    credit_balance.balance_credits = Decimal("25.5")
    db.query.return_value.filter.return_value.first.return_value = credit_balance

    result = get_active_balance(uuid.uuid4(), db)
    assert result["source"] == "purchased"
    assert result["balance"] == Decimal("25.5")


def test_get_active_balance_no_balance():
    db = _make_db()
    db.query.return_value.join.return_value.filter.return_value.filter.return_value.order_by.return_value.first.return_value = (
        None
    )
    db.query.return_value.filter.return_value.first.return_value = None

    result = get_active_balance(uuid.uuid4(), db)
    assert result["source"] == "none"
    assert result["balance"] == Decimal("0")


# ---------------------------------------------------------------------------
# calculate_cost
# ---------------------------------------------------------------------------


def _make_pricing(
    input_rate="0.002500",
    output_rate="0.010000",
    multiplier="1.2",
    minimum="0.01",
):
    p = MagicMock()
    p.cost_per_1k_input_tokens = Decimal(input_rate)
    p.cost_per_1k_output_tokens = Decimal(output_rate)
    p.platform_fee_multiplier = Decimal(multiplier)
    p.minimum_charge_credits = Decimal(minimum)
    return p


def test_calculate_cost_basic():
    db = _make_db()
    db.query.return_value.filter.return_value.first.return_value = _make_pricing()
    result = calculate_cost("vision", 1000, 1000, db)
    raw = Decimal("0.002500") + Decimal("0.010000")
    total = raw * Decimal("1.2")
    credits = (total * CREDITS_PER_USD).quantize(Decimal("0.000001"))
    assert result["raw_cost_usd"] == raw
    assert result["total_cost_usd"] == total
    assert result["credits_charged"] == credits


def test_calculate_cost_minimum_enforced():
    db = _make_db()
    pricing = _make_pricing(
        input_rate="0.000001", output_rate="0.000001", minimum="5.0"
    )
    db.query.return_value.filter.return_value.first.return_value = pricing
    result = calculate_cost("chat", 1, 1, db)
    assert result["credits_charged"] == Decimal("5.0")


def test_calculate_cost_no_pricing_config_raises():
    db = _make_db()
    db.query.return_value.filter.return_value.first.return_value = None
    with pytest.raises(HTTPException) as exc_info:
        calculate_cost("unknown_op", 100, 100, db)
    assert exc_info.value.status_code == 500


# ---------------------------------------------------------------------------
# charge_usage
# ---------------------------------------------------------------------------


def _setup_charge_db(balance: Decimal, source: str = "purchased"):
    db = _make_db()
    with patch("app.services.billing_service.get_active_balance") as mock_bal, patch(
        "app.services.billing_service.calculate_cost"
    ) as mock_cost:
        mock_bal.return_value = {
            "source": source,
            "balance": balance,
            "access_code_id": None,
            "access_code": None,
            "issued_by": None,
        }
        cost = Decimal("0.5")
        mock_cost.return_value = {
            "raw_cost_usd": Decimal("0.4"),
            "platform_fee_usd": Decimal("0.1"),
            "total_cost_usd": Decimal("0.5"),
            "credits_charged": cost,
        }
        yield db, mock_bal, mock_cost


def test_charge_usage_raises_402_on_no_balance():
    db = _make_db()
    with patch("app.services.billing_service.get_active_balance") as mock_bal:
        mock_bal.return_value = {
            "source": "none",
            "balance": Decimal("0"),
            "access_code_id": None,
            "access_code": None,
            "issued_by": None,
        }
        with pytest.raises(HTTPException) as exc_info:
            charge_usage(uuid.uuid4(), "vision", 100, 100, db)
    assert exc_info.value.status_code == 402


def test_charge_usage_raises_402_on_insufficient_credits():
    db = _make_db()
    with patch("app.services.billing_service.get_active_balance") as mock_bal, patch(
        "app.services.billing_service.calculate_cost"
    ) as mock_cost:
        mock_bal.return_value = {
            "source": "purchased",
            "balance": Decimal("0.1"),
            "access_code_id": None,
            "access_code": None,
            "issued_by": None,
        }
        mock_cost.return_value = {
            "raw_cost_usd": Decimal("0.4"),
            "platform_fee_usd": Decimal("0.1"),
            "total_cost_usd": Decimal("0.5"),
            "credits_charged": Decimal("50"),
        }
        with pytest.raises(HTTPException) as exc_info:
            charge_usage(uuid.uuid4(), "vision", 100, 100, db)
    assert exc_info.value.status_code == 402


# ---------------------------------------------------------------------------
# charge_usage idempotency (dual voice pipeline billing)
# ---------------------------------------------------------------------------


def test_charge_usage_returns_existing_record_for_known_idempotency_key():
    """If a UsageRecord with this (user_id, idempotency_key) already exists,
    charge_usage must short-circuit before touching the balance at all."""
    db = _make_db()
    existing_record = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = existing_record

    with patch("app.services.billing_service.get_active_balance") as mock_bal:
        result = charge_usage(
            uuid.uuid4(), "tts_elevenlabs", 500, 0, db, idempotency_key="key-123"
        )

    assert result is existing_record
    mock_bal.assert_not_called()  # never re-evaluated balance/cost for a duplicate


def test_charge_usage_charges_once_for_new_idempotency_key():
    db = _make_db()
    # Idempotency lookup (db.query(UsageRecord).filter(...).first(), no
    # with_for_update()) finds nothing — a fresh charge.
    db.query.return_value.filter.return_value.first.return_value = None
    # get_active_balance is mocked below, but charge_usage's own balance
    # deduction still does a real db.query(CreditBalance)...with_for_update()
    # .first() call — give it a real Decimal to subtract from.
    credit_balance = MagicMock()
    credit_balance.balance_credits = Decimal("100")
    db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = (
        credit_balance
    )

    with patch("app.services.billing_service.get_active_balance") as mock_bal, patch(
        "app.services.billing_service.calculate_cost"
    ) as mock_cost:
        mock_bal.return_value = {
            "source": "purchased",
            "balance": Decimal("100"),
            "access_code_id": None,
            "access_code": None,
            "issued_by": None,
        }
        mock_cost.return_value = {
            "raw_cost_usd": Decimal("0.09"),
            "platform_fee_usd": Decimal("0.018"),
            "total_cost_usd": Decimal("0.108"),
            "credits_charged": Decimal("10.8"),
        }
        record = charge_usage(
            uuid.uuid4(),
            "tts_elevenlabs",
            500,
            0,
            db,
            idempotency_key="key-456",
        )

    assert record.idempotency_key == "key-456"
    assert record.credits_charged == Decimal("10.8")
    db.commit.assert_called_once()


def test_charge_usage_handles_concurrent_duplicate_via_integrity_error():
    """Simulates two requests racing past the upfront idempotency check —
    the DB unique constraint on idempotency_key catches the second insert,
    which must roll back and return the record the first request committed."""
    db = _make_db()
    winner_record = MagicMock()

    call_count = {"n": 0}

    def _first_side_effect(*args, **kwargs):
        call_count["n"] += 1
        # 1st call: idempotency-key lookup before insert -> None (not yet raced)
        # 2nd call: idempotency-key lookup after IntegrityError -> winner record
        return None if call_count["n"] == 1 else winner_record

    db.query.return_value.filter.return_value.first.side_effect = _first_side_effect
    credit_balance = MagicMock()
    credit_balance.balance_credits = Decimal("100")
    db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = (
        credit_balance
    )
    db.commit.side_effect = IntegrityError("stmt", "params", "orig")

    with patch("app.services.billing_service.get_active_balance") as mock_bal, patch(
        "app.services.billing_service.calculate_cost"
    ) as mock_cost:
        mock_bal.return_value = {
            "source": "purchased",
            "balance": Decimal("100"),
            "access_code_id": None,
            "access_code": None,
            "issued_by": None,
        }
        mock_cost.return_value = {
            "raw_cost_usd": Decimal("0.09"),
            "platform_fee_usd": Decimal("0.018"),
            "total_cost_usd": Decimal("0.108"),
            "credits_charged": Decimal("10.8"),
        }
        result = charge_usage(
            uuid.uuid4(), "tts_elevenlabs", 500, 0, db, idempotency_key="key-race"
        )

    assert result is winner_record
    db.rollback.assert_called_once()
