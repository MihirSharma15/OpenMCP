"""Account, agent, and credential rules.

The raw secret is created here and returned to the caller once. The stored
record keeps only a sha256 hash. This module does not open a database or a
socket, and it does not log the secret.
"""

import hashlib
import hmac
import secrets
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import StrEnum

from openmcp.ports.accounts import Account, AccountState, AccountStore, Agent, Credential


class Scope(StrEnum):
    """Scopes carried by a credential. An agent scope cannot manage the account."""

    OWNER_BILLING = "owner:billing"
    AGENT_EXECUTE = "agent:execute"


_OWNER_SCOPES = frozenset({Scope.OWNER_BILLING})
_AGENT_SCOPES = frozenset({Scope.AGENT_EXECUTE})
_CREDIT_SCOPES = frozenset({Scope.OWNER_BILLING, Scope.AGENT_EXECUTE})
_HEX = "0123456789abcdef"


class AuthenticationFailed(Exception):
    """The bearer token is unknown, revoked, or expired.

    ``reason`` is ``unknown``, ``revoked``, or ``expired``. The message stays
    generic so a log of this error does not describe which check failed.
    """

    def __init__(self, reason: str) -> None:
        if reason not in {"unknown", "revoked", "expired"}:
            raise ValueError("invalid authentication failure reason")
        self.reason = reason
        super().__init__("credential is invalid")


class Forbidden(Exception):
    """The principal is authenticated and is not allowed to do this."""


class NotFound(Exception):
    """The agent or credential is not visible to this account."""


@dataclass(frozen=True, slots=True)
class Principal:
    """Who a valid bearer token resolved to. ``agent_id`` is null for an owner."""

    account_id: str
    agent_id: str | None
    credential_id: str
    scopes: frozenset[str]


@dataclass(frozen=True, slots=True)
class IssuedCredential:
    """A credential that was just created. ``secret`` must not be stored or logged."""

    account_id: str
    agent_id: str | None
    credential_id: str
    secret: str
    scopes: frozenset[str]


def hash_token(token: str) -> str:
    """Return the sha256 hex digest of a bearer token. Do not log ``token``."""

    if not isinstance(token, str) or token == "":
        raise ValueError("token must be a non-empty string")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_account(store: AccountStore) -> IssuedCredential:
    """Create an account and its first owner credential.

    The returned secret is the caller's only copy. The store receives the hash.
    """

    def decide(state: AccountState) -> tuple[AccountState, IssuedCredential]:
        account_id = _new_id("acct")
        if account_id in state.accounts:
            raise RuntimeError("account id collision")
        accounts = dict(state.accounts)
        accounts[account_id] = Account(account_id=account_id)
        staged = AccountState(accounts=accounts, agents=state.agents, credentials=state.credentials)
        return _issue(
            staged,
            account_id=account_id,
            agent_id=None,
            scopes=frozenset({Scope.OWNER_BILLING.value}),
            expires_at=None,
        )

    return store.apply(decide)


def create_agent(store: AccountStore, principal: Principal) -> Agent:
    """Create an agent under the owner principal's account."""

    ensure_owner(principal)

    def decide(state: AccountState) -> tuple[AccountState, Agent]:
        if principal.account_id not in state.accounts:
            raise NotFound("Account not found.")
        agent_id = _new_id("agt")
        if agent_id in state.agents:
            raise RuntimeError("agent id collision")
        agent = Agent(agent_id=agent_id, account_id=principal.account_id)
        agents = dict(state.agents)
        agents[agent_id] = agent
        updated = AccountState(
            accounts=state.accounts, agents=agents, credentials=state.credentials
        )
        return updated, agent

    return store.apply(decide)


def issue_credential(
    store: AccountStore,
    principal: Principal,
    *,
    agent_id: str | None,
    scopes: Iterable[str],
    expires_at: datetime | None = None,
) -> IssuedCredential:
    """Create an owner or agent credential. The raw secret is returned once."""

    ensure_owner(principal)
    owner_agent_id = _optional_id(agent_id, "agent_id")
    normalized = _normalize_scopes(scopes, agent_id=owner_agent_id)
    expiry = _aware(expires_at, "expires_at")

    def decide(state: AccountState) -> tuple[AccountState, IssuedCredential]:
        if owner_agent_id is None:
            if principal.account_id not in state.accounts:
                raise NotFound("Account not found.")
            account_id = principal.account_id
        else:
            agent = state.agents.get(owner_agent_id)
            if agent is None or agent.account_id != principal.account_id:
                raise NotFound("Agent not found.")
            account_id = agent.account_id
        return _issue(
            state,
            account_id=account_id,
            agent_id=owner_agent_id,
            scopes=normalized,
            expires_at=expiry,
        )

    return store.apply(decide)


def revoke_credential(
    store: AccountStore,
    principal: Principal,
    credential_id: str,
    *,
    agent_id: str,
) -> Credential:
    """Revoke one agent credential owned by the principal's account."""

    ensure_owner(principal)
    if not isinstance(credential_id, str) or credential_id == "":
        raise NotFound("Credential not found.")
    if not isinstance(agent_id, str) or agent_id == "":
        raise NotFound("Agent not found.")

    def decide(state: AccountState) -> tuple[AccountState, Credential]:
        agent = state.agents.get(agent_id)
        if agent is None or agent.account_id != principal.account_id:
            raise NotFound("Agent not found.")
        current = state.credentials.get(credential_id)
        if (
            current is None
            or current.account_id != principal.account_id
            or current.agent_id != agent_id
        ):
            raise NotFound("Credential not found.")
        revoked = replace(current, revoked=True)
        credentials = dict(state.credentials)
        credentials[credential_id] = revoked
        updated = AccountState(
            accounts=state.accounts, agents=state.agents, credentials=credentials
        )
        return updated, revoked

    return store.apply(decide)


