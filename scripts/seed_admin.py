"""
Seed an admin user into the database.

Usage:
    python -m scripts.seed_admin

The script reads DATABASE_URL from .env (or environment). It skips creation if
a user with the same email already exists. After running, the admin can log in
via the normal /api/auth/login endpoint and use the X-Admin-Secret header for
admin billing endpoints.

Defaults (override with env vars):
    ADMIN_EMAIL     = admin@profsidekick.com
    ADMIN_USERNAME  = admin
    ADMIN_PASSWORD  = changeme123          ← change immediately after first login
    ADMIN_FIRST     = Admin
    ADMIN_LAST      = User
"""

import os
import uuid

import bcrypt
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

DATABASE_URL = os.environ["DATABASE_URL"]

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@profsidekick.com")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme123")
ADMIN_FIRST = os.getenv("ADMIN_FIRST", "Admin")
ADMIN_LAST = os.getenv("ADMIN_LAST", "User")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def seed():
    from app.database.models import CreditBalance, User

    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == ADMIN_EMAIL.lower()).first()
        if existing:
            print(f"Admin user '{ADMIN_EMAIL}' already exists — skipping.")
            return

        admin_id = uuid.uuid4()
        admin = User(
            id=admin_id,
            username=ADMIN_USERNAME,
            email=ADMIN_EMAIL.lower(),
            password_hash=hash_password(ADMIN_PASSWORD),
            first_name=ADMIN_FIRST,
            last_name=ADMIN_LAST,
            role="admin",
            email_verified=True,
            is_approved=True,
        )
        db.add(admin)

        balance = CreditBalance(
            id=uuid.uuid4(),
            user_id=admin_id,
            balance_credits=0,
        )
        db.add(balance)

        db.commit()
        print(f"Admin user created:")
        print(f"  email:    {ADMIN_EMAIL}")
        print(f"  username: {ADMIN_USERNAME}")
        print(f"  password: {ADMIN_PASSWORD}")
        print()
        print("IMPORTANT: change the password immediately after first login.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
