"""
Integration tests for billing API routes.

Uses the shared Postgres test database and fixtures from tests/conftest.py
(db_session, test_user, client). It used to build its own SQLite database,
which cannot render the models' UUID columns. Each test makes its own access
code, because committed rows are shared across the test session.
"""

import uuid
from decimal import Decimal

import pytest

from app.database.models import (
    AccessCode,
    CreditBalance,
    PricingConfig,
)


@pytest.fixture
def db(db_session):
    return db_session


@pytest.fixture
def code():
    return f"TEST-{uuid.uuid4().hex[:12].upper()}"


def _seed_pricing(db):
    for op_type, in_rate, out_rate, multiplier, minimum in [
        ("vision", "0.002500", "0.010000", "1.2", "0.01"),
        ("chat", "0.000150", "0.000600", "1.2", "0.001"),
        ("realtime_token", "0.000000", "0.000000", "1.0", "0.5"),
    ]:
        db.add(
            PricingConfig(
                id=uuid.uuid4(),
                operation_type=op_type,
                cost_per_1k_input_tokens=Decimal(in_rate),
                cost_per_1k_output_tokens=Decimal(out_rate),
                platform_fee_multiplier=Decimal(multiplier),
                minimum_charge_credits=Decimal(minimum),
            )
        )
    db.commit()


def _add_balance(db, user_id, credits: Decimal):
    cb = CreditBalance(
        id=uuid.uuid4(),
        user_id=user_id,
        balance_credits=credits,
    )
    db.add(cb)
    db.commit()


def _make_access_code(db, credits: Decimal, code: str) -> AccessCode:
    ac = AccessCode(
        id=uuid.uuid4(),
        code=code,
        total_credits=credits,
        remaining_credits=credits,
        issued_by="pytest",
        max_redemptions=5,
        redemptions_used=0,
        is_active=True,
    )
    db.add(ac)
    db.commit()
    db.refresh(ac)
    return ac


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGetBalance:
    def test_no_balance(self, client):
        resp = client.get("/api/billing/balance")
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "none"
        assert float(data["balance"]) == 0.0

    def test_purchased_balance(self, client, db, test_user):
        _add_balance(db, test_user.id, Decimal("42.5"))
        resp = client.get("/api/billing/balance")
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "purchased"
        assert float(data["balance"]) == pytest.approx(42.5)


class TestRedeemCode:
    def test_redeem_valid_code(self, client, db, test_user, code):
        _make_access_code(db, Decimal("100"), code)
        resp = client.post("/api/billing/redeem", json={"code": code})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["code"] == code

    def test_redeem_nonexistent_code(self, client):
        resp = client.post("/api/billing/redeem", json={"code": "FAKE-CODE-0000"})
        assert resp.status_code == 404

    def test_redeem_same_code_twice(self, client, db, test_user, code):
        _make_access_code(db, Decimal("100"), code)
        client.post("/api/billing/redeem", json={"code": code})
        resp = client.post("/api/billing/redeem", json={"code": code})
        assert resp.status_code == 400

    def test_redeem_inactive_code(self, client, db, code):
        ac = _make_access_code(db, Decimal("100"), code)
        ac.is_active = False
        db.commit()
        resp = client.post("/api/billing/redeem", json={"code": code})
        assert resp.status_code == 400


class TestAddCredits:
    def test_add_credits(self, client, db, test_user):
        resp = client.post("/api/billing/add-credits", json={"amount_usd": "10.00"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert float(data["new_balance"]) == pytest.approx(
            float(Decimal("10.00") * Decimal("100"))
        )

    def test_add_credits_zero_rejected(self, client):
        resp = client.post("/api/billing/add-credits", json={"amount_usd": "0"})
        assert resp.status_code == 422


class TestUsageHistory:
    def test_empty_history(self, client):
        resp = client.get("/api/billing/usage")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["records"] == []

    def test_pagination_params(self, client):
        resp = client.get("/api/billing/usage?page=2&limit=5")
        assert resp.status_code == 200
        data = resp.json()
        assert data["pagination"]["page"] == 2
        assert data["pagination"]["limit"] == 5
