"""Explicit deployment migrations; runtime roles never need schema ownership."""

import re
from pathlib import Path

import psycopg


def migration_files():
    source = Path(__file__).resolve().parents[2] / "supabase/migrations"
    # Wheels contain these exact source files via hatch force-include.
    return sorted(
        (source if source.is_dir() else Path(__file__).parent / "migrations").glob("*.sql")
    )


def migration_sql(schema="openmcp_product"):
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,49}", schema):
        raise ValueError("Migration schema must be a safe identifier of at most 50 characters")
    files = migration_files()
    if not files:
        raise RuntimeError("Packaged account migrations are missing")
    return "\n".join(p.read_text() for p in files).replace("openmcp_product", schema)


def migrate(dsn, schema="openmcp_product"):
    with psycopg.connect(dsn, connect_timeout=10, prepare_threshold=None) as connection:
        connection.execute("SELECT pg_advisory_xact_lock(68193421)")
        connection.execute(migration_sql(schema))
