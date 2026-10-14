"""Journal one bounded provider call; adapters own vendor transport and billing rules."""

import asyncio
import logging
import os

import httpx
from pydantic import ValidationError

from openmcp.integrations.registry import adapter
from openmcp.integrations.transport import Rejected

from .config import Service, validate_service_url
from .models import ProductError, canonical
from .settlement import TerminalFailure

_MAX_RESPONSE_BYTES = 1_000_000
log = logging.getLogger(__name__)


class _RequestLogFilter(logging.Filter):
    def filter(self, record):
        if isinstance(record.args, tuple):
            record.args = tuple(
                value.copy_with(query=None) if isinstance(value, httpx.URL) else value
                for value in record.args
            )
        return True


class ApiKeyCaller:
    def __init__(self, settings, store, *, transport=None):
        self.settings, self.store = settings, store
        http_log = logging.getLogger("httpx")
        if not any(isinstance(f, _RequestLogFilter) for f in http_log.filters):
            http_log.addFilter(_RequestLogFilter())
        self._limits = {}
        self.http = httpx.AsyncClient(
            timeout=settings.provider_timeout, transport=transport, follow_redirects=False
        )

    async def close(self):
        await self.http.aclose()

    async def purchase(self, row):
        if row.get("payment_status") == "confirmed":
            return
        if row.get("payment_status") == "sent":
            raise TerminalFailure("API-key request was already sent and needs review.")
        try:
            service = Service.model_validate(row["service"])
            validate_service_url(service.url, service.mode)
        except (ValidationError, ValueError) as exc:
            raise TerminalFailure("Provider URL or adapter is not allowed.") from exc
        secret_ref = self.store.provider_secret_ref(service.endpoint_id)
        key = os.environ.get(secret_ref, "") if secret_ref else ""
        if not key:
            raise TerminalFailure("Provider API key is not configured.")
        implementation = adapter(service.adapter)
        try:
            request = await implementation.prepare(
                service, row["payload"], key, self.http, self.settings.provider_timeout
            )
            validate_service_url(request.url, service.mode)
            request.headers = {
                "Content-Type": "application/json",
                "Idempotency-Key": row["execution_id"],
                "X-OpenMCP-Execution-ID": row["execution_id"],
                **request.headers,
            }
        except (ValueError, httpx.HTTPError, TimeoutError) as exc:
            raise TerminalFailure("Provider input or credentials could not be validated.") from exc
        try:
            self.store.mark_sent(row["execution_id"])
        except ProductError as exc:
            current = self.store.execution_internal(row["execution_id"])
            if current and current["payment_status"] == "sent":
                raise TerminalFailure("API-key request was already sent and needs review.") from exc
            raise
        try:
            response = await self._send(service.adapter, implementation, request)
            data = self._object(response, require_success=request.require_success)
            data, receipt, cost = implementation.parse(
                service, row["payload"], response, data, request.context
            )
        except Rejected as exc:
            # Only adapters with conclusive zero-cost evidence can release a sent request.
            self.store.finish(row["execution_id"], refund_reason=str(exc))
            return
        except TerminalFailure:
            raise
        except Exception as exc:
            log.warning(
                "Provider response failure execution_id=%s error=%s",
                row["execution_id"],
                type(exc).__name__,
            )
            raise TerminalFailure("Provider request or billing outcome needs review.") from exc
        # Persist data with the receipt before capture, so a restart never calls upstream twice.
        self.store.mark_paid(row["execution_id"], receipt, data=data, cost_microusd=cost)
        self.store.finish(row["execution_id"], data=data)

    async def _send(self, name, implementation, request):
        interval = getattr(implementation, "MIN_INTERVAL", 0)
        if not interval:
            return await self._request(request)
        lock, _ = self._limits.setdefault(name, (asyncio.Lock(), 0.0))
        async with lock:
            loop = asyncio.get_running_loop()
            await asyncio.sleep(max(0, self._limits[name][1] - loop.time()))
            try:
                return await self._request(request)
            finally:
                self._limits[name] = (lock, loop.time() + interval)

    async def _request(self, request):
        async with self.http.stream(request.method, request.url, **request.options()) as response:
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > _MAX_RESPONSE_BYTES:
                    raise TerminalFailure("Provider response exceeded the maximum size.")
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
        except (ValueError, TypeError) as exc:
            raise TerminalFailure(
                "Provider returned an unusable result after the request was sent."
            ) from exc
        return data
