"""In-memory credit ledger. A single lock serializes overlapping postings."""

import threading
from collections.abc import Callable
from typing import TypeVar

from openmcp.ports.ledger import LedgerState

T = TypeVar("T")


class MemoryLedger:
    """Process-local ``CreditLedger`` used by tests.

    The lock is held for the whole domain decision, so two debits of the same
    last credits cannot both succeed.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = LedgerState()

    def apply(self, decide: Callable[[LedgerState], tuple[LedgerState, T]]) -> T:
        with self._lock:
            updated, result = decide(self._state)
            if not isinstance(updated, LedgerState):
                raise TypeError("decide must return a LedgerState")
            self._state = updated
            return result

    def balance_cents(self, account_id: str) -> int:
        with self._lock:
            return self._state.balances.get(account_id, 0)
