"""Decorator-driven MPP provider application."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import re
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, get_type_hints
from urllib.parse import urlparse

from eth_utils import is_address
from fastapi import Body, FastAPI, Request
from fastapi.responses import JSONResponse, Response
from mpp import Challenge
from mpp.methods.tempo import ChargeIntent, tempo
from mpp.server import Mpp
from mpp.stores import SQLiteStore
from pydantic import BaseModel, ConfigDict, create_model

from openmcp.config import CHAIN_ID, TOKEN, load_catalog

from .payments import (
    Fulfillment,
    FulfillmentStore,
    fingerprint_for,
    hash_credential,
    load_or_create_secrets,
    memo_for,
    prepare_private_directory,
)
from .settings import ProviderSettings, resolve_provider_settings

_ROUTE = re.compile(r"^/[a-z0-9]+(?:-[a-z0-9]+)*$")
_MAX_RESPONSE_BYTES = 1_000_000


@dataclass(frozen=True, slots=True)
class ProviderTool:
    route: str
    route_id: str
    price_cents: int
    price_usd: str
    function: Callable[..., Any] | Callable[..., Awaitable[Any]]
    input_model: type[BaseModel]
    input_schema: dict[str, Any]


class OpenMCPProvider:
    """Collect payment terms and decorated provider functions."""

    def __init__(self, *, name: str, wallet: str, realm: str) -> None:
        if not name.strip():
            raise ValueError("Provider name cannot be empty")
        if not wallet.strip():
            raise ValueError("Provider wallet name cannot be empty")
        if not realm.strip():
            raise ValueError("Provider realm cannot be empty")
        self.name = name
        self.wallet = wallet
        self.realm = realm
        self._tools: dict[str, ProviderTool] = {}

    @property
    def tools(self) -> tuple[ProviderTool, ...]:
        return tuple(self._tools.values())

    def tool(
        self,
        *,
        route: str,
        price_usd: int | float | Decimal | str,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Declare the exact HTTP route and provider-hop charge."""

        if not _ROUTE.fullmatch(route):
            raise ValueError("Provider route must be one lowercase kebab-case path segment")
        price_cents = _price_to_cents(price_usd)

        def decorator(function: Callable[..., Any]) -> Callable[..., Any]:
            if route in self._tools:
                raise ValueError(f"Duplicate provider route: {route}")
            route_id = route.removeprefix("/")
            input_model = _input_model(function, route_id)
            self._tools[route] = ProviderTool(
                route=route,
                route_id=route_id,
                price_cents=price_cents,
                price_usd=f"{price_cents / 100:.2f}",
                function=function,
                input_model=input_model,
                input_schema=_clean_schema(input_model.model_json_schema()),
            )
            return function

        return decorator


@dataclass(slots=True)
class ProviderRuntime:
    settings: ProviderSettings
    receivers: dict[str, Mpp]
    fulfillments: FulfillmentStore
    locks: dict[str, asyncio.Lock]

    def lock_for(self, execution_id: str) -> asyncio.Lock:
        # The service is deliberately single-worker. Creating the lock has no await,
        # so one event-loop turn cannot race this dictionary operation.
        return self.locks.setdefault(execution_id, asyncio.Lock())


def load_public_addresses(wallets: Path) -> dict[str, str]:
    """Load only the public wallet handoff file."""

    path = wallets / "public.json"
    if not path.exists():
        raise ValueError("Run `uv run openmcp init` to create the five demo wallets")
    try:
        addresses = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Wallet public.json is unreadable or invalid") from exc
    if not isinstance(addresses, dict) or not all(
        isinstance(name, str) and isinstance(address, str) and is_address(address)
        for name, address in addresses.items()
    ):
        raise ValueError("Wallet public.json contains an invalid address")
    return addresses


