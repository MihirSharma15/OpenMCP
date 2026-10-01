"""In-memory accounts, agents, and hashed credentials."""

import threading
from collections.abc import Callable
from typing import TypeVar

from openmcp.ports.accounts import AccountState, Credential

T = TypeVar("T")


class MemoryAccounts:
    """Process-local ``AccountStore``. The lock covers each decision and lookup."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = AccountState()

    def apply(self, decide: Callable[[AccountState], tuple[AccountState, T]]) -> T:
        with self._lock:
            updated, result = decide(self._state)
            if not isinstance(updated, AccountState):
                raise TypeError("decide must return an AccountState")
            self._state = updated
            return result

    def credential_by_hash(self, token_hash: str) -> Credential | None:
        if not isinstance(token_hash, str) or token_hash == "":
            return None
        with self._lock:
            for credential in self._state.credentials.values():
                if credential.token_hash == token_hash:
                    return credential
            return None
