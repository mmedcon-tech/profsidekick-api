"""
Add credits to a user's balance.

Usage (from the backend-main directory):
    python -m scripts.add_credits --email user@example.com --credits 100
    python -m scripts.add_credits --email user@example.com --usd 10
    python -m scripts.add_credits --email user@example.com --credits 500 --reason "Course access grant"

In Docker:
    docker compose exec api python -m scripts.add_credits --email user@example.com --credits 100

Arguments:
    --email     Required. Email of the user to credit.
    --credits   Credits to add directly (e.g. 100).
    --usd       USD amount to convert to credits (uses CREDITS_PER_USD from config).
                Provide one of --credits or --usd, not both.
    --reason    Optional note logged with the operation (default: "manual_grant").
    --dry-run   Print what would happen without writing to the database.
"""

import argparse
import os
import sys
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.environ["DATABASE_URL"]
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)


def main() -> None:
    parser = argparse.ArgumentParser(description="Add credits to a user.")
    parser.add_argument("--email", required=True, help="User email")
    parser.add_argument("--credits", type=str, default=None, help="Credits to add directly")
    parser.add_argument("--usd", type=str, default=None, help="USD amount to convert to credits")
    parser.add_argument("--reason", default="manual_grant", help="Reason (logged in usage_records)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()

    if args.credits and args.usd:
        parser.error("Provide --credits OR --usd, not both.")
    if not args.credits and not args.usd:
        parser.error("Provide one of --credits or --usd.")

    from app.config import settings
    from app.database.models import CreditBalance, UsageRecord, User

    CREDITS_PER_USD = Decimal(str(settings.credits_per_usd))

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == args.email.lower().strip()).first()
        if not user:
            print(f"ERROR: No user found with email '{args.email}'")
            sys.exit(1)

        try:
            if args.usd:
                usd_amount = Decimal(args.usd)
                credits_to_add = (usd_amount * CREDITS_PER_USD).quantize(Decimal("0.000001"))
            else:
                credits_to_add = Decimal(args.credits).quantize(Decimal("0.000001"))
        except InvalidOperation:
            print("ERROR: Invalid numeric value for --credits or --usd")
            sys.exit(1)

        if credits_to_add <= 0:
            print("ERROR: Amount must be positive")
            sys.exit(1)

        credit_balance = db.query(CreditBalance).filter(CreditBalance.user_id == user.id).first()
        previous = Decimal(str(credit_balance.balance_credits)) if credit_balance else Decimal("0")
        new_balance = previous + credits_to_add

        print(f"User:           {user.email} ({user.first_name} {user.last_name})")
        print(f"Current balance: {previous:,.6f} credits")
        print(f"Adding:          {credits_to_add:,.6f} credits  (reason: {args.reason})")
        print(f"New balance:     {new_balance:,.6f} credits")

        if args.dry_run:
            print("\n[DRY RUN] No changes written.")
            return

        now = datetime.utcnow()
        if credit_balance:
            credit_balance.balance_credits = new_balance
            credit_balance.updated_at = now
        else:
            credit_balance = CreditBalance(
                id=uuid.uuid4(),
                user_id=user.id,
                balance_credits=new_balance,
                updated_at=now,
            )
            db.add(credit_balance)

        # Write an audit record so the grant appears in usage history
        record = UsageRecord(
            id=uuid.uuid4(),
            user_id=user.id,
            session_run_id=None,
            operation_type="admin_grant",
            input_tokens=0,
            output_tokens=0,
            raw_cost_usd=Decimal("0"),
            platform_fee_usd=Decimal("0"),
            total_cost_usd=Decimal("0"),
            credits_charged=credits_to_add,
            funded_by="admin",
            ai_provider="manual",
            access_code_id=None,
            created_at=now,
        )
        db.add(record)
        db.commit()

        print("\nDone. Credits added successfully.")
    except Exception as e:
        db.rollback()
        print(f"ERROR: {e}")
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
