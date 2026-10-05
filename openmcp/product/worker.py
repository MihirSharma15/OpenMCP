"""Durable single-treasury worker; safe to run multiple processes (one obtains lock)."""

import asyncio
import logging

from .models import ProductError
from .settlement import TerminalFailure

log = logging.getLogger(__name__)


class Worker:
    def __init__(self, settings, store, stripe, treasury=None):
        self.settings, self.store, self.stripe, self.treasury = settings, store, stripe, treasury

    async def execution(self, row, lock):
        try:
            await self.treasury.purchase(row, lock)
        except TerminalFailure as exc:
            current = self.store.execution_internal(row["execution_id"])
            if current["payment_status"] != "signed" or exc.reverted:
                self.store.finish(
                    row["execution_id"], refund_reason=str(exc), payment_reverted=exc.reverted
                )
            else:
                self.store.needs_review(
                    row["execution_id"],
                    "A signed payment needs reconciliation before credits can be returned.",
                )
        except Exception as exc:
            # Never log authorization headers, request payloads, signer keys, or
            # raw HTTP errors. Error categories and execution IDs are enough.
            if isinstance(exc, ProductError) and exc.code == "worker_lease_lost":
                raise
            self.treasury.ensure_lock(lock)
            current = self.store.execution_internal(row["execution_id"])
            if current["status"] in {"completed", "refunded"}:
                return
            log.warning(
                "Execution retry execution_id=%s error=%s", row["execution_id"], type(exc).__name__
            )
            if (
                current["attempts"] + 1 >= self.settings.max_attempts
                and current["payment_status"] != "signed"
            ):
                self.store.finish(
                    row["execution_id"],
                    refund_reason="Service could not deliver a result within its retry window. Credits returned.",
                )
            else:
                self.store.retry_execution(
                    row["execution_id"],
                    "Provider payment or result is pending reconciliation.",
                    self.settings.retry_seconds,
                    self.settings.max_attempts,
                )

    async def tick(self):
        with self.store.worker_lock() as lock:
            if lock is None:
                return False
            self.store.heartbeat()
            for event in self.store.pending_events():
                try:
                    await self.stripe.process_event(event)
                    self.store.event_done(event["id"])
                except Exception as exc:
                    code = exc.code if isinstance(exc, ProductError) else type(exc).__name__
                    self.store.event_retry(event["id"], code, self.settings.retry_seconds)
                    log.warning(
                        "Stripe reconciliation retry event_id=%s error=%s", event["id"], code
                    )
                self.store.heartbeat()
            if self.treasury:
                for row in self.store.pending_executions():
                    await self.execution(row, lock)
                    self.store.heartbeat()
            return True

    async def run(self):
        while True:
            await self.tick()
            await asyncio.sleep(self.settings.worker_interval)
