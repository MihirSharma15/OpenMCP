"""Credit routes. The account id comes from the bearer credential."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from openmcp.domain.credits import InvalidAmount, debit_for_query, post_deposit
from openmcp.models import OpenMCPError

from .auth import (
    require_credit_debit_account,
    require_credit_deposit_account,
    require_credit_read_account,
)
from .models import (
    CreditsResponse,
    DebitRequest,
    DebitResponse,
    DepositRequest,
    DepositResponse,
)

router = APIRouter(prefix="/v1")


@router.get("/credits", response_model=CreditsResponse)
def read_credits(
    request: Request,
    account_id: Annotated[str, Depends(require_credit_read_account)],
) -> CreditsResponse:
    available_cents = request.app.state.ledger.balance_cents(account_id)
    return CreditsResponse(available_cents=available_cents, currency="usd_credits")


@router.post("/credits/deposits", response_model=DepositResponse)
def deposit_credits(
    body: DepositRequest,
    request: Request,
    account_id: Annotated[str, Depends(require_credit_deposit_account)],
) -> DepositResponse:
    try:
        result = post_deposit(
            request.app.state.ledger,
            account_id,
            body.amount_cents,
            body.charge_id,
            status=body.status,
        )
    except InvalidAmount as exc:
        raise OpenMCPError("invalid_amount", str(exc), status=422) from exc
    return DepositResponse(
        available_cents=result.balance_cents,
        amount_cents=result.amount_cents,
        charge_id=result.charge_id,
        outcome=result.outcome,
    )


@router.post("/credits/debits", response_model=DebitResponse)
def debit_credits(
    body: DebitRequest,
    request: Request,
    account_id: Annotated[str, Depends(require_credit_debit_account)],
) -> DebitResponse:
    try:
        result = debit_for_query(
            request.app.state.ledger,
            account_id,
            body.price_cents,
            body.idempotency_key,
        )
    except InvalidAmount as exc:
        raise OpenMCPError("invalid_amount", str(exc), status=422) from exc
    return DebitResponse(
        available_cents=result.balance_cents,
        price_cents=result.price_cents,
        idempotency_key=result.idempotency_key,
        outcome=result.outcome,
    )
