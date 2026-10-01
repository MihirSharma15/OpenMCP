import ast
import threading
import time
from pathlib import Path

import pytest

from openmcp.adapters.memory import MemoryLedger
from openmcp.domain import credits
from openmcp.domain.credits import (
    ChargeStatus,
    DebitOutcome,
    DepositOutcome,
    InvalidAmount,
    debit_for_query,
    post_deposit,
)

ACCOUNT = "acct-1"
ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = {"fastapi", "sqlalchemy", "sqlite3", "httpx", "stripe", "socket"}


def test_confirmed_deposit_sets_balance_to_1000():
    ledger = MemoryLedger()
    result = post_deposit(ledger, ACCOUNT, 1000, "ch_1000", status=ChargeStatus.CONFIRMED)
    assert result.outcome is DepositOutcome.POSTED
    assert result.amount_cents == 1000
    assert result.balance_cents == 1000
    assert ledger.balance_cents(ACCOUNT) == 1000


@pytest.mark.parametrize(
    "status",
    [ChargeStatus.PENDING, ChargeStatus.FAILED, ChargeStatus.UNKNOWN],
)
def test_unconfirmed_deposit_leaves_balance_at_zero(status):
    ledger = MemoryLedger()
    first = post_deposit(ledger, ACCOUNT, 1000, "ch_open", status=status)
    second = post_deposit(ledger, ACCOUNT, 1000, "ch_open", status=status)
    assert first.outcome is DepositOutcome.IGNORED
    assert second.outcome is DepositOutcome.IGNORED
    assert first.balance_cents == 0
    assert ledger.balance_cents(ACCOUNT) == 0


def test_replaying_confirmed_charge_does_not_double_credit():
    ledger = MemoryLedger()
    first = post_deposit(ledger, ACCOUNT, 1000, "ch_once", status=ChargeStatus.CONFIRMED)
    replay = post_deposit(ledger, ACCOUNT, 1000, "ch_once", status=ChargeStatus.CONFIRMED)
    other_amount = post_deposit(ledger, ACCOUNT, 500, "ch_once", status=ChargeStatus.CONFIRMED)
    assert first.outcome is DepositOutcome.POSTED
    assert replay.outcome is DepositOutcome.REPLAYED
    assert replay.amount_cents == 1000
    assert other_amount.outcome is DepositOutcome.REPLAYED
    assert other_amount.amount_cents == 1000
    assert ledger.balance_cents(ACCOUNT) == 1000


def test_confirmation_after_pending_posts_once():
    ledger = MemoryLedger()
    pending = post_deposit(ledger, ACCOUNT, 1000, "ch_later", status=ChargeStatus.PENDING)
    posted = post_deposit(ledger, ACCOUNT, 1000, "ch_later", status=ChargeStatus.CONFIRMED)
    replay = post_deposit(ledger, ACCOUNT, 1000, "ch_later", status=ChargeStatus.CONFIRMED)
    assert pending.outcome is DepositOutcome.IGNORED
    assert posted.outcome is DepositOutcome.POSTED
    assert replay.outcome is DepositOutcome.REPLAYED
    assert ledger.balance_cents(ACCOUNT) == 1000


def test_debit_of_40_cents_from_1000_leaves_960():
    ledger = MemoryLedger()
    post_deposit(ledger, ACCOUNT, 1000, "ch_fund", status=ChargeStatus.CONFIRMED)
    result = debit_for_query(ledger, ACCOUNT, 40, "query-40")
    assert result.outcome is DebitOutcome.DEBITED
    assert result.price_cents == 40
    assert result.balance_cents == 960
    assert ledger.balance_cents(ACCOUNT) == 960


def test_debit_larger_than_balance_is_insufficient_credits():
    ledger = MemoryLedger()
    post_deposit(ledger, ACCOUNT, 1000, "ch_fund", status=ChargeStatus.CONFIRMED)
    result = debit_for_query(ledger, ACCOUNT, 1001, "query-over")
    assert result.outcome == "insufficient_credits"
    assert result.outcome is DebitOutcome.INSUFFICIENT_CREDITS
    assert result.balance_cents == 1000
    assert ledger.balance_cents(ACCOUNT) == 1000


def test_replaying_debit_idempotency_key_does_not_subtract_twice():
    ledger = MemoryLedger()
    post_deposit(ledger, ACCOUNT, 1000, "ch_fund", status=ChargeStatus.CONFIRMED)
    first = debit_for_query(ledger, ACCOUNT, 40, "query-40")
    replay = debit_for_query(ledger, ACCOUNT, 40, "query-40")
    different_price = debit_for_query(ledger, ACCOUNT, 25, "query-40")
    assert first.outcome is DebitOutcome.DEBITED
    assert first.balance_cents == 960
    assert replay.outcome is DebitOutcome.REPLAYED
    assert replay.price_cents == 40
    assert replay.balance_cents == 960
    assert different_price.outcome is DebitOutcome.REPLAYED
    assert different_price.price_cents == 40
    assert ledger.balance_cents(ACCOUNT) == 960