def create_provider_app(
    providers: list[OpenMCPProvider] | tuple[OpenMCPProvider, ...],
    settings: object | None = None,
    intent_factory: Callable[[], Any] | None = None,
) -> FastAPI:
    """Create one side-effect-free FastAPI app for all provider routes."""

    declared = tuple(providers)
    if not declared:
        raise ValueError("At least one provider is required")
    tools = [(provider, tool) for provider in declared for tool in provider.tools]
    if not tools:
        raise ValueError("At least one provider tool is required")
    routes = [tool.route for _, tool in tools]
    realms = [provider.realm for provider in declared]
    if len(set(routes)) != len(routes):
        raise ValueError("Provider routes must be unique")
    if len(set(realms)) != len(realms):
        raise ValueError("Provider realms must be unique")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        resolved = resolve_provider_settings(settings)
        addresses = _validate_configuration(declared, resolved)
        prepare_private_directory(resolved.state_dir)
        challenge_secrets = load_or_create_secrets(
            resolved.state_dir / "secrets.json",
            set(realms),
        )

        async with AsyncExitStack() as stack:
            fulfillments = await FulfillmentStore.create(resolved.state_dir / "fulfillment.sqlite3")
            stack.push_async_callback(fulfillments.close)

            replay_path = resolved.state_dir / "mpp-replay.sqlite3"
            replay_store = await SQLiteStore.create(str(replay_path))
            os.chmod(replay_path, 0o600)
            stack.push_async_callback(replay_store.close)

            receivers: dict[str, Mpp] = {}
            for provider in declared:
                intent = (
                    intent_factory()
                    if intent_factory is not None
                    else ChargeIntent(
                        chain_id=CHAIN_ID,
                        rpc_url=resolved.rpc_url,
                        timeout=40,
                    )
                )
                stack.push_async_callback(intent.aclose)
                receivers[provider.realm] = Mpp.create(
                    method=tempo(
                        intents={"charge": intent},
                        chain_id=CHAIN_ID,
                        rpc_url=resolved.rpc_url,
                        currency=TOKEN,
                        recipient=addresses[provider.wallet],
                    ),
                    realm=provider.realm,
                    secret_key=challenge_secrets[provider.realm],
                    store=replay_store,
                )

            app.state.provider_runtime = ProviderRuntime(
                settings=resolved,
                receivers=receivers,
                fulfillments=fulfillments,
                locks={},
            )
            try:
                yield
            finally:
                app.state.provider_runtime = None

    app = FastAPI(
        title="OpenMCP provider service — MPP on Tempo testnet",
        version="0.2.0",
        lifespan=lifespan,
    )

    for provider, tool in tools:
        app.add_api_route(
            tool.route,
            _endpoint(app, provider, tool),
            methods=["POST"],
            name=tool.route_id,
        )

    return app


def _validate_configuration(
    providers: tuple[OpenMCPProvider, ...],
    settings: ProviderSettings,
) -> dict[str, str]:
    addresses = load_public_addresses(settings.wallets)
    catalog = load_catalog(settings.catalog)
    declared = {
        tool.route_id: (provider, tool) for provider in providers for tool in provider.tools
    }
    if set(declared) != set(catalog):
        raise ValueError("Provider routes must exactly match catalog/providers.json")

    wallet_names = {provider.wallet for provider in providers}
    missing = wallet_names - set(addresses)
    if missing:
        raise ValueError("Run `uv run openmcp init`; provider public wallets are missing")
    selected = [addresses[name].lower() for name in wallet_names]
    if len(selected) != len(set(selected)):
        raise ValueError("Provider recipient wallets must be distinct")

    for route_id, (provider, tool) in declared.items():
        entry = catalog[route_id]
        parsed_url = urlparse(str(entry.url))
        if (
            entry.name != provider.name
            or entry.wallet != provider.wallet
            or parsed_url.hostname != "127.0.0.1"
            or parsed_url.port != 9001
            or parsed_url.path != tool.route
            or parsed_url.query
            or parsed_url.fragment
        ):
            raise ValueError(f"Provider declaration does not match catalog route {route_id}")
        fee = (entry.price_cents * settings.fee_bps + 5000) // 10_000
        expected_price = entry.price_cents - fee
        if expected_price != tool.price_cents:
            raise ValueError(
                f"Provider price for {route_id} must be {expected_price} cents "
                f"at OPENMCP_FEE_BPS={settings.fee_bps}"
            )
        if tool.input_schema != entry.input_schema:
            raise ValueError(f"Provider input schema does not match catalog route {route_id}")

    return addresses


