"""Account port. Records hold a credential hash, never the raw secret."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, TypeVar

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class Account:
    """One OpenMCP account. Credits and agents belong to this id."""

    account_id: str


@dataclass(frozen=True, slots=True)
class Agent:
    """An agent owned by exactly one account."""

    agent_id: str
    account_id: str


@dataclass(frozen=True, slots=True)
class Credential:
    """A hashed bearer credential.

    ``token_hash`` is the only form of the secret this record can hold.
    ``agent_id`` is null for an owner credential.
    """

    credential_id: str
    account_id: str
    agent_id: str | None
    token_hash: str
    scopes: frozenset[str]
    expires_at: datetime | None
    revoked: bool


@dataclass(frozen=True, slots=True)
class AccountState:
    """Snapshot the domain decides against. Adapters persist the replacement."""

    accounts: Mapping[str, Account] = field(default_factory=dict)
    agents: Mapping[str, Agent] = field(default_factory=dict)
    credentials: Mapping[str, Credential] = field(default_factory=dict)


class AccountStore(Protocol):
    """Persistence for accounts, agents, and hashed credentials.

    ``apply`` runs the domain decision once while holding the adapter's lock
    (or an equivalent critical section) and then stores the returned state.
    The decision's result may include a raw secret the caller shows once.
    Adapters must not write that result, or log it.
    """

    def apply(self, decide: Callable[[AccountState], tuple[AccountState, T]]) -> T:
        """Persist the state returned by ``decide`` and return its result."""
        ...

    def credential_by_hash(self, token_hash: str) -> Credential | None:
        """Return the credential with this hash, or None when it is unknown."""
        ...
