"""Organization-authenticated v2 onboarding. No money movement or automatic retries."""

import asyncio
import re
import time
from collections.abc import Callable

import httpx
from pydantic import BaseModel, SecretStr, ValidationError

from .config import AgentCardSettings
from .models import (
    AccessToken,
    AgentCardError,
    ConnectAttempt,
    Connection,
    ConnectionTokens,
    CredentialIdentity,
    VerificationStatus,
)

API_ORIGIN = "https://api.agentcard.sh"


class AgentCardClient:
    def __init__(
        self,
        settings: AgentCardSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.settings = settings
        self._clock = clock
        self._http = httpx.AsyncClient(
            base_url=API_ORIGIN,
            timeout=settings.timeout_seconds,
            transport=transport,
            follow_redirects=False,
            trust_env=False,
        )
        self._auth_lock = asyncio.Lock()
        self._token: AccessToken | None = None
        self._identity: CredentialIdentity | None = None
        self._expires_at = 0.0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def close(self):
        await self._http.aclose()
        self._token = None
        self._identity = None

    @staticmethod
    def _parse(model: type[BaseModel], data: dict, *, mutation: bool = False):
        try:
            return model.model_validate(data)
        except ValidationError:
            # Pydantic errors include input values; do not surface tokens from them.
            raise AgentCardError("invalid_response", outcome_unknown=mutation) from None

    async def _send(self, method: str, path: str, **kwargs) -> dict:
        mutation = method != "GET"
        try:
            response = await self._http.request(method, path, **kwargs)
        except httpx.RequestError:
            raise AgentCardError("transport_error", outcome_unknown=mutation) from None
        if not response.is_success:
            code = "http_error"
            try:
                error = response.json().get("error")
                candidate = error.get("code") if isinstance(error, dict) else error
                if isinstance(candidate, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,79}", candidate):
                    code = candidate
            except (ValueError, AttributeError):
                pass
            raise AgentCardError(
                code,
                status=response.status_code,
                outcome_unknown=mutation
                and (response.status_code >= 500 or response.status_code == 408),
            )
        try:
            data = response.json()
        except ValueError:
            raise AgentCardError("invalid_response", outcome_unknown=mutation) from None
        if not isinstance(data, dict):
            raise AgentCardError("invalid_response", outcome_unknown=mutation)
        return data

    async def _authorize(self) -> str:
        async with self._auth_lock:
            if self._token and self._clock() < self._expires_at:
                return self._token.access_token.get_secret_value()
            self._token = None
            self._identity = None
            started = self._clock()
            token = self._parse(
                AccessToken,
                await self._send(
                    "POST",
                    "/api/v2/oauth/token",
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self.settings.client_id,
                        "client_secret": self.settings.client_secret.get_secret_value(),
                    },
                ),
            )
            bearer = token.access_token.get_secret_value()
            identity = self._parse(
                CredentialIdentity,
                await self._send(
                    "GET",
                    "/api/v2",
                    headers={"Authorization": f"Bearer {bearer}"},
                ),
            )
            if identity.test_mode != self.settings.test_mode:
                raise AgentCardError("mode_mismatch")
            self._identity = identity
            self._token = token
            self._expires_at = started + token.expires_in - min(30, token.expires_in / 10)
            return bearer

    async def check_credentials(self) -> CredentialIdentity:
        """Read-only connection diagnostic; mode comes from the credential, not a host."""
        await self._authorize()
        assert self._identity is not None
        return self._identity.model_copy()

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        token = await self._authorize()
        try:
            return await self._send(
                method, path, headers={"Authorization": f"Bearer {token}"}, **kwargs
            )
        except AgentCardError as exc:
            if exc.status == 401:
                # Future calls re-authenticate. This call is never replayed implicitly.
                if self._token and self._token.access_token.get_secret_value() == token:
                    self._token = None
            raise

    async def start_connection(
        self,
        *,
        email: str | None = None,
        phone: str | None = None,
        external_user_id: str | None = None,
    ) -> ConnectAttempt:
        if bool(email) == bool(phone):
            raise ValueError("Provide exactly one email or phone")
        body = {"email": email} if email else {"phone": phone}
        if external_user_id is not None:
            if not 1 <= len(external_user_id) <= 255:
                raise ValueError("external_user_id must contain 1–255 characters")
            body["external_user_id"] = external_user_id
        return self._parse(
            ConnectAttempt,
            await self._request(
                "POST",
                "/api/v2/connect/start",
                json=body,
            ),
            mutation=True,
        )

    async def verify_connection(self, connect_id: str, code: str) -> Connection:
        return self._parse(
            Connection,
            await self._request(
                "POST",
                "/api/v2/connect/verify",
                json={"connect_id": connect_id, "code": code},
            ),
            mutation=True,
        )

    async def refresh_connection(self, refresh_token: SecretStr) -> ConnectionTokens:
        """Caller must serialize per connection and atomically persist the rotated pair.

        Never automatically replay a timed-out refresh: reuse can revoke the connection.
        """
        return self._parse(
            ConnectionTokens,
            await self._request(
                "POST",
                "/api/v2/connect/refresh",
                json={"refresh_token": refresh_token.get_secret_value()},
            ),
            mutation=True,
        )

    async def record_consent(self, user_id: str) -> None:
        """Call only after the application has captured the user's consent."""
        await self._request("POST", "/api/v2/connect/consent", json={"user_id": user_id})

    async def verification_status(self, user_id: str) -> VerificationStatus:
        return self._parse(
            VerificationStatus,
            await self._request(
                "GET",
                "/api/v2/kyc",
                params={"user_id": user_id},
            ),
        )
