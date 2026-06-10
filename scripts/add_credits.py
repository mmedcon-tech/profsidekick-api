import os
import sys

# Add the root backend directory to the sys path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database.connection import SessionLocal
from app.database.models import User, CreditBalance

def add_credits_to_subscribers():
    db = SessionLocal()
    try:
        # Find all subscribers
        subscribers = db.query(User).filter(User.role == "subscriber").all()
        
        count = 0
        for subscriber in subscribers:
            # Check if they have a wallet/credit balance
            wallet = db.query(CreditBalance).filter(CreditBalance.user_id == subscriber.id).first()
            if not wallet:
                wallet = CreditBalance(user_id=subscriber.id, balance_credits=0)
                db.add(wallet)
            
            # Add 1000 credits
            wallet.balance_credits += 1000
            count += 1
            
        db.commit()
        print(f"Successfully added 1000 credits to {count} subscribers.")
    except Exception as e:
        db.rollback()
        print(f"Error adding credits: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    add_credits_to_subscribers()
