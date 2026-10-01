"""Resolve account credentials and the demo connection token."""

import hmac
from datetime import datetime, timezone

from fastapi import Request

from openmcp.domain.accounts import (
    AuthenticationFailed,
    Forbidden,
    NotFound,
    Principal,
    account_for_credit_debit,
    account_for_credit_deposit,
    account_for_credit_read,
    ensure_owner,
    resolve_bearer,
)
from openmcp.models import OpenMCPError

_ACCOUNT_MESSAGE = "Account credential required."
_DEMO_MESSAGE = "OpenMCP connection token required."


def require_demo_token(request: Request) -> None:
    """Allow only the operator connection token. Used for account bootstrap."""

    settings = request.app.state.settings
    expected = f"Bearer {settings.api_token.get_secret_value()}".encode()
    authorization = (request.headers.get("authorization") or "").encode()
    if not hmac.compare_digest(authorization, expected):
        raise OpenMCPError("unauthorized", _DEMO_MESSAGE, status=401)


def require_owner_principal(request: Request) -> Principal:
    """Owner credential required. Agent credentials are forbidden."""

    principal = _principal(request)
    try:
        return ensure_owner(principal)
    except Forbidden as exc:
        raise OpenMCPError("forbidden", str(exc), status=403) from exc


def require_credit_read_account(request: Request) -> str:
    principal = _principal(request)
    try:
        return account_for_credit_read(principal)
    except Forbidden as exc:
        raise OpenMCPError("forbidden", str(exc), status=403) from exc


def require_credit_deposit_account(request: Request) -> str:
    principal = _principal(request)
    try:
        return account_for_credit_deposit(principal)
    except Forbidden as exc:
        raise OpenMCPError("forbidden", str(exc), status=403) from exc


def require_credit_debit_account(request: Request) -> str:
    principal = _principal(request)
    try:
        return account_for_credit_debit(principal)
    except Forbidden as exc:
        raise OpenMCPError("forbidden", str(exc), status=403) from exc


def call_account(action):
    """Run an account use case and map its failures onto HTTP errors."""

    try:
        return action()
    except AuthenticationFailed as exc:
        raise OpenMCPError("unauthorized", _ACCOUNT_MESSAGE, status=401) from exc
    except Forbidden as exc:
        raise OpenMCPError("forbidden", str(exc), status=403) from exc
    except NotFound as exc:
        raise OpenMCPError("not_found", str(exc), status=404) from exc
    except ValueError as exc:
        raise OpenMCPError("invalid_request", str(exc), status=422) from exc


def _principal(request: Request) -> Principal:
    token = _bearer(request.headers.get("authorization"))
    if token is None:
        raise OpenMCPError("unauthorized", _ACCOUNT_MESSAGE, status=401)
    try:
        return resolve_bearer(
            request.app.state.accounts,
            token,
            now=datetime.now(timezone.utc),
        )
    except AuthenticationFailed as exc:
        raise OpenMCPError("unauthorized", _ACCOUNT_MESSAGE, status=401) from exc


def _bearer(header: str | None) -> str | None:
    if header is None:
        return None
    parts = header.split(" ")
    if len(parts) != 2 or parts[0].lower() != "bearer" or parts[1] == "":
        return None
    return parts[1]
