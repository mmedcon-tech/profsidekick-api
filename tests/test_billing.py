"""
Integration tests for billing API routes.

Uses PostgreSQL database from environment (DATABASE_URL) and overrides FastAPI
dependencies so no real OpenAI calls are made.
"""

import uuid
from decimal import Decimal
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.connection import Base, get_db
from app.database.models import (
    AccessCode,
    CreditBalance,
    PricingConfig,
    User,
)
from app.dependencies.auth import get_current_user
from app.main import app

# ---------------------------------------------------------------------------
# PostgreSQL test DB (uses DATABASE_URL from environment or fallback)
# ---------------------------------------------------------------------------

TEST_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:1234@localhost:5432/postgres",
)

engine = create_engine(TEST_DATABASE_URL)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_BILLING_TABLES = [
    "users",
    "credit_balances",
    "access_codes",
    "access_code_redemptions",
    "usage_records",
    "pricing_configs",
]


@pytest.fixture(autouse=True)
def setup_tables():
    tables = [Base.metadata.tables[t] for t in _BILLING_TABLES if t in Base.metadata.tables]
    Base.metadata.create_all(bind=engine, tables=tables)
    yield
    Base.metadata.drop_all(bind=engine, tables=tables)


@pytest.fixture
def db():
    session = TestSessionLocal()
    yield session
    session.close()


@pytest.fixture
def test_user(db):
    user = User(
        id=uuid.uuid4(),
        username="testuser",
        email="test@example.com",
        password_hash="hashed",
        first_name="Test",
        last_name="User",
        role="teacher",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def client(test_user):
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: test_user
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


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


def _make_access_code(db, credits: Decimal, code: str = "TEST-CODE-0001") -> AccessCode:
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
    def test_redeem_valid_code(self, client, db, test_user):
        _make_access_code(db, Decimal("100"))
        resp = client.post("/api/billing/redeem", json={"code": "TEST-CODE-0001"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["code"] == "TEST-CODE-0001"

    def test_redeem_nonexistent_code(self, client):
        resp = client.post("/api/billing/redeem", json={"code": "FAKE-CODE-0000"})
        assert resp.status_code == 404

    def test_redeem_same_code_twice(self, client, db, test_user):
        _make_access_code(db, Decimal("100"))
        client.post("/api/billing/redeem", json={"code": "TEST-CODE-0001"})
        resp = client.post("/api/billing/redeem", json={"code": "TEST-CODE-0001"})
        assert resp.status_code == 400

    def test_redeem_inactive_code(self, client, db):
        ac = _make_access_code(db, Decimal("100"))
        ac.is_active = False
        db.commit()
        resp = client.post("/api/billing/redeem", json={"code": "TEST-CODE-0001"})
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
