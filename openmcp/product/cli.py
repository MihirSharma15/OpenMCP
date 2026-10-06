"""Operator-only commands. No administrative mutation routes are exposed publicly."""

import argparse
import asyncio
import json
import logging
import os

from openmcp.database import DatabaseManager

from .config import ProductSettings, Service
from .models import ProductError
from .settlement import TerminalFailure, Treasury
from .store import Store
from .stripe import StripeGateway
from .worker import Worker


async def run(args):
    settings = ProductSettings()
    if args.command == "migrate":
        from .migrate import migrate

        # Privileged DSN is read only by the explicit deployment command.
        dsn = os.environ.get("OPENMCP_PRODUCT_MIGRATION_DATABASE_URL") or settings.database_url
        DatabaseManager.validate_dsn(dsn, settings.database_provider)
        migrate(dsn, settings.database_schema)
        print("Account database migrated.")
        return
    settings.validate_database()
    store = Store(DatabaseManager.from_settings(settings))
    try:
        store.database.check_schema_version()
        if args.command == "database-check":
            print(
                json.dumps(
                    {
                        "status": "ready",
                        "provider": settings.database_provider,
                        "schema": settings.database_schema,
                        **store.health(),
                    }
                )
            )
            return
        # A worker with no MPP services or unfinished MPP payments can process
        # Stripe events without a signer. The database decides below.
        settings.validate_startup(require_treasury_key=args.command != "worker")
        store.bind_runtime(settings)
        store.sync_catalog(settings.catalog())
        await run_with_store(args, settings, store)
    finally:
        store.close()


async def run_with_store(args, settings, store):
    if args.command == "review":
        print(json.dumps(store.review(), default=str))
        return
    if args.command == "doctor":
        report = {
            "mode": settings.mode,
            "services": store.service_count(settings.mode),
            **store.health(),
        }
        if args.chain:
            treasury = Treasury(settings, store)
            try:
                report["treasury_balance_units"] = await treasury.network_and_balance()
                report["treasury_address"] = treasury.account.address
                report["chain_id"] = settings.chain_id
            finally:
                await treasury.close()
        print(json.dumps(report))
        return
    if args.command == "enable-service":
        store.enable_service(args.endpoint_id)
        print(json.dumps({"endpoint_id": args.endpoint_id, "enabled": True}))
        return
    stripe = StripeGateway(settings, store)
    treasury = None
    worker = None
    try:
        if args.command != "worker" or store.requires_treasury(settings.mode):
            treasury = Treasury(settings, store)
        worker = Worker(settings, store, stripe, treasury)
        if args.command == "worker":
            if args.once:
                await worker.tick()
            else:
                await worker.run()
        else:
            with store.worker_lock() as lock:
                if lock is None:
                    raise ProductError(
                        "worker_busy", "Stop the active worker before operator reconciliation.", 409
                    )
                row = store.execution_internal(args.execution_id)
                if not row:
                    raise ProductError("not_found", "Execution not found.", 404)
                if args.refund:
                    if not args.reason:
                        raise ProductError(
                            "reason_required", "Operator refunds require --reason.", 422
                        )
                    reverted = False
                    if row["payment_status"] == "signed":
                        try:
                            receipt = await treasury.confirmation(
                                row, Service.model_validate(row["service"])
                            )
                            if not receipt:
                                raise ProductError(
                                    "payment_ambiguous",
                                    "Signed payment is unconfirmed; reservation retained.",
                                    409,
                                )
                            store.mark_paid(row["execution_id"], receipt)
                        except TerminalFailure as exc:
                            if not exc.reverted:
                                raise
                            reverted = True
                    row = store.finish(
                        row["execution_id"],
                        refund_reason="Operator confirmed fulfillment failure: "
                        + args.reason[:300],
                        payment_reverted=reverted,
                    )
                else:
                    if row["status"] == "needs_review":
                        row = store.requeue(row["execution_id"])
                    if row["status"] not in {"completed", "refunded"}:
                        await worker.execution(row, lock)
                    row = store.execution_internal(row["execution_id"])
                print(json.dumps(store.execution_public(row), default=str))
    finally:
        await stripe.close()
        if treasury:
            await treasury.close()
        if worker and worker.api_caller:
            await worker.api_caller.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate")
    sub.add_parser("database-check")
    sub.add_parser("review")
    worker = sub.add_parser("worker")
    worker.add_argument("--once", action="store_true")
    doctor = sub.add_parser("doctor")
    doctor.add_argument("--chain", action="store_true")
    enable = sub.add_parser("enable-service", help="Re-enable a service after operator review")
    enable.add_argument("--endpoint-id", required=True)
    reconcile = sub.add_parser("reconcile")
    reconcile.add_argument("--execution-id", required=True)
    reconcile.add_argument(
        "--refund", action="store_true", help="Return credits only after payment outcome is known"
    )
    reconcile.add_argument("--reason")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(run(args))
    except (ProductError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
