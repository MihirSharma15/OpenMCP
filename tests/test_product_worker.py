"""Recovery policy cannot turn payment uncertainty into free credits or a new signature."""

from unittest.mock import AsyncMock, Mock

import pytest

from openmcp.product.config import ProductSettings
from openmcp.product.models import ProductError
from openmcp.product.settlement import PendingPayment, TerminalFailure
from openmcp.product.worker import Worker


@pytest.mark.parametrize(
    "payment_status,refund", [("unsigned", True), ("confirmed", True), ("signed", False)]
)
async def test_retry_exhaustion_refunds_only_when_payment_outcome_is_known(payment_status, refund):
    settings = ProductSettings(_env_file=None, max_attempts=3)
    row = {
        "execution_id": "exe_one",
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
    assert store.retry_execution.called is (not refund)
    treasury.purchase.assert_awaited_once()


@pytest.mark.parametrize(
    "payment_status,reverted,refund",
    [
        ("unsigned", False, True),
        ("confirmed", False, True),
        ("signed", False, False),
        ("signed", True, True),
    ],
)
async def test_terminal_failure_preserves_ambiguous_signed_payment(
    payment_status, reverted, refund
):
    settings = ProductSettings(_env_file=None)
    row = {"execution_id": "exe_one", "status": "payment_pending", "payment_status": payment_status}
    store = Mock()
    store.execution_internal.return_value = row
    treasury = Mock(
        purchase=AsyncMock(side_effect=TerminalFailure("provider failed", reverted=reverted))
    )
    await Worker(settings, store, Mock(), treasury).execution(row, Mock())
    assert store.finish.called is refund
    assert store.needs_review.called is (not refund)


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
