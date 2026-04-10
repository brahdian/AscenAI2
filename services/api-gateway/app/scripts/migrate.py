"""
Migration bootstrap — run before `alembic upgrade head`.

Handles the case where the database schema was created outside of Alembic
(via Base.metadata.create_all or seed scripts). If no alembic_version table
exists, the DB is stamped at the last migration that pre-dates Alembic being
wired into the startup, so `upgrade head` only runs genuinely new migrations.
"""
from __future__ import annotations

import asyncio
import subprocess
import sys

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine


async def _get_db_state(url: str) -> str:
    """
    Returns:
      'fresh'    — no tables at all (brand new DB)
      'legacy'   — tables exist but no alembic_version (pre-Alembic deployment)
      'managed'  — alembic_version table exists (already tracked)
    """
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            # Check for alembic_version table
            av = await conn.execute(sa.text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_name = 'alembic_version' LIMIT 1"
            ))
            if av.fetchone():
                return "managed"

            # Check if any app tables exist
            tables = await conn.execute(sa.text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = 'tenants' LIMIT 1"
            ))
            if tables.fetchone():
                return "legacy"

            return "fresh"
    except Exception:
        return "fresh"
    finally:
        await engine.dispose()


def main() -> None:
    from app.core.config import settings

    state = asyncio.run(_get_db_state(settings.DATABASE_URL))

    if state == "fresh":
        # Brand new DB — run all migrations from 0001
        print("[migrate] Fresh database — running all migrations from scratch.")
    elif state == "legacy":
        # Tables exist but created outside Alembic — stamp at 0007 baseline
        print("[migrate] Legacy database detected — stamping at 0007 baseline.")
        result = subprocess.run(["alembic", "stamp", "0007"])
        if result.returncode != 0:
            sys.exit(result.returncode)
    else:
        print("[migrate] Alembic already tracking migrations — skipping stamp.")

    print("[migrate] Running alembic upgrade head.")
    result = subprocess.run(["alembic", "upgrade", "head"])
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