def resolve_bearer(store: AccountStore, token: str, *, now: datetime) -> Principal:
    """Resolve a raw bearer token to a principal.

    Unknown, revoked, and expired tokens fail. The account id on the principal
    is the credential's account, not a caller-supplied id.
    """

    moment = _aware(now, "now")
    if moment is None:
        raise ValueError("now must be timezone-aware")
    if not isinstance(token, str) or token == "" or token != token.strip():
        raise AuthenticationFailed("unknown")
    found = store.credential_by_hash(hash_token(token))
    if found is None or not _hash_matches(found.token_hash, hash_token(token)):
        raise AuthenticationFailed("unknown")
    if found.revoked:
        raise AuthenticationFailed("revoked")
    if found.expires_at is not None:
        expires_at = found.expires_at
        if expires_at.tzinfo is None or expires_at.tzinfo.utcoffset(expires_at) is None:
            raise AuthenticationFailed("unknown")
        if expires_at.astimezone(timezone.utc) <= moment:
            raise AuthenticationFailed("expired")
    return Principal(
        account_id=found.account_id,
        agent_id=found.agent_id,
        credential_id=found.credential_id,
        scopes=frozenset(found.scopes),
    )


def ensure_owner(principal: Principal) -> Principal:
    """Allow account management only for an owner principal."""

    _require_principal(principal)
    if principal.agent_id is not None or Scope.OWNER_BILLING not in principal.scopes:
        raise Forbidden("Owner credential required.")
    return principal


def account_for_credit_read(principal: Principal) -> str:
    """Return the account whose credits this principal may read."""

    _require_credit_scope(principal, "Credential cannot read credits.")
    return principal.account_id


def account_for_credit_deposit(principal: Principal) -> str:
    """Return the account an owner may deposit into. Agents cannot deposit."""

    ensure_owner(principal)
    return principal.account_id


def account_for_credit_debit(principal: Principal) -> str:
    """Return the account whose credits this principal may spend."""

    _require_credit_scope(principal, "Credential cannot debit credits.")
    return principal.account_id


def _require_credit_scope(principal: Principal, message: str) -> None:
    _require_principal(principal)
    if principal.scopes.isdisjoint(_CREDIT_SCOPES):
        raise Forbidden(message)


def _require_principal(principal: Principal) -> None:
    if not isinstance(principal, Principal):
        raise TypeError("principal must be a Principal")
    if not isinstance(principal.account_id, str) or principal.account_id == "":
        raise TypeError("principal account_id must be a non-empty string")


def _issue(
    state: AccountState,
    *,
    account_id: str,
    agent_id: str | None,
    scopes: frozenset[str],
    expires_at: datetime | None,
) -> tuple[AccountState, IssuedCredential]:
    secret = _new_secret()
    token_hash = hash_token(secret)
    if not _is_sha256_hex(token_hash) or token_hash == secret:
        raise RuntimeError("token hash is not a sha256 digest")
    if _hash_exists(state, token_hash):
        raise RuntimeError("credential hash collision")
    credential_id = _new_id("cred")
    if credential_id in state.credentials:
        raise RuntimeError("credential id collision")
    credential = Credential(
        credential_id=credential_id,
        account_id=account_id,
        agent_id=agent_id,
        token_hash=token_hash,
        scopes=scopes,
        expires_at=expires_at,
        revoked=False,
    )
    credentials = dict(state.credentials)
    credentials[credential_id] = credential
    updated = AccountState(accounts=state.accounts, agents=state.agents, credentials=credentials)
    issued = IssuedCredential(
        account_id=account_id,
        agent_id=agent_id,
        credential_id=credential_id,
        secret=secret,
        scopes=scopes,
    )
    return updated, issued


def _hash_exists(state: AccountState, token_hash: str) -> bool:
    return any(
        _hash_matches(credential.token_hash, token_hash)
        for credential in state.credentials.values()
    )


def _hash_matches(stored: str, presented: str) -> bool:
    if len(stored) != len(presented):
        return False
    return hmac.compare_digest(stored, presented)


def _is_sha256_hex(value: str) -> bool:
    return len(value) == 64 and all(character in _HEX for character in value)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(16)}"


def _new_secret() -> str:
    return f"omcp_{secrets.token_urlsafe(32)}"


def _optional_id(value: str | None, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or value == "" or value != value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _normalize_scopes(scopes: Iterable[str], *, agent_id: str | None) -> frozenset[str]:
    if isinstance(scopes, (str, bytes)) or not isinstance(scopes, Iterable):
        raise ValueError("scopes must be a set of scope names")
    try:
        parsed = frozenset(Scope(scope) for scope in scopes)
    except ValueError as exc:
        raise ValueError("unknown scope") from exc
    allowed = _AGENT_SCOPES if agent_id is not None else _OWNER_SCOPES
    if not parsed or not parsed <= allowed:
        raise ValueError("scopes are not valid for this credential")
    return frozenset(scope.value for scope in parsed)


def _aware(value: datetime | None, label: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise ValueError(f"{label} must be a datetime")
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(timezone.utc)
