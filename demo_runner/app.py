"""Wallet-owning local runner used only by the live ``/demo`` page."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable
from contextlib import asynccontextmanager
from typing import Any, Literal, TypeVar

import httpx
from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from openmcp.agent import Agent
from openmcp.config import Settings
from openmcp.models import ExecuteRequest, OpenMCPError

DEMO_QUERY = "FreightFlow operational health, legal liabilities and competitor market share"
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
T = TypeVar("T")


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


class EmptyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["all", "next"]


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
    """Own one agent wallet client and serialize local demo commands."""

    def __init__(self, settings: Settings, agent: Agent, *, owns_agent: bool):
        self.settings = settings
        self.agent = agent
        self.owns_agent = owns_agent
        self._lock = asyncio.Lock()
        self._discovery_lock = asyncio.Lock()
        self._discovery: dict[str, Any] | None = None
        self._session_id: str | None = None
        self._job_task: asyncio.Task[None] | None = None
        self._purchase_task: asyncio.Task[dict[str, Any]] | None = None
        self._status: Literal["idle", "running", "pausing"] = "idle"
        self._mode: Literal["all", "next"] | None = None
        self._current_endpoint: str | None = None
        self._pause_requested = False
        self._last_error: dict[str, Any] | None = None

    async def close(self) -> None:
        async with self._lock:
            task = self._job_task
            if task is not None and not task.done():
                self._pause_requested = True
                self._status = "pausing"
        if task is not None and not task.done():
            await task
        if self.owns_agent:
            await self.agent.close()

    def _job_unlocked(self) -> dict[str, Any]:
        return {
            "status": self._status,
            "mode": self._mode,
            "current_endpoint": self._current_endpoint,
            "last_error": self._last_error,
        }

    async def job(self) -> dict[str, Any]:
        async with self._lock:
            return _public_value(self._job_unlocked())

    @staticmethod
    async def _gateway(operation: Awaitable[T]) -> T:
        try:
            return await operation
        except OpenMCPError:
            raise
        except httpx.HTTPError as exc:
            raise _gateway_unavailable() from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise _invalid_gateway_response() from exc

    async def _gateway_json(self, operation: Awaitable[httpx.Response]) -> dict[str, Any]:
        response = await self._gateway(operation)
        try:
            result = Agent.result(response)
        except OpenMCPError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise _invalid_gateway_response() from exc
        if not isinstance(result, dict):
            raise _invalid_gateway_response()
        return result

    async def _observe_session(self, session_id: Any) -> str:
        if not isinstance(session_id, str) or not session_id:
            raise _invalid_gateway_response()
        async with self._lock:
            if session_id != self._session_id:
                self._session_id = session_id
                if self._discovery is not None and self._discovery.get("session_id") != session_id:
                    self._discovery = None
        return session_id

    async def state(self, after: int, include_chain: bool) -> dict[str, Any]:
        # If a job finishes while the gateway reads are in flight, read once more
        # so an "idle" response cannot carry a pre-completion dashboard.
        for attempt in range(2):
            async with self._lock:
                task_before = self._job_task
                status_before = self._status
            dashboard, event_page = await asyncio.gather(
                self._gateway_json(
                    self.agent.http.get("/dashboard", params={"include_chain": include_chain})
                ),
                self._gateway_json(self.agent.http.get("/events", params={"after": after})),
            )
            agent_state = dashboard.get("agent")
            if not isinstance(agent_state, dict):
                raise _invalid_gateway_response()
            await self._observe_session(agent_state.get("session_id"))
            events = event_page.get("events")
            next_cursor = event_page.get("next_cursor")
            if not isinstance(events, list) or not isinstance(next_cursor, int):
                raise _invalid_gateway_response()
            async with self._lock:
                changed = task_before is not self._job_task or status_before != self._status
                if attempt == 0 and changed:
                    continue
                result = {
                    "dashboard": dashboard,
                    "events": events,
                    "next_cursor": next_cursor,
                    "discovery": self._discovery,
                    "job": self._job_unlocked(),
                }
            return _public_value(result)
        raise RuntimeError("unreachable")

    async def discover(self) -> dict[str, Any]:
        async with self._discovery_lock:
            discovery = await self._gateway(
                self.agent.discover(DEMO_QUERY, self.settings.budget_cents)
            )
            if not isinstance(discovery, dict):
                raise _invalid_gateway_response()
            session_id = await self._observe_session(discovery.get("session_id"))
            if discovery.get("session_id") != session_id:
                raise _invalid_gateway_response()
            async with self._lock:
                self._discovery = discovery
            return _public_value(discovery)

    async def _ensure_discovery(self) -> dict[str, Any]:
        balance = await self._gateway(self.agent.balance())
        if not isinstance(balance, dict):
            raise _invalid_gateway_response()
        session_id = await self._observe_session(balance.get("session_id"))
        async with self._lock:
            discovery = self._discovery
        if discovery is not None and discovery.get("session_id") == session_id:
            return discovery
        return await self.discover()

    async def start(self, mode: Literal["all", "next"]) -> dict[str, Any]:
        async with self._lock:
            if self._status != "idle" or (self._job_task is not None and not self._job_task.done()):
                raise OpenMCPError(
                    "job_running",
                    "A demo purchase job is already running.",
                    409,
                    True,
                )
            self._pause_requested = False
            self._status = "running"
            self._mode = mode
            self._current_endpoint = None
            self._last_error = None
            self._job_task = asyncio.create_task(
                self._run_job(mode),
                name=f"openmcp-demo-{mode}",
            )
            return _public_value(self._job_unlocked())

    async def pause(self) -> dict[str, Any]:
        async with self._lock:
            if self._status in {"running", "pausing"}:
                self._pause_requested = True
                self._status = "pausing"
            return _public_value(self._job_unlocked())

    async def reset(self) -> dict[str, Any]:
        # Keep this lock through the gateway reset so a run cannot start in between
        # the local idle check and the new gateway session becoming active.
        async with self._discovery_lock:
            async with self._lock:
                if self._status != "idle" or (
                    self._job_task is not None and not self._job_task.done()
                ):
                    raise OpenMCPError(
                        "job_running",
                        "Pause and wait for the current purchase before resetting.",
                        409,
                        True,
                    )
                result = await self._gateway_json(self.agent.http.post("/demo/reset", json={}))
                session_id = result.get("session_id")
                if not isinstance(session_id, str) or not session_id:
                    raise _invalid_gateway_response()
                self._session_id = session_id
                self._discovery = None
                self._last_error = None
                self._mode = None
                return _public_value(result)

    async def _completed_endpoint_ids(self) -> set[str]:
        dashboard = await self._gateway_json(
            self.agent.http.get("/dashboard", params={"include_chain": False})
        )
        transactions = dashboard.get("transactions")
        if not isinstance(transactions, list):
            raise _invalid_gateway_response()
        return {
            transaction["endpoint_id"]
            for transaction in transactions
            if isinstance(transaction, dict)
            and transaction.get("status") == "completed"
            and isinstance(transaction.get("endpoint_id"), str)
        }

    async def _same_session(self, expected: str) -> None:
        balance = await self._gateway(self.agent.balance())
        if not isinstance(balance, dict):
            raise _invalid_gateway_response()
        actual = await self._observe_session(balance.get("session_id"))
        if actual != expected:
            raise OpenMCPError(
                "session_changed",
                "The demo session changed. Run again to rediscover before purchasing.",
                409,
                True,
            )

    @staticmethod
    def _safe_job_error(exc: Exception) -> dict[str, Any]:
        if isinstance(exc, OpenMCPError):
            return exc.as_dict()
        if isinstance(exc, httpx.HTTPError):
            return _gateway_unavailable().as_dict()
        return {
            "code": "runner_error",
            "message": "The demo runner could not complete the purchase. Retry the same run.",
            "retryable": True,
        }

    async def _run_job(self, mode: Literal["all", "next"]) -> None:
        try:
            discovery = await self._ensure_discovery()
            session_id = discovery.get("session_id")
            endpoints = discovery.get("endpoints")
            if not isinstance(session_id, str) or not isinstance(endpoints, list):
                raise _invalid_gateway_response()
            completed = await self._completed_endpoint_ids()
            remaining = [
                endpoint
                for endpoint in endpoints
                if isinstance(endpoint, dict)
                and isinstance(endpoint.get("endpoint_id"), str)
                and endpoint["endpoint_id"] not in completed
            ]
            if mode == "next":
                remaining = remaining[:1]

            for endpoint in remaining:
                endpoint_id = endpoint["endpoint_id"]
                price_cents = endpoint.get("price_cents")
                if not isinstance(price_cents, int):
                    raise _invalid_gateway_response()
                await self._same_session(session_id)
                request = ExecuteRequest(
                    session_id=session_id,
                    endpoint_id=endpoint_id,
                    payload={"company": "FreightFlow"},
                    idempotency_key=f"demo-{session_id}-{endpoint_id}",
                    max_price_cents=price_cents,
                    budget_cents=self.settings.budget_cents,
                )

                # Checking pause, publishing the in-flight endpoint, and creating
                # the execute task are atomic with respect to POST /pause.
                async with self._lock:
                    if self._pause_requested:
                        break
                    self._current_endpoint = endpoint_id
                    purchase = asyncio.create_task(
                        self.agent.execute(request),
                        name=f"openmcp-purchase-{endpoint_id}",
                    )
                    self._purchase_task = purchase
                try:
                    await self._gateway(purchase)
                finally:
                    async with self._lock:
                        self._purchase_task = None
                        self._current_endpoint = None

                async with self._lock:
                    if self._pause_requested:
                        break
        except Exception as exc:
            async with self._lock:
                self._last_error = self._safe_job_error(exc)
        finally:
            async with self._lock:
                self._current_endpoint = None
                self._purchase_task = None
                self._pause_requested = False
                self._status = "idle"
                self._mode = None


def create_app(settings: Settings | None = None, agent: Agent | None = None) -> FastAPI:
    """Create the app without reading settings or wallet files until startup."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        resolved = settings or Settings()
        resolved_agent = agent or Agent(resolved)
        runner = DemoRunner(resolved, resolved_agent, owns_agent=agent is None)
        app.state.demo_runner = runner
        try:
            yield
        finally:
            await runner.close()
            app.state.demo_runner = None

    app = FastAPI(title="OpenMCP local demo runner", version="0.1.0", lifespan=lifespan)
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
        after: int = Query(default=0, ge=0),
        chain: int = Query(default=0, ge=0, le=1),
    ):
        return await runtime(request).state(after, bool(chain))

    @app.post("/discover")
    async def discover(_body: EmptyBody, request: Request):
        return await runtime(request).discover()

    @app.post("/run", status_code=202)
    async def run(body: RunBody, request: Request):
        return {"job": await runtime(request).start(body.mode)}

    @app.post("/pause")
    async def pause(_body: EmptyBody, request: Request):
        return {"job": await runtime(request).pause()}

    @app.post("/reset")
    async def reset(_body: EmptyBody, request: Request):
        return await runtime(request).reset()

    return app


app = create_app()