def test_concurrent_debits_cannot_both_spend_the_last_credits(monkeypatch):
    _slow(monkeypatch, "_decide_debit")
    ledger = MemoryLedger()
    post_deposit(ledger, ACCOUNT, 1000, "ch_fund", status=ChargeStatus.CONFIRMED)
    results = _run_together(
        lambda: debit_for_query(ledger, ACCOUNT, 1000, "query-a"),
        lambda: debit_for_query(ledger, ACCOUNT, 1000, "query-b"),
    )
    debited = [result for result in results if result.outcome is DebitOutcome.DEBITED]
    refused = [result for result in results if result.outcome is DebitOutcome.INSUFFICIENT_CREDITS]
    assert len(debited) == 1
    assert len(refused) == 1
    assert ledger.balance_cents(ACCOUNT) == 0


def test_concurrent_debits_never_spend_more_than_the_balance(monkeypatch):
    _slow(monkeypatch, "_decide_debit")
    ledger = MemoryLedger()
    start = 1000
    price = 400
    post_deposit(ledger, ACCOUNT, start, "ch_fund", status=ChargeStatus.CONFIRMED)
    results = _run_together(
        *[lambda i=i: debit_for_query(ledger, ACCOUNT, price, f"query-{i}") for i in range(5)]
    )
    spent = sum(result.price_cents for result in results if result.outcome is DebitOutcome.DEBITED)
    assert spent <= start
    assert spent == 800
    assert ledger.balance_cents(ACCOUNT) == start - spent


def test_concurrent_same_charge_posts_once(monkeypatch):
    _slow(monkeypatch, "_decide_deposit")
    ledger = MemoryLedger()
    results = _run_together(
        lambda: post_deposit(ledger, ACCOUNT, 1000, "ch_race", status=ChargeStatus.CONFIRMED),
        lambda: post_deposit(ledger, ACCOUNT, 1000, "ch_race", status=ChargeStatus.CONFIRMED),
    )
    posted = [result for result in results if result.outcome is DepositOutcome.POSTED]
    replayed = [result for result in results if result.outcome is DepositOutcome.REPLAYED]
    assert len(posted) == 1
    assert len(replayed) == 1
    assert ledger.balance_cents(ACCOUNT) == 1000


@pytest.mark.parametrize("amount", [0, -1, -40, True, False, 1.5, "1000"])
def test_rejects_non_positive_integer_amounts(amount):
    ledger = MemoryLedger()
    post_deposit(ledger, ACCOUNT, 1000, "ch_fund", status=ChargeStatus.CONFIRMED)
    with pytest.raises(InvalidAmount):
        post_deposit(ledger, ACCOUNT, amount, "ch_bad", status=ChargeStatus.CONFIRMED)
    with pytest.raises(InvalidAmount):
        debit_for_query(ledger, ACCOUNT, amount, "query-bad")
    assert ledger.balance_cents(ACCOUNT) == 1000


def test_credit_rules_do_not_import_frameworks_or_the_memory_adapter():
    domain = ROOT / "openmcp" / "domain"
    ports = ROOT / "openmcp" / "ports"
    memory = ROOT / "openmcp" / "adapters" / "memory"
    for path in list(domain.rglob("*.py")) + list(ports.rglob("*.py")) + list(memory.rglob("*.py")):
        modules = _imported_modules(path)
        tops = {module.split(".")[0] for module in modules}
        assert tops.isdisjoint(FORBIDDEN), f"{path} imports {tops & FORBIDDEN}"
    for path in domain.rglob("*.py"):
        modules = _imported_modules(path)
        assert all(not module.startswith("openmcp.adapters") for module in modules)


def _slow(monkeypatch, name):
    original = getattr(credits, name)

    def slowed(*args, **kwargs):
        time.sleep(0.03)
        return original(*args, **kwargs)

    monkeypatch.setattr(credits, name, slowed)


def _run_together(*calls):
    barrier = threading.Barrier(len(calls))
    results = [None] * len(calls)
    errors = []

    def run(index, call):
        try:
            barrier.wait(timeout=2)
            results[index] = call()
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(index, call)) for index, call in enumerate(calls)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()
    assert errors == []
    return results


def _imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules
