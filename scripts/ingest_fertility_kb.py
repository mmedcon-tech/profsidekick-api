"""Index knowledge/ivf_doctor_twin_kb.md into fertility_knowledge_chunks.

Usage (inside the backend container):  python -m scripts.ingest_fertility_kb
"""

from app.database.connection import SessionLocal
from app.services.fertility.knowledge import ingest_kb

if __name__ == "__main__":
    db = SessionLocal()
    try:
        print(ingest_kb(db))
    finally:
        db.close()
