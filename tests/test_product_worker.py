"""Recovery policy cannot turn payment uncertainty into free credits or a new signature."""

from unittest.mock import AsyncMock, Mock

import pytest

from openmcp.product.config import ProductSettings
from openmcp.product.models import ProductError
from openmcp.product.policy import Action, settlement_outcome
from openmcp.product.settlement import PendingPayment, TerminalFailure
from openmcp.product.worker import Worker


def test_unknown_payment_status_is_not_a_refund():
    assert settlement_outcome("unsigned", False) is Action.REFUND
    assert settlement_outcome("signed", True) is Action.REFUND
    assert settlement_outcome("signed", False) is Action.HOLD
    assert settlement_outcome("sent", False) is Action.HOLD
    assert settlement_outcome("sent", True) is Action.HOLD
    assert settlement_outcome("confirmed", False) is Action.HOLD_AND_DISABLE
    assert settlement_outcome("mystery", False) is Action.HOLD
    assert settlement_outcome("confirmed", True) is Action.REFUND


@pytest.mark.parametrize(
    "payment_status,refund,disable",
    [
        ("unsigned", True, False),
        ("confirmed", False, True),
        ("signed", False, False),
        ("sent", False, False),
        ("mystery", False, False),
    ],
)
async def test_retry_exhaustion_follows_payment_policy(payment_status, refund, disable):
    settings = ProductSettings(_env_file=None, max_attempts=3)
    row = {
        "execution_id": "exe_one",
        "endpoint_id": "example",
        "status": "payment_pending",
        "payment_status": payment_status,
        "attempts": 2,
    }
    store = Mock()
    store.execution_internal.return_value = row
    treasury = Mock(purchase=AsyncMock(side_effect=PendingPayment("lost response")))
    worker = Worker(settings, store, Mock(), treasury)
    await worker.execution(row, Mock())
    assert store.finish.called is refund
    assert store.needs_review.called is (not refund)
    assert store.disable_service.called is disable
    assert store.retry_execution.called is False
    treasury.purchase.assert_awaited_once()
    if disable:
        assert store.disable_service.call_args.args[0] == "example"


@pytest.mark.parametrize(
    "payment_status,reverted,refund,disable",
    [
        ("unsigned", False, True, False),
        ("confirmed", False, False, True),
        ("signed", False, False, False),
        ("signed", True, True, False),
        ("sent", False, False, False),
        ("sent", True, False, False),
        ("mystery", False, False, False),
    ],
)
async def test_terminal_failure_preserves_ambiguous_signed_payment(
    payment_status, reverted, refund, disable
):
    settings = ProductSettings(_env_file=None)
    row = {
        "execution_id": "exe_one",
        "endpoint_id": "example",
        "status": "payment_pending",
        "payment_status": payment_status,
    }
    store = Mock()
    store.execution_internal.return_value = row
    treasury = Mock(
        purchase=AsyncMock(side_effect=TerminalFailure("provider failed", reverted=reverted))
    )
    await Worker(settings, store, Mock(), treasury).execution(row, Mock())
    assert store.finish.called is refund
    assert store.needs_review.called is (not refund)
    assert store.disable_service.called is disable
    if disable:
        store.disable_service.assert_called_once_with("example", "provider failed")
    else:
        store.disable_service.assert_not_called()


async def test_lost_worker_lock_stops_without_refund_or_retry():
    store = Mock()
    treasury = Mock(
        purchase=AsyncMock(side_effect=ProductError("worker_lease_lost", "Lost lock", 503, True))
    )
    with pytest.raises(ProductError):
        await Worker(ProductSettings(_env_file=None), store, Mock(), treasury).execution(
            {"execution_id": "exe_one"}, Mock()
        )
    store.finish.assert_not_called()
    store.retry_execution.assert_not_called()
    store.needs_review.assert_not_called()
    store.disable_service.assert_not_called()


async def test_api_key_already_sent_holds_without_posting():
    row = {
        "execution_id": "exe_one",
        "endpoint_id": "example",
        "status": "payment_pending",
        "payment_status": "sent",
        "service": {"settlement": "api_key"},
        "attempts": 0,
    }
    store = Mock()
    caller = Mock(purchase=AsyncMock())
    await Worker(ProductSettings(_env_file=None), store, Mock(), Mock(), caller).execution(
        row, Mock()
    )
    caller.purchase.assert_not_called()
    store.needs_review.assert_called_once()
    store.finish.assert_not_called()
    store.disable_service.assert_not_called()
    store.retry_execution.assert_not_called()


async def test_api_key_error_after_sent_does_not_retry_post():
    row = {
        "execution_id": "exe_one",
        "endpoint_id": "example",
        "status": "payment_pending",
        "payment_status": "unsigned",
        "service": {"settlement": "api_key"},
        "attempts": 0,
    }
    store = Mock()
    store.execution_internal.return_value = {**row, "payment_status": "sent"}
    caller = Mock(purchase=AsyncMock(side_effect=RuntimeError("socket")))
    await Worker(ProductSettings(_env_file=None, max_attempts=5), store, Mock(), Mock(), caller).execution(
        row, Mock()
    )
    caller.purchase.assert_awaited_once()
    store.retry_execution.assert_not_called()
    store.finish.assert_not_called()
    store.disable_service.assert_not_called()
    store.needs_review.assert_called_once()
