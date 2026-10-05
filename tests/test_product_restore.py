"""Opt-in real pg_dump/pg_restore and fresh-process recovery using synthetic funds.

OPENMCP_TEST_RESTORE=1 enables this operational acceptance test. It dumps only a
unique test schema and restores into a freshly created test database, never into
an existing product database. No provider, Stripe account, or signer is contacted.
Requires CREATEDB and either pg_dump/pg_restore or the local compose Postgres.
"""

import os
import shutil
import subprocess
import sys
import uuid

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from openmcp.product.config import ProductSettings
from openmcp.product.models import Principal
from openmcp.product.store import Store
from tests.test_product_postgres import credit, grant, purchase
from tests.test_product_postgres import postgres_url as postgres_url
from tests.test_product_postgres import service as service
from tests.test_product_postgres import store as store

pytestmark = pytest.mark.skipif(
    os.environ.get("OPENMCP_TEST_RESTORE") != "1",
    reason="Set OPENMCP_TEST_RESTORE=1 for isolated PostgreSQL dump/restore acceptance",
)


def postgres_cli(name, dsn, *args, input=None):
    parts = conninfo_to_dict(dsn)
    binary = shutil.which(name)
    environment = os.environ.copy()
    client_container = os.environ.get("OPENMCP_TEST_POSTGRES_CLIENT_CONTAINER")
    if binary or client_container:
        command = [binary, "--no-password", "--dbname", parts["dbname"]]
        for field, variable in (
            ("host", "PGHOST"),
            ("port", "PGPORT"),
            ("user", "PGUSER"),
            ("password", "PGPASSWORD"),
            ("sslmode", "PGSSLMODE"),
            ("sslrootcert", "PGSSLROOTCERT"),
        ):
            if field in parts:
                environment[variable] = parts[field]
        if client_container:
            # Explicit test container only: connection secrets travel through
            # the child environment, never command arguments or logs.
            if not client_container.startswith("openmcp-verification-"):
                pytest.fail("Use a dedicated openmcp-verification-* client container")
            if environment.get("PGHOST") in {"localhost", "127.0.0.1"}:
                environment["PGHOST"], environment["PGPORT"] = "127.0.0.1", "5432"
            if parts.get("sslrootcert"):
                environment["PGSSLROOTCERT"] = "/tmp/supabase-ca.crt"
            command = ["docker", "exec", "-i"]
            for variable in [
                "PGHOST",
                "PGPORT",
                "PGUSER",
                "PGPASSWORD",
                "PGSSLMODE",
                "PGSSLROOTCERT",
            ]:
                if variable in environment:
                    command += ["-e", variable]
            command += [client_container, name, "--no-password", "--dbname", parts["dbname"]]
    else:
        if not shutil.which("docker"):
            pytest.fail("Restore acceptance requires pg_dump/pg_restore or Docker compose")
        # The fallback is deliberately confined to the repository's local service.
        if (
            parts.get("host") not in {"127.0.0.1", "localhost"}
            or parts.get("port", "5432") != "5433"
        ):
            pytest.fail(
                "Docker CLI fallback only supports the local compose database at localhost:5433"
            )
        command = [
            "docker",
            "compose",
            "exec",
            "-T",
            "postgres",
            name,
            "--no-password",
            "--username",
            parts.get("user", "openmcp"),
            "--dbname",
            parts["dbname"],
        ]
    result = subprocess.run(
        command + list(args), input=input, capture_output=True, env=environment, timeout=180
    )
    assert result.returncode == 0, f"{name} failed: {result.stderr.decode(errors='replace')}"
    return result.stdout


