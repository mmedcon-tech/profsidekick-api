"""
Move knowledge and reference files saved under the public /uploads mount into
private storage (ADR 0010).

Usage:
    python -m scripts.migrate_legacy_files                      # dry run
    python -m scripts.migrate_legacy_files --apply              # move, keep originals
    python -m scripts.migrate_legacy_files --apply --delete-originals
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
    parser.add_argument("--delete-originals", action="store_true")
    args = parser.parse_args()
    if args.delete_originals and not args.apply:
        parser.error("--delete-originals needs --apply")

    from app.services.legacy_files import migrate_legacy_files
    from app.services.private_storage import get_private_storage

    db = sessionmaker(bind=create_engine(os.environ["DATABASE_URL"]))()
    try:
        report = migrate_legacy_files(
            db,
            get_private_storage(),
            apply=args.apply,
            delete_originals=args.delete_originals,
        )
    finally:
        db.close()

    print(f"moved: {len(report.moved)}")
    print(f"would move (dry run): {len(report.would_move)}")
    for line in report.skipped:
        print(f"skipped: {line}")


if __name__ == "__main__":
    main()
