"""One POST for every API-key query.

The bearer token is read from the environment at call time. It is not logged,
not placed on the execution, and not taken from the catalog JSON. secret_ref
is only the variable name, looked up from the provider row.
"""

import os

import httpx
from pydantic import ValidationError

from .config import Service, validate_service_url
from .models import ProductError, canonical
from .settlement import TerminalFailure

_MAX_RESPONSE_BYTES = 1_000_000


class ApiKeyCaller:
    def __init__(self, settings, store, *, transport=None):
        self.settings, self.store = settings, store
        self.http = httpx.AsyncClient(
            timeout=settings.provider_timeout, transport=transport, follow_redirects=False
        )

    async def close(self):
        await self.http.aclose()

    async def purchase(self, row):
        # Retry must not POST. sent is a terminal hold; confirmed already has a receipt.
        if row.get("payment_status") == "confirmed":
            return
        if row.get("payment_status") == "sent":
            raise TerminalFailure("API-key request was already sent and needs review.")
        try:
            service = Service.model_validate(row["service"])
            # Catalog validation already ran. Check again before journaling or sending.
            validate_service_url(service.url, service.mode)
        except (ValidationError, ValueError) as exc:
            raise TerminalFailure("Provider URL is not allowed.") from exc
        secret_ref = self.store.provider_secret_ref(service.endpoint_id)
        key = os.environ.get(secret_ref, "") if secret_ref else ""
        if not key:
            raise TerminalFailure("Provider API key is not configured.")
        try:
            self.store.mark_sent(row["execution_id"])
        except ProductError as exc:
            current = self.store.execution_internal(row["execution_id"])
            if current and current["payment_status"] == "sent":
                raise TerminalFailure("API-key request was already sent and needs review.") from exc
            raise
        try:
            # Same URL rule, immediately before the POST. A rejection here does not send.
            validate_service_url(service.url, service.mode)
            response = await self._post(
                service, canonical(row["payload"]), self._headers(row, key)
            )
            data = self._object(response)
        except TerminalFailure:
            raise
        except Exception as exc:
            raise TerminalFailure("Provider request failed after it was sent.") from exc
        receipt = {"method": "api_key", "status": "success"}
        self.store.mark_paid(row["execution_id"], receipt)
        self.store.finish(row["execution_id"], data=data)

    @staticmethod
    def _headers(row, key):
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
            "Idempotency-Key": row["execution_id"],
            "X-OpenMCP-Execution-ID": row["execution_id"],
        }

    async def _post(self, service, body, headers):
        async with self.http.stream("POST", service.url, content=body, headers=headers) as response:
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > _MAX_RESPONSE_BYTES:
                    raise TerminalFailure("Provider response exceeded the maximum size.")
            return httpx.Response(
                response.status_code, headers=response.headers, content=bytes(content)
            )

    @staticmethod
    def _object(response):
        if not response.is_success:
            raise TerminalFailure("Provider request failed after it was sent.")
        try:
            data = response.json()
            canonical(data)
            if not isinstance(data, dict):
                raise ValueError("Not an object")
        except TerminalFailure:
            raise
        except (ValueError, TypeError) as exc:
            raise TerminalFailure(
                "Provider returned an unusable result after the request was sent."
            ) from exc
        return data