def test_isolated_backup_restore_recovers_signed_and_reserved_work_in_fresh_process(
    store, service, tmp_path, postgres_url
):
    settings = ProductSettings(
        _env_file=None,
        mode="test",
        chain_id=42431,
        token="0x20c0000000000000000000000000000000000000",
    )
    store.bind_runtime(settings)
    owner = store.bootstrap("synthetic-backup-test")["account_id"]
    credit(store, owner, 1000)
    principal, _ = grant(store, owner, 200)
    signed = store.reserve(principal, "signed-before-crash", purchase(service), service)
    reserved = store.reserve(principal, "reserved-before-crash", purchase(service), service)
    store.mark_signed(
        signed["execution_id"],
        "synthetic-non-executable-credential",
        "synthetic-challenge",
        "Authorization",
        "0xsynthetic",
    )
    store.accept_event(
        {
            "id": "evt_synthetic",
            "type": "synthetic.restore",
            "created": 1,
            "data": {"object": {"id": "obj_synthetic"}},
        }
    )
    backup = postgres_cli(
        "pg_dump",
        postgres_url,
        "--format=custom",
        "--no-owner",
        "--no-acl",
        "--schema",
        store.schema,
    )
    artifact = tmp_path / "synthetic-product.dump"
    descriptor = os.open(artifact, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(backup)
    restored_database = "product_restore_" + uuid.uuid4().hex
    restore_admin = os.environ.get("OPENMCP_TEST_RESTORE_TARGET_DATABASE_URL", postgres_url)
    parts = conninfo_to_dict(restore_admin)
    restored_dsn = make_conninfo(**(parts | {"dbname": restored_database}))
    created = False
    created_role = False
    restored = None
    try:
        with psycopg.connect(restore_admin, autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(restored_database)))
            created = True
            # Policies in a schema-only dump refer to its restricted privilege role.
            if not admin.execute(
                "SELECT 1 FROM pg_roles WHERE rolname=%s", (store.schema + "_runtime",)
            ).fetchone():
                admin.execute(
                    sql.SQL("CREATE ROLE {} NOLOGIN").format(
                        sql.Identifier(store.schema + "_runtime")
                    )
                )
                created_role = True
        postgres_cli(
            "pg_restore", restored_dsn, "--exit-on-error", "--no-owner", "--no-acl", input=backup
        )
        restored = Store(restored_dsn, store.schema)
        restored.migrate()
        restored.bind_runtime(settings)
        assert restored.wallet(principal)["reserved_cents"] == 80
        assert (
            restored.execution_internal(signed["execution_id"])["payment_authorization"]
            == "synthetic-non-executable-credential"
        )
        assert len(restored.pending_events()) == 1
        code = """
import asyncio, os
from openmcp.product.config import ProductSettings
from openmcp.product.store import Store
from openmcp.product.worker import Worker
from openmcp.product.settlement import TerminalFailure
store = Store(os.environ["OPENMCP_TEST_RECOVERY_DSN"], os.environ["OPENMCP_TEST_RECOVERY_SCHEMA"])
settings = ProductSettings(_env_file=None, mode="test", chain_id=42431, token="0x20c0000000000000000000000000000000000000")
store.bind_runtime(settings)
class SyntheticStripe:
    async def process_event(self, event):
        assert event["type"] == "synthetic.restore"
class SyntheticProvider:
    @staticmethod
    def ensure_lock(lock):
        lock.assert_held()
    async def purchase(self, row, lock):
        if row["payment_authorization"] is None:
            raise TerminalFailure("Synthetic provider refused before signing")
        assert row["payment_authorization"] == "synthetic-non-executable-credential"
        store.mark_paid(row["execution_id"], {"reference": "synthetic-restored-receipt"})
        store.finish(row["execution_id"], data={"answer": "synthetic restored result"})
asyncio.run(Worker(settings, store, SyntheticStripe(), SyntheticProvider()).tick())
"""
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=30,
            env=os.environ
            | {
                "OPENMCP_TEST_RECOVERY_DSN": restored_dsn,
                "OPENMCP_TEST_RECOVERY_SCHEMA": store.schema,
            },
        )
        assert result.returncode == 0, result.stderr
        wallet = restored.wallet(principal)
        assert (
            wallet["balance_cents"],
            wallet["reserved_cents"],
            wallet["agent"]["spent_cents"],
        ) == (960, 0, 40)
        assert restored.execution_internal(signed["execution_id"])["status"] == "completed"
        assert restored.execution_internal(reserved["execution_id"])["status"] == "refunded"
        assert restored.pending_events() == []
        # Restoration/recovery never mutated the source schema.
        assert store.wallet(Principal(owner))["balance_cents"] == 1000
        assert store.wallet(Principal(owner))["reserved_cents"] == 80
        assert store.execution_internal(signed["execution_id"])["status"] == "payment_pending"
    finally:
        if restored:
            restored.close()
        if created:
            with psycopg.connect(restore_admin, autocommit=True) as admin:
                admin.execute(
                    sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                        sql.Identifier(restored_database)
                    )
                )
                if created_role:
                    admin.execute(
                        sql.SQL("DROP ROLE {}").format(sql.Identifier(store.schema + "_runtime"))
                    )
