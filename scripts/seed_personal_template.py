"""
Seed the built-in "Personal avatar" template so creators can make an avatar
without an admin publishing a template first.

Usage:
    python -m scripts.seed_personal_template

Needs an admin user to own the template: ADMIN_EMAIL if set, otherwise the
oldest admin. Run scripts.seed_admin first on a fresh database (it also calls
this). Safe to run repeatedly.
"""

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))


def seed(db) -> bool:
    from app.database.models import User
    from app.services.personal_template import ensure_personal_template

    admin_email = os.getenv("ADMIN_EMAIL")
    query = db.query(User).filter(User.role == "admin")
    admin = None
    if admin_email:
        admin = query.filter(User.email == admin_email.lower()).first()
    if admin is None:
        admin = query.order_by(User.created_at.asc()).first()
    if admin is None:
        print("No admin user found. Run `python -m scripts.seed_admin` first.")
        return False

    template = ensure_personal_template(db, admin.id)
    print(
        f"Personal avatar template ready: {template.id} (active={template.is_active})"
    )
    return True


if __name__ == "__main__":
    engine = create_engine(os.environ["DATABASE_URL"])
    session = sessionmaker(bind=engine)()
    try:
        seed(session)
    finally:
        session.close()
