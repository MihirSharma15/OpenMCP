"""OpenMCP domain services.

Credit balances are integer cents, not Tempo pathUSD. Account credentials are
hashed; the use case that creates one returns the raw secret a single time.
"""

from .accounts import (
    AuthenticationFailed,
    Forbidden,
    IssuedCredential,
    NotFound,
    Principal,
    Scope,
    account_for_credit_debit,
    account_for_credit_deposit,
    account_for_credit_read,
    create_account,
    create_agent,
    ensure_owner,
    issue_credential,
    resolve_bearer,
    revoke_credential,
)
from .credits import (
    ChargeStatus,
    DebitOutcome,
    DebitResult,
    DepositOutcome,
    DepositResult,
    InvalidAmount,
    debit_for_query,
    post_deposit,
)

__all__ = [
    "AuthenticationFailed",
    "ChargeStatus",
    "DebitOutcome",
    "DebitResult",
    "DepositOutcome",
    "DepositResult",
    "Forbidden",
    "InvalidAmount",
    "IssuedCredential",
    "NotFound",
    "Principal",
    "Scope",
    "account_for_credit_debit",
    "account_for_credit_deposit",
    "account_for_credit_read",
    "create_account",
    "create_agent",
    "debit_for_query",
    "ensure_owner",
    "issue_credential",
    "post_deposit",
    "resolve_bearer",
    "revoke_credential",
]
