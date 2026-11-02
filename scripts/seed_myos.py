"""Seed MYOS sample content (idempotent). Usage: python -m scripts.seed_myos [--cleanup]"""
import json
import sys

from app.database.connection import SessionLocal
from app.services.care import seed_myos

if __name__ == "__main__":
    db = SessionLocal()
    try:
        print(json.dumps(seed_myos.seed(db)))
        if "--cleanup" in sys.argv:
            print(json.dumps(seed_myos.cleanup(db)))
    finally:
        db.close()
