"""Ledger port for posted OpenMCP credit balances.

Balances are integer cents. This port does not open a database or a socket.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Protocol, TypeVar

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class PostedDeposit:
    """One confirmed charge that has already increased a credit balance."""

    account_id: str
    amount_cents: int


@dataclass(frozen=True, slots=True)
class PostedDebit:
    """One successful query debit, keyed so a replay can return it."""

    price_cents: int
    balance_after_cents: int


@dataclass(frozen=True, slots=True)
class LedgerState:
    """Snapshot the domain decides against. Adapters persist the replacement."""

    balances: Mapping[str, int] = field(default_factory=dict)
    deposits: Mapping[str, PostedDeposit] = field(default_factory=dict)
    debits: Mapping[tuple[str, str], PostedDebit] = field(default_factory=dict)


class CreditLedger(Protocol):
    """Persistence for credit postings.

    ``apply`` runs the domain decision once while holding the adapter's lock
    (or an equivalent critical section) and then stores the returned state.
    """

    def apply(self, decide: Callable[[LedgerState], tuple[LedgerState, T]]) -> T:
        """Persist the state returned by ``decide`` and return its result."""
        ...

    def balance_cents(self, account_id: str) -> int:
        """Return posted credits for ``account_id``, or 0 when none exist."""
        ...