def _endpoint(
    app: FastAPI,
    provider: OpenMCPProvider,
    tool: ProviderTool,
) -> Callable[..., Awaitable[Response]]:
    async def endpoint(request: Request, arguments: BaseModel) -> Response:
        runtime: ProviderRuntime | None = getattr(app.state, "provider_runtime", None)
        if runtime is None:
            return _error(503, "provider_unavailable")

        execution_id = request.headers.get("Idempotency-Key")
        forwarded_id = request.headers.get("X-OpenMCP-Execution-ID")
        if not execution_id or execution_id != forwarded_id:
            return _error(400, "execution_headers_must_match")

        body = arguments.model_dump(mode="json")
        fingerprint = fingerprint_for(tool.route_id, body)
        authorization = request.headers.get("Authorization")
        credential_hash = hash_credential(authorization) if authorization else None

        async with runtime.lock_for(execution_id):
            saved = await runtime.fulfillments.get(execution_id)
            if saved is not None:
                if saved.fingerprint != fingerprint:
                    return _error(409, "idempotency_conflict")
                if not credential_hash or credential_hash != saved.credential_hash:
                    return _error(403, "original_paid_credential_required")
                if saved.response_json is not None:
                    return _paid_response(saved.response_json, saved.receipt)
                return await _fulfill(runtime, tool, body, saved)

            receiver = runtime.receivers[provider.realm]
            try:
                result = await receiver.charge(
                    authorization,
                    tool.price_usd,
                    memo=memo_for(execution_id),
                    body=body,
                )
            except Exception:
                return _error(503, "payment_temporarily_unavailable")

            if isinstance(result, Challenge):
                return JSONResponse(
                    {"payment_required": True},
                    status_code=402,
                    headers={
                        "WWW-Authenticate": result.to_www_authenticate(receiver.realm),
                        "Cache-Control": "no-store",
                    },
                )

            if authorization is None or credential_hash is None:
                return _error(503, "payment_state_invalid")
            _, receipt = result
            receipt_header = receipt.to_payment_receipt()
            try:
                await runtime.fulfillments.save_payment(
                    execution_id=execution_id,
                    route=tool.route_id,
                    fingerprint=fingerprint,
                    credential_hash=credential_hash,
                    receipt=receipt_header,
                )
            except Exception:
                return _error(
                    503,
                    "payment_persistence_failed",
                    receipt=receipt_header,
                )

            saved = Fulfillment(
                execution_id=execution_id,
                route=tool.route_id,
                fingerprint=fingerprint,
                credential_hash=credential_hash,
                receipt=receipt_header,
                response_json=None,
            )
            return await _fulfill(runtime, tool, body, saved)

    endpoint.__name__ = f"call_{tool.route_id.replace('-', '_')}"
    endpoint.__signature__ = inspect.Signature(  # type: ignore[attr-defined]
        parameters=[
            inspect.Parameter(
                "request",
                kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
                annotation=Request,
            ),
            inspect.Parameter(
                "arguments",
                kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
                annotation=tool.input_model,
                default=Body(...),
            ),
        ],
        return_annotation=Response,
    )
    return endpoint


async def _fulfill(
    runtime: ProviderRuntime,
    tool: ProviderTool,
    body: dict[str, Any],
    saved: Fulfillment,
) -> Response:
    try:
        result = tool.function(**body)
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, dict):
            raise TypeError("Provider results must be JSON objects")
        response_json = json.dumps(
            result,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
        if len(response_json.encode()) > _MAX_RESPONSE_BYTES:
            raise ValueError("Provider result exceeds 1 MB")
        await runtime.fulfillments.save_response(saved.execution_id, response_json)
    except Exception:
        return _error(503, "upstream_temporarily_unavailable", receipt=saved.receipt)
    return _paid_response(response_json, saved.receipt)


def _paid_response(response_json: str, receipt: str) -> Response:
    return Response(
        response_json,
        status_code=200,
        media_type="application/json",
        headers={"Payment-Receipt": receipt},
    )


def _error(status: int, code: str, *, receipt: str | None = None) -> JSONResponse:
    headers = {"Payment-Receipt": receipt} if receipt else None
    return JSONResponse({"error": code}, status_code=status, headers=headers)


def _price_to_cents(price_usd: int | float | Decimal | str) -> int:
    try:
        amount = Decimal(str(price_usd))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("price_usd must be a valid decimal amount") from exc
    cents = amount * 100
    if not cents.is_finite() or cents <= 0 or cents != cents.to_integral_value():
        raise ValueError("price_usd must be positive and have at most two decimals")
    return int(cents)


def _input_model(function: Callable[..., Any], route_id: str) -> type[BaseModel]:
    signature = inspect.signature(function)
    try:
        annotations = get_type_hints(function, include_extras=True)
    except (NameError, TypeError) as exc:
        raise TypeError(f"Could not resolve annotations for {route_id}") from exc

    fields: dict[str, tuple[Any, Any]] = {}
    for parameter in signature.parameters.values():
        if parameter.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            raise TypeError(f"Unsupported parameter kind for {parameter.name}")
        if parameter.name not in annotations:
            raise TypeError(f"{route_id}.{parameter.name} must have a type annotation")
        default = ... if parameter.default is inspect.Parameter.empty else parameter.default
        fields[parameter.name] = (annotations[parameter.name], default)

    return create_model(
        f"{route_id.title().replace('-', '')}Input",
        __config__=ConfigDict(extra="forbid"),
        **fields,
    )


def _clean_schema(schema: dict[str, Any]) -> dict[str, Any]:
    def clean(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items() if key != "title"}
        if isinstance(value, list):
            return [clean(item) for item in value]
        return value

    return json.loads(json.dumps(clean(schema)))
