"""Durable single-treasury worker; safe to run multiple processes (one obtains lock)."""

import asyncio
import logging

from .api_call import ApiKeyCaller
from .models import ProductError
from .policy import Action, settlement_outcome
from .settlement import TerminalFailure

log = logging.getLogger(__name__)


class Worker:
    def __init__(self, settings, store, stripe, treasury=None, api_caller=None):
        self.settings, self.store, self.stripe, self.treasury = settings, store, stripe, treasury
        self.api_caller = api_caller

    @staticmethod
    def _api_key(row):
        service = row.get("service") or {}
        return isinstance(service, dict) and service.get("settlement") == "api_key"

    def _apply_failure(self, row, current, *, reverted, reason):
        action = settlement_outcome(current["payment_status"], reverted)
        if action is Action.REFUND:
            self.store.finish(row["execution_id"], refund_reason=reason, payment_reverted=reverted)
            return
        if action is Action.HOLD and current["payment_status"] != "sent":
            review = "A signed payment needs reconciliation before credits can be returned."
        else:
            review = reason
        self.store.needs_review(row["execution_id"], review)
        if action is Action.HOLD_AND_DISABLE:
            self.store.disable_service(current["endpoint_id"], reason)

    async def _execute_api_key(self, row):
        if row.get("status") in {"completed", "refunded"}:
            return
        if row.get("payment_status") == "confirmed" and isinstance(row.get("data"), dict):
            self.store.finish(row["execution_id"], data=row["data"])
            return
        # Already sent or confirmed: hold for review and do not POST again.
        if row.get("payment_status") in {"sent", "confirmed"}:
            self.store.needs_review(
                row["execution_id"],
                "An API-key request was already sent and needs review.",
            )
            return
        if self.api_caller is None:
            self.api_caller = ApiKeyCaller(self.settings, self.store)
        try:
            await self.api_caller.purchase(row)
        except TerminalFailure as exc:
            current = self.store.execution_internal(row["execution_id"])
            self._apply_failure(row, current, reverted=exc.reverted, reason=str(exc))
        except Exception as exc:
            if isinstance(exc, ProductError) and exc.code == "worker_lease_lost":
                raise
            current = self.store.execution_internal(row["execution_id"])
            if current["status"] in {"completed", "refunded"}:
                return
            log.warning(
                "Execution retry execution_id=%s error=%s",
                row["execution_id"],
                type(exc).__name__,
            )
            # A journaled send is final. Do not POST again, refund, or disable.
            if current["payment_status"] in {"sent", "confirmed"}:
                if current["payment_status"] == "sent":
                    self._apply_failure(
                        row,
                        current,
                        reverted=False,
                        reason="Provider request failed after it was sent. Reserved credits need review.",
                    )
                else:
                    self.store.needs_review(
                        row["execution_id"],
                        "Provider result needs review.",
                    )
                return
            if current["attempts"] + 1 >= self.settings.max_attempts:
                outcome = settlement_outcome(current["payment_status"], False)
                if outcome is Action.REFUND:
                    reason = (
                        "Service could not deliver a result within its retry window. "
                        "Credits returned."
                    )
                else:
                    reason = (
                        "Service could not deliver a result within its retry window. "
                        "Reserved credits need review."
                    )
                self._apply_failure(row, current, reverted=False, reason=reason)
            else:
                self.store.retry_execution(
                    row["execution_id"],
                    "Provider payment or result is pending reconciliation.",
                    self.settings.retry_seconds,
                    self.settings.max_attempts,
                )

    async def execution(self, row, lock):
        if self._api_key(row):
            await self._execute_api_key(row)
            return
        try:
            await self.treasury.purchase(row, lock)
        except TerminalFailure as exc:
            current = self.store.execution_internal(row["execution_id"])
            self._apply_failure(row, current, reverted=exc.reverted, reason=str(exc))
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
            if current["attempts"] + 1 >= self.settings.max_attempts:
                outcome = settlement_outcome(current["payment_status"], False)
                if outcome is Action.REFUND:
                    reason = (
                        "Service could not deliver a result within its retry window. "
                        "Credits returned."
                    )
                else:
                    reason = (
                        "Service could not deliver a result within its retry window. "
                        "Reserved credits need review."
                    )
                self._apply_failure(row, current, reverted=False, reason=reason)
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
            if self.treasury is None and self.store.requires_treasury(self.settings.mode):
                raise ValueError(
                    "MPP services or unfinished MPP payments require a treasury signer; "
                    "configure OPENMCP_TREASURY_KEY_FILE and restart the worker"
                )
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
            for row in self.store.pending_executions():
                if self._api_key(row) or self.treasury:
                    await self.execution(row, lock)
                    self.store.heartbeat()
            return True

    async def run(self):
        while True:
            await self.tick()
            await asyncio.sleep(self.settings.worker_interval)
