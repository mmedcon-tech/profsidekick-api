# check_schema.py

from sqlalchemy import create_engine, inspect, text
from dotenv import load_dotenv
import os

print("PID:", os.getpid())

load_dotenv()

url = os.getenv("DATABASE_URL")

print("=" * 80)
print("DATABASE URL:", url)
print("=" * 80)

engine = create_engine(url)

with engine.connect() as conn:

    db = conn.execute(text("SELECT current_database()")).scalar()
    schema = conn.execute(text("SELECT current_schema()")).scalar()

    print("Database:", db)
    print("Schema:", schema)

    insp = inspect(conn)

    tables_to_check = [
        "sessions",
        "courses",
        "autograder_submissions",
    ]

    print("\nAll tables:")
    print(sorted(insp.get_table_names()))

    for table in tables_to_check:

        print("\n" + "=" * 80)
        print(f"TABLE: {table}")
        print("=" * 80)

        if table not in insp.get_table_names():
            print("❌ TABLE DOES NOT EXIST")
            continue

        cols = insp.get_columns(table)

        print(f"{len(cols)} columns:")

        for c in cols:
            print(
                f"- {c['name']:35}"
                f"{str(c['type']):20}"
                f"nullable={c['nullable']}"
            )