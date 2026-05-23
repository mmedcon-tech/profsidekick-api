# clear_db_data.py

import sys
import os

# Add parent directory to path so we can import from app package
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.database.connection import engine

def truncate_all_tables():
    with engine.connect() as conn:
        conn.execute(text("""
            DO $$
            DECLARE
                r RECORD;
            BEGIN
                FOR r IN (SELECT tablename FROM pg_tables WHERE schemaname = 'public') LOOP
                    EXECUTE 'TRUNCATE TABLE ' || quote_ident(r.tablename) || ' RESTART IDENTITY CASCADE';
                END LOOP;
            END $$;
        """))
        print("✅ All tables truncated successfully.")

if __name__ == "__main__":
    truncate_all_tables()
