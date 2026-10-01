"""Integer-cent credit rules for OpenMCP accounts.

A credit balance is an OpenMCP ledger quantity in cents. It is not Tempo
pathUSD, a card limit, or a wallet balance. Deposits post only for a confirmed
charge. Query debits spend posted credits and never charge a card.
"""

from dataclasses import dataclass
from enum import StrEnum

from openmcp.ports.ledger import CreditLedger, LedgerState, PostedDebit, PostedDeposit


class InvalidAmount(ValueError):
    """A cent amount was zero, negative, or not an integer."""

    def __init__(self, amount: object) -> None:
        self.amount = amount
        super().__init__("amount must be a positive integer number of cents")


class ChargeStatus(StrEnum):
    """Whether a card charge may fund credits. Only CONFIRMED posts."""

    CONFIRMED = "confirmed"
    PENDING = "pending"
    FAILED = "failed"
    UNKNOWN = "unknown"


class DepositOutcome(StrEnum):
    POSTED = "posted"
    IGNORED = "ignored"
    REPLAYED = "replayed"


class DebitOutcome(StrEnum):
    DEBITED = "debited"
    INSUFFICIENT_CREDITS = "insufficient_credits"
    REPLAYED = "replayed"


@dataclass(frozen=True, slots=True)
class DepositResult:
    account_id: str
    charge_id: str
    amount_cents: int
    balance_cents: int
    outcome: DepositOutcome


@dataclass(frozen=True, slots=True)
class DebitResult:
    account_id: str
    idempotency_key: str
    price_cents: int
    balance_cents: int
    outcome: DebitOutcome


def _require_positive_cents(amount: object) -> int:
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise InvalidAmount(amount)
    if amount <= 0:
        raise InvalidAmount(amount)
    return amount


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _decide_deposit(
    state: LedgerState,
    account_id: str,
    amount_cents: int,
    charge_id: str,
    status: ChargeStatus,
) -> tuple[LedgerState, DepositResult]:
    account_id = _require_text(account_id, "account_id")
    charge_id = _require_text(charge_id, "charge_id")
    amount_cents = _require_positive_cents(amount_cents)
    if not isinstance(status, ChargeStatus):
        raise TypeError("status must be a ChargeStatus")

    balance = state.balances.get(account_id, 0)
    if status is not ChargeStatus.CONFIRMED:
        return state, DepositResult(
            account_id=account_id,
            charge_id=charge_id,
            amount_cents=amount_cents,
            balance_cents=balance,
            outcome=DepositOutcome.IGNORED,
        )

    existing = state.deposits.get(charge_id)
    if existing is not None:
        return state, DepositResult(
            account_id=existing.account_id,
            charge_id=charge_id,
            amount_cents=existing.amount_cents,
            balance_cents=state.balances.get(existing.account_id, 0),
            outcome=DepositOutcome.REPLAYED,
        )

    posted_balance = balance + amount_cents
    balances = dict(state.balances)
    balances[account_id] = posted_balance
    deposits = dict(state.deposits)
    deposits[charge_id] = PostedDeposit(account_id=account_id, amount_cents=amount_cents)
    updated = LedgerState(balances=balances, deposits=deposits, debits=state.debits)
    return updated, DepositResult(
        account_id=account_id,
        charge_id=charge_id,
        amount_cents=amount_cents,
        balance_cents=posted_balance,
        outcome=DepositOutcome.POSTED,
    )


def _decide_debit(
    state: LedgerState,
    account_id: str,
    price_cents: int,
    idempotency_key: str,
) -> tuple[LedgerState, DebitResult]:
    account_id = _require_text(account_id, "account_id")
    idempotency_key = _require_text(idempotency_key, "idempotency_key")
    price_cents = _require_positive_cents(price_cents)
    balance = state.balances.get(account_id, 0)
    existing = state.debits.get((account_id, idempotency_key))
    if existing is not None:
        return state, DebitResult(
            account_id=account_id,
            idempotency_key=idempotency_key,
            price_cents=existing.price_cents,
            balance_cents=existing.balance_after_cents,
            outcome=DebitOutcome.REPLAYED,
        )
    if balance < price_cents:
        return state, DebitResult(
            account_id=account_id,
            idempotency_key=idempotency_key,
            price_cents=price_cents,
            balance_cents=balance,
            outcome=DebitOutcome.INSUFFICIENT_CREDITS,
        )

    balance_after = balance - price_cents
    balances = dict(state.balances)
    balances[account_id] = balance_after
    debits = dict(state.debits)
    debits[(account_id, idempotency_key)] = PostedDebit(
        price_cents=price_cents,
        balance_after_cents=balance_after,
    )
    updated = LedgerState(balances=balances, deposits=state.deposits, debits=debits)
    return updated, DebitResult(
        account_id=account_id,
        idempotency_key=idempotency_key,
        price_cents=price_cents,
        balance_cents=balance_after,
        outcome=DebitOutcome.DEBITED,
    )


def post_deposit(
    ledger: CreditLedger,
    account_id: str,
    amount_cents: int,
    charge_id: str,
    *,
    status: ChargeStatus,
) -> DepositResult:
    """Add credits only when ``status`` is confirmed. A charge id posts once."""

    def decide(state: LedgerState) -> tuple[LedgerState, DepositResult]:
        return _decide_deposit(state, account_id, amount_cents, charge_id, status)

    return ledger.apply(decide)


def debit_for_query(
    ledger: CreditLedger,
    account_id: str,
    price_cents: int,
    idempotency_key: str,
) -> DebitResult:
    """Subtract credits when the balance covers the price. Does not charge a card."""

    def decide(state: LedgerState) -> tuple[LedgerState, DebitResult]:
        return _decide_debit(state, account_id, price_cents, idempotency_key)

    return ledger.apply(decide)
