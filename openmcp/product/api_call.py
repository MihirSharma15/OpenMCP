"""One bounded HTTP request for every API-key query.

The provider credential is read from the environment at call time. It is not logged,
not placed on the execution, and not taken from the catalog JSON. secret_ref
is only the variable name, looked up from the provider row.
"""

import asyncio
import json
import logging
import os

import httpx
from pydantic import ValidationError

from .config import Service, validate_service_url
from .models import ProductError, canonical
from .settlement import TerminalFailure

_MAX_RESPONSE_BYTES = 1_000_000
log = logging.getLogger(__name__)


class _RequestLogFilter(logging.Filter):
    """HTTPX logs URLs at INFO; query strings can contain provider credentials."""

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
        self._builtwith_lock = asyncio.Lock()
        self._builtwith_next = 0.0
        self.http = httpx.AsyncClient(
            timeout=settings.provider_timeout, transport=transport, follow_redirects=False
        )

    async def close(self):
        await self.http.aclose()

    async def purchase(self, row):
        # Retry must not call upstream. sent is a hold; confirmed already has a receipt.
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
        openweather_cost = None
        nansen_rate = None
        if service.adapter == "api2pdf":
            from openmcp.integrations.api2pdf.protocol import prepare

            try:
                payload, headers["Authorization"] = prepare(
                    service.endpoint_id, service.url, service.mode, payload, key
                )
            except ValueError as exc:
                raise TerminalFailure(str(exc)) from exc
        if service.adapter == "nansen":
            from openmcp.integrations.nansen.protocol import (
                DEFAULT_CREDIT_COST_MICROUSD,
                credit_rate,
                prepare,
            )

            try:
                nansen_rate = credit_rate(
                    os.environ.get("NANSEN_CREDIT_COST_MICROUSD", str(DEFAULT_CREDIT_COST_MICROUSD))
                )
                payload, headers["apikey"] = prepare(
                    service.endpoint_id, service.url, service.mode, payload, key
                )
                headers.pop("Authorization")
            except ValueError as exc:
                raise TerminalFailure(str(exc)) from exc
        if service.adapter == "builtwith":
            from openmcp.integrations.builtwith.protocol import prepare

            try:
                payload = prepare(service.endpoint_id, service.url, service.mode, payload, key)
            except ValueError as exc:
                raise TerminalFailure(str(exc)) from exc

        if service.adapter == "companies_house":
            from openmcp.integrations.companies_house.protocol import prepare

            try:
                _, _, headers["Authorization"] = prepare(
                    service.endpoint_id, service.url, service.mode, payload, key
                )
            except ValueError as exc:
                raise TerminalFailure(str(exc)) from exc
        if service.adapter == "openweather":
            from openmcp.integrations.openweather.protocol import prepare, request_cost

            try:
                openweather_cost = request_cost(
                    os.environ.get("OPENWEATHER_REQUEST_COST_MICROUSD", "0")
                )
                payload, headers["x-api-key"] = prepare(
                    service.endpoint_id, service.url, service.mode, payload, key
                )
                headers.pop("Authorization")
            except ValueError as exc:
                raise TerminalFailure(str(exc)) from exc
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
        deepgram_duration = None
        if service.adapter == "deepgram":
            from openmcp.integrations.deepgram.audio import load_audio
            from openmcp.integrations.deepgram.protocol import prepare

            hosts = {
                h.strip().lower()
                for h in os.environ.get("DEEPGRAM_AUDIO_HOSTS", "static.deepgram.com").split(",")
                if h.strip()
            }
            try:
                params, authorization = prepare(
                    service.endpoint_id, service.url, service.mode, payload, key, hosts
                )
                async with asyncio.timeout(min(self.settings.provider_timeout, 30)):
                    audio, deepgram_duration = await load_audio(
                        self.http, payload["audio_url"], hosts
                    )
            except (ValueError, httpx.HTTPError, TimeoutError) as exc:
                # No paid vendor request was sent. The worker can release the reservation.
                raise TerminalFailure("Deepgram audio input could not be validated.") from exc
            headers["Authorization"] = authorization
            headers["Content-Type"] = "audio/wav"
            body = (audio, params)
        try:
            self.store.mark_sent(row["execution_id"])
        except ProductError as exc:
            current = self.store.execution_internal(row["execution_id"])
            if current and current["payment_status"] == "sent":
                raise TerminalFailure("API-key request was already sent and needs review.") from exc
            raise
        try:
            # Same URL rule, immediately before transport. A rejection here does not send.
            validate_service_url(service.url, service.mode)
            response = await self._post(service, body, headers)
            data = self._object(
                response, require_success=service.adapter not in {"dataforseo", "nansen"}
            )
        except TerminalFailure:
            raise
        except Exception as exc:
            # Log the category, never the raw error, headers, or credentials.
            log.warning(
                "Provider response failure execution_id=%s error=%s",
                row["execution_id"],
                type(exc).__name__,
            )
            raise TerminalFailure("Provider request failed after it was sent.") from exc
        receipt = {"method": "api_key", "status": "success"}
        cost = None
        if service.adapter == "api2pdf":
            from openmcp.integrations.api2pdf.protocol import parse

            try:
                data, receipt, cost = parse(service.endpoint_id, row["payload"], data)
            except (ValueError, TypeError, KeyError) as exc:
                raise TerminalFailure("API2PDF conversion or cost needs review.") from exc
        if service.adapter == "nansen":
            from openmcp.integrations.nansen.protocol import Rejected, parse

            try:
                data, receipt, cost = parse(
                    service.endpoint_id,
                    row["payload"],
                    data,
                    response.headers,
                    response.status_code,
                    nansen_rate,
                )
            except Rejected as exc:
                self.store.finish(row["execution_id"], refund_reason=str(exc))
                return
            except (ValueError, TypeError, KeyError) as exc:
                raise TerminalFailure("Nansen result or credit usage needs review.") from exc
        if service.adapter == "builtwith":
            from openmcp.integrations.builtwith.protocol import parse

            try:
                data, receipt, cost = parse(service.endpoint_id, row["payload"], data)
            except (ValueError, TypeError, KeyError) as exc:
                raise TerminalFailure("BuiltWith result needs review.") from exc
        if service.adapter == "deepgram":
            from openmcp.integrations.deepgram.protocol import parse

            try:
                data, receipt, cost = parse(service.endpoint_id, data, deepgram_duration)
            except (ValueError, TypeError, KeyError) as exc:
                raise TerminalFailure("Deepgram transcription or duration needs review.") from exc
        if service.adapter == "companies_house":
            from openmcp.integrations.companies_house.protocol import parse

            try:
                data, receipt, cost = parse(service.endpoint_id, row["payload"], data)
            except (ValueError, TypeError, KeyError) as exc:
                raise TerminalFailure("Companies House result needs review.") from exc
        if service.adapter == "openweather":
            from openmcp.integrations.openweather.protocol import parse

            try:
                data, receipt, cost = parse(
                    service.endpoint_id, row["payload"], data, openweather_cost
                )
            except (ValueError, TypeError, KeyError) as exc:
                raise TerminalFailure("OpenWeather result needs review.") from exc
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
        if service.adapter == "builtwith":
            # Single worker deployment: serialize and space calls for the free API.
            async with self._builtwith_lock:
                loop = asyncio.get_running_loop()
                await asyncio.sleep(max(0, self._builtwith_next - loop.time()))
                try:
                    return await self._request(service, body, headers)
                finally:
                    self._builtwith_next = loop.time() + 1.0
        return await self._request(service, body, headers)

    async def _request(self, service, body, headers):
        method, options = "POST", {"content": body, "headers": headers}
        if service.adapter == "openweather":
            # Only the outgoing request gets appid; stored payloads never contain it.
            from openmcp.integrations.openweather.protocol import validate_target

            validate_target(service.endpoint_id, service.url, service.mode)
            outgoing_headers = dict(headers)
            params = json.loads(body)
            params["appid"] = outgoing_headers.pop("x-api-key")
            method, options = "GET", {"params": params, "headers": outgoing_headers}
        if service.adapter == "deepgram":
            audio, params = body
            options = {"content": audio, "params": params, "headers": headers}
        if service.adapter == "builtwith":
            params = json.loads(body)
            outgoing_headers = dict(headers)
            # Free API documents query authentication. Never store or log this URL.
            params["KEY"] = outgoing_headers.pop("Authorization").removeprefix("Bearer ")
            method, options = "GET", {"params": params, "headers": outgoing_headers}
        target = service.url
        if service.adapter == "companies_house":
            from openmcp.integrations.companies_house.protocol import request

            target, params = request(
                service.endpoint_id, service.url, service.mode, json.loads(body)
            )
            method, options = "GET", {"params": params, "headers": headers}
        async with self.http.stream(method, target, **options) as response:
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
