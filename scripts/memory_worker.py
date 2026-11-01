"""Run `python -m scripts.memory_worker`; use --once for a single queue drain.

Run one or more dedicated worker processes alongside the API. Jobs are stored
in Postgres; SKIP LOCKED permits concurrent workers and crash-safe retries.
"""

import argparse
import asyncio

from app.database.connection import SessionLocal
from app.services.memory_service import process_job, purge_expired


async def main(once: bool) -> None:
    while True:
        with SessionLocal() as db:
            purge_expired(db)
            db.commit()
        while await process_job():
            pass
        if once:
            return
        await asyncio.sleep(10)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    asyncio.run(main(parser.parse_args().once))
