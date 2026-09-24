"""Token-only local observer API used by the live ``/demo`` page."""

from __future__ import annotations

import re
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse

from openmcp.config import Settings
from openmcp.models import OpenMCPError, ResetRequest

START_COMMAND = "uv run python -m scripts.run_demo"
_LOCAL_HOST = re.compile(r"^(?:127\.0\.0\.1|localhost)(?::[0-9]{1,5})?$", re.IGNORECASE)
_RECEIPT_FIELDS = {
    "method",
    "status",
    "reference",
    "chain_id",
    "timestamp",
    "explorer_url",
}
_SENSITIVE_KEYS = {
    "api_token",
    "authorization",
    "challenge",
    "credential",
    "header",
    "header_name",
    "incoming_credential",
    "openmcp_api_token",
    "openmcp_mpp_secret",
    "payment_authorization",
    "payment_secret",
    "private_key",
    "secret",
}


def _error_response(status: int, code: str, message: str, *, retryable: bool = False):
    return JSONResponse(
        {"error": {"code": code, "message": message, "retryable": retryable}},
        status_code=status,
    )


class DemoSafetyMiddleware:
    """Reject non-local hosts and browser-triggerable mutation requests."""

    def __init__(self, app: Any):
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", ()))
        host = headers.get(b"host", b"").decode("latin-1")
        if not _LOCAL_HOST.fullmatch(host):
            await _error_response(
                400,
                "invalid_host",
                "The demo runner only accepts localhost requests.",
            )(scope, receive, send)
            return

        if scope["method"] not in {"GET", "HEAD", "OPTIONS"}:
            if headers.get(b"x-openmcp-demo") != b"1":
                await _error_response(
                    403,
                    "demo_header_required",
                    "Send X-OpenMCP-Demo: 1 for demo actions.",
                )(scope, receive, send)
                return
            content_type = headers.get(b"content-type", b"").decode("latin-1")
            if content_type.partition(";")[0].strip().lower() != "application/json":
                await _error_response(
                    415,
                    "json_required",
                    "Demo actions require an application/json request body.",
                )(scope, receive, send)
                return

        await self.app(scope, receive, send)


def _public_receipt(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {key: _public_value(item) for key, item in value.items() if key in _RECEIPT_FIELDS}


def _public_value(value: Any) -> Any:
    """Copy gateway data while removing credentials and serialized receipt headers."""

    if isinstance(value, list):
        return [_public_value(item) for item in value]
    if not isinstance(value, dict):
        return value

    result: dict[str, Any] = {}
    for raw_key, item in value.items():
        key = str(raw_key)
        normalized = key.lower()
        if (
            normalized in _SENSITIVE_KEYS
            or normalized.endswith("_credential")
            or normalized.endswith("_private_key")
            or normalized.endswith("_secret")
        ):
            continue
        if normalized in {
            "agent_to_openmcp",
            "incoming_receipt",
            "openmcp_to_provider",
            "outgoing_receipt",
            "receipt",
        }:
            result[key] = _public_receipt(item)
        else:
            result[key] = _public_value(item)
    return result


def _gateway_unavailable() -> OpenMCPError:
    return OpenMCPError(
        "gateway_unavailable",
        f"OpenMCP gateway is unavailable. Start the local stack with `{START_COMMAND}`.",
        503,
        True,
    )


def _invalid_gateway_response() -> OpenMCPError:
    return OpenMCPError(
        "invalid_gateway_response",
        "OpenMCP returned an invalid response. Restart the local demo stack.",
        502,
        True,
    )


class DemoRunner:
    """Read dashboard state and forward resets without loading a signing wallet."""

    def __init__(self, http: httpx.AsyncClient):
        self.http = http

    @staticmethod
    async def _gateway(operation):
        try:
            return await operation
        except OpenMCPError:
            raise
        except httpx.HTTPError as exc:
            raise _gateway_unavailable() from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise _invalid_gateway_response() from exc

    @staticmethod
    def _result(response: httpx.Response) -> Any:
        if response.is_error:
            try:
                error = response.json()["error"]
                code = error["code"]
                message = error["message"]
                retryable = error.get("retryable", False)
                if (
                    not isinstance(code, str)
                    or not isinstance(message, str)
                    or not isinstance(retryable, bool)
                ):
                    raise TypeError
            except (KeyError, TypeError, ValueError):
                raise OpenMCPError(
                    "http_error",
                    f"OpenMCP returned HTTP {response.status_code}",
                    response.status_code,
                )
            raise OpenMCPError(code, message, response.status_code, retryable)
        return response.json()

    async def _gateway_json(self, operation) -> dict[str, Any]:
        response = await self._gateway(operation)
        try:
            result = self._result(response)
        except OpenMCPError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise _invalid_gateway_response() from exc
        if not isinstance(result, dict):
            raise _invalid_gateway_response()
        return result

    async def state(self, include_chain: bool) -> dict[str, Any]:
        dashboard = await self._gateway_json(
            self.http.get("/dashboard", params={"include_chain": include_chain})
        )
        if not isinstance(dashboard.get("agent"), dict) or not isinstance(
            dashboard.get("transactions"), list
        ):
            raise _invalid_gateway_response()
        return _public_value({"dashboard": dashboard})

    async def reset(self, budget_cents: int | None) -> dict[str, Any]:
        body = {} if budget_cents is None else {"budget_cents": budget_cents}
        result = await self._gateway_json(self.http.post("/demo/reset", json=body))
        if not isinstance(result.get("session_id"), str) or not result["session_id"]:
            raise _invalid_gateway_response()
        return _public_value(result)


def create_app(
    settings: Settings | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    """Create the token-only observer without reading any wallet files."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        resolved = settings or Settings()
        http = httpx.AsyncClient(
            base_url=resolved.base_url,
            headers={"Authorization": f"Bearer {resolved.api_token.get_secret_value()}"},
            timeout=150,
            transport=transport,
        )
        runner = DemoRunner(http)
        app.state.demo_runner = runner
        try:
            yield
        finally:
            app.state.demo_runner = None
            await http.aclose()

    app = FastAPI(title="OpenMCP local demo observer", version="0.2.0", lifespan=lifespan)
    app.state.demo_runner = None
    app.add_middleware(DemoSafetyMiddleware)

    @app.exception_handler(OpenMCPError)
    async def domain_error(_request: Request, exc: OpenMCPError):
        return JSONResponse({"error": exc.as_dict()}, status_code=exc.status)

    def runtime(request: Request) -> DemoRunner:
        runner = request.app.state.demo_runner
        if not isinstance(runner, DemoRunner):
            raise OpenMCPError(
                "runner_unavailable",
                f"Demo runner is starting. Retry or run `{START_COMMAND}`.",
                503,
                True,
            )
        return runner

    @app.get("/health")
    async def health():
        return {"status": "ok", "scope": "local_demo_only"}

    @app.get("/state")
    async def state(
        request: Request,
        chain: int = Query(default=0, ge=0, le=1),
    ):
        return await runtime(request).state(bool(chain))

    @app.post("/reset")
    async def reset(request: Request, body: ResetRequest | None = None):
        return await runtime(request).reset(body.budget_cents if body is not None else None)

    return app


app = create_app()
