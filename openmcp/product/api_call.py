"""One POST for every API-key query.

The provider credential is read from the environment at call time. It is not logged,
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
        headers = self._headers(row, key)
        payload = row["payload"]
        tavily_rate = None
        firecrawl_rate = None
        if service.adapter == "exa":
            from openmcp.integrations.exa.protocol import prepare

            try:
                payload, headers["x-api-key"] = prepare(
                    service.endpoint_id, service.url, service.mode, payload, key
                )
                headers.pop("Authorization")
            except ValueError as exc:
                raise TerminalFailure(str(exc)) from exc
        if service.adapter == "firecrawl":
            from openmcp.integrations.firecrawl.protocol import (
                DEFAULT_CREDIT_COST_MICROUSD,
                credit_rate,
                prepare,
            )

            try:
                firecrawl_rate = credit_rate(
                    os.environ.get(
                        "FIRECRAWL_CREDIT_COST_MICROUSD", str(DEFAULT_CREDIT_COST_MICROUSD)
                    )
                )
                payload, headers["Authorization"] = prepare(
                    service.endpoint_id, service.url, service.mode, payload, key
                )
            except ValueError as exc:
                raise TerminalFailure(str(exc)) from exc
        if service.adapter == "tavily":
            from openmcp.integrations.tavily.protocol import (
                DEFAULT_CREDIT_COST_MICROUSD,
                credit_rate,
                prepare,
            )

            try:
                tavily_rate = credit_rate(
                    os.environ.get("TAVILY_CREDIT_COST_MICROUSD", str(DEFAULT_CREDIT_COST_MICROUSD))
                )
                payload, headers["Authorization"] = prepare(
                    service.endpoint_id, service.url, service.mode, payload, key
                )
            except ValueError as exc:
                raise TerminalFailure(str(exc)) from exc
        if service.adapter == "dataforseo":
            from openmcp.integrations.dataforseo.protocol import prepare

            try:
                payload, headers["Authorization"] = prepare(
                    service.endpoint_id, service.url, service.mode, payload, key
                )
            except ValueError as exc:
                raise TerminalFailure(str(exc)) from exc
        body = canonical(payload)
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
            response = await self._post(service, body, headers)
            data = self._object(response, require_success=service.adapter != "dataforseo")
        except TerminalFailure:
            raise
        except Exception as exc:
            raise TerminalFailure("Provider request failed after it was sent.") from exc
        receipt = {"method": "api_key", "status": "success"}
        cost = None
        if service.adapter == "exa":
            from openmcp.integrations.exa.protocol import parse

            try:
                data, receipt, cost = parse(service.endpoint_id, row["payload"], data)
            except (ValueError, TypeError, KeyError) as exc:
                raise TerminalFailure("Exa result or cost estimate needs review.") from exc
        if service.adapter == "firecrawl":
            from openmcp.integrations.firecrawl.protocol import parse

            try:
                data, receipt, cost = parse(
                    service.endpoint_id, row["payload"], data, firecrawl_rate
                )
            except (ValueError, TypeError, KeyError) as exc:
                raise TerminalFailure("Firecrawl result or credit usage needs review.") from exc
        if service.adapter == "tavily":
            from openmcp.integrations.tavily.protocol import Rejected, parse

            try:
                data, receipt, cost = parse(row["payload"], data, tavily_rate, service.endpoint_id)
            except Rejected as exc:
                self.store.finish(row["execution_id"], refund_reason=str(exc))
                return
            except (ValueError, TypeError, KeyError) as exc:
                raise TerminalFailure("Tavily result or credit usage needs review.") from exc
        if service.adapter == "dataforseo":
            from openmcp.integrations.dataforseo.protocol import Rejected, parse

            try:
                data, receipt, cost = parse(service.endpoint_id, service.mode, row["payload"], data)
            except Rejected as exc:
                # An explicit vendor rejection with zero reported cost is conclusive.
                self.store.finish(row["execution_id"], refund_reason=str(exc))
                return
            except (ValueError, TypeError, KeyError) as exc:
                raise TerminalFailure("DataForSEO task or result needs review.") from exc
            if not response.is_success:
                raise TerminalFailure("DataForSEO returned an inconsistent HTTP status.")
        # Save the result together with the receipt. A crash before finish can then
        # recover without submitting another paid API task.
        self.store.mark_paid(row["execution_id"], receipt, data=data, cost_microusd=cost)
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
            # aiter_bytes() already decoded compression. Reusing Content-Encoding
            # would make the new response decompress these plain bytes again.
            headers = response.headers.copy()
            headers.pop("content-encoding", None)
            headers.pop("content-length", None)
            return httpx.Response(response.status_code, headers=headers, content=bytes(content))

    @staticmethod
    def _object(response, *, require_success=True):
        if require_success and not response.is_success:
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
