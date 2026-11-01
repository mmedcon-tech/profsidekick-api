"""
Index avatar knowledge documents that have no retrievable chunks yet.

Usage:
    python -m scripts.index_knowledge            # dry run: list what would be indexed
    python -m scripts.index_knowledge --apply    # index them (calls the embeddings API)
    python -m scripts.index_knowledge --embed-missing [--apply]
        # also add embeddings to chunks stored without one (e.g. indexed while
        # OPENAI_API_KEY was missing), so meaning-based search can find them
"""

import argparse
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--embed-missing", action="store_true")
    args = parser.parse_args()

    from app.services.knowledge_indexing import embed_missing, index_unindexed

    db = sessionmaker(bind=create_engine(os.environ["DATABASE_URL"]))()
    try:
        report = index_unindexed(db, apply=args.apply)
        missing = embed_missing(db, apply=args.apply) if args.embed_missing else None
    finally:
        db.close()
    print(f"indexed: {len(report.indexed)}")
    for line in report.would_index:
        print(f"would index: {line}")
    for line in report.skipped:
        print(f"skipped: {line}")
    if missing is not None:
        verb = "embedded" if args.apply else "chunks without an embedding"
        print(f"{verb}: {missing}")


if __name__ == "__main__":
    main()
