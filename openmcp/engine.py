import asyncio
import hashlib
import re

import httpx
from jsonschema import ValidationError, validate
from mpp import Challenge, Receipt

from .config import CHAIN_ID, TOKEN, Settings, load_catalog
from .models import DiscoverRequest, ExecuteRequest, OpenMCPError
from .payments import PaidClient, canonical, make_receiver, memo_for, receipt_dict
from .registry import registered_providers
from .store import Store
from .wallets import Chain


class Engine:
    def __init__(self, settings: Settings, *, incoming_intent=None, outgoing=None, chain=None):
        self.settings = settings
        self.catalog = load_catalog(settings.catalog)
        self.addresses = settings.addresses()
        self.store = Store(settings.database, settings.budget_cents)
        self.receiver, self.incoming_intent = make_receiver(
            settings, self.addresses["openmcp"], requires_auth=True, intent=incoming_intent
        )
        self.outgoing = outgoing or PaidClient(settings, "openmcp")
        self.chain = chain or Chain(settings)
        self.lock = asyncio.Lock()

    async def close(self):
        await self.incoming_intent.aclose()
        await self.outgoing.close()
        await self.chain.close()

    def refresh_catalog(self):
        for key, provider in registered_providers(self.settings.creator_database).items():
            if key in self.catalog and self.catalog[key] != provider:
                raise OpenMCPError("registry_conflict", "Registered endpoint terms changed", 503)
            self.catalog[key] = provider

    def endpoint_terms(self, endpoint_id):
        self.refresh_catalog()
        provider = self.catalog.get(endpoint_id)
        if provider is None:
            raise OpenMCPError("endpoint_not_found", "Unknown endpoint", 404)
        return {
            "endpoint_id": provider.id,
            "price_cents": provider.price_cents,
            "input_schema": provider.input_schema,
            "chain_id": CHAIN_ID,
            "token_address": TOKEN,
            "pay_to": self.addresses["openmcp"],
            "execute_path": "/execute",
        }

    def discover(self, request: DiscoverRequest):
        self.refresh_catalog()
        balance = self.store.balance()
        tokens = set(re.findall(r"[a-z0-9]+", request.query.lower()))
        broad = bool(tokens & {"diligence", "acquisition", "acquiring"})
        matches = []
        for p in self.catalog.values():
            score = len(tokens & set(p.keywords)) + int(broad)
            if score:
                fee = (p.price_cents * self.settings.fee_bps + 5000) // 10000
                matches.append(
                    {
                        "endpoint_id": p.id,
                        "provider": p.name,
                        "description": p.description,
                        "price_cents": p.price_cents,
                        "provider_price_cents": p.price_cents - fee,
                        "platform_fee_cents": fee,
                        "input_schema": p.input_schema,
                        "currency": "pathUSD",
                        "payment_protocol": "MPP",
                        "payment_method": "tempo",
                        "chain_id": CHAIN_ID,
                        "token_address": TOKEN,
                        "execute_path": "/execute",
                        "pay_to": self.addresses["openmcp"],
                        "provider_wallet": self.addresses[p.wallet],
                        "affordable": p.price_cents
                        <= min(balance["remaining_cents"], request.budget_cents),
                        "relevance": score,
                    }
                )
        matches.sort(key=lambda x: (-x["relevance"], x["price_cents"], x["endpoint_id"]))
        return {
            "session_id": balance["session_id"],
            "query": request.query,
            "endpoints": matches,
            "total_price_cents": sum(x["price_cents"] for x in matches),
            "remaining_cents": balance["remaining_cents"],
            "payment_mode": "mpp_tempo_testnet",
            "discovery_is_free": True,
        }

    async def execute(self, request: ExecuteRequest, authorization: str | None = None):
        self.refresh_catalog()
        body = request.model_dump()
        fingerprint = hashlib.sha256(canonical(body)).hexdigest()
        async with self.lock:
            row = self.store.existing(request.session_id, request.idempotency_key)
            if row and row["fingerprint"] != fingerprint:
                raise OpenMCPError(
                    "idempotency_conflict", "Key belongs to a different request.", 409
                )
            if row and row["state"] == "completed":
                return self.receipt(row, replayed=True)
            if row is None:
                provider = self.catalog.get(request.endpoint_id)
                if provider is None:
                    raise OpenMCPError("endpoint_not_found", "Discover an endpoint first.", 404)
                try:
                    validate(request.payload, provider.input_schema)
                except ValidationError as exc:
                    raise OpenMCPError("invalid_payload", exc.message, 422) from exc
                if provider.price_cents > request.max_price_cents:
                    raise OpenMCPError(
                        "price_changed", "Price exceeds approved maximum; rediscover.", 409
                    )
                fee = (provider.price_cents * self.settings.fee_bps + 5000) // 10000
                if fee >= provider.price_cents:
                    raise OpenMCPError("invalid_price", "Provider price must be positive.", 503)
                row = self.store.create(
                    request,
                    fingerprint,
                    provider.model_dump(mode="json"),
                    self.addresses[provider.wallet],
                    fee,
                )
            if row["state"] in ("quoted", "payment_pending"):
                if (
                    row["incoming_credential"]
                    and authorization
                    and row["incoming_credential"] != authorization
                ):
                    raise OpenMCPError(
                        "credential_conflict",
                        "This execution already has a payment credential; reuse it.",
                        409,
                    )
                credential_header = row["incoming_credential"] or authorization
                if credential_header and row["state"] == "quoted":
                    row = self.store.reserve(row, request.budget_cents, credential_header)
                try:
                    result = await self.receiver.charge(
                        None,
                        f"{row['price'] / 100:.2f}",
                        payment_authorization=credential_header,
                        memo=memo_for(fingerprint),
                        body=body,
                        description=f"OpenMCP: {row['provider']['name']}",
                    )
                except Exception as exc:
                    # Never generate a replacement payment after an ambiguous broadcast.
                    raise OpenMCPError(
                        "agent_payment_pending",
                        "MPP verification is pending. Retry the identical request and saved credential.",
                        503,
                        True,
                    ) from exc
                if isinstance(result, Challenge):
                    if credential_header:
                        raise OpenMCPError(
                            "credential_rejected",
                            "MPP credential rejected or expired; it was not paid again. Resolve the pending execution before resetting.",
                            409,
                        )
                    self.store.event(
                        row,
                        "agent_challenge_created",
                        amount_cents=row["price"],
                        challenge_id=result.id,
                    )
                    return result
                credential, receipt = result
                row = self.store.paid(row, receipt_dict(receipt))
            try:
                response = await self.outgoing.post(
                    str(row["provider"]["url"]),
                    request.payload,
                    key=row["id"],
                    recipient=row["destination"],
                    cents=row["price"] - row["fee"],
                    scope=row["id"],
                    budget=row["price"] - row["fee"],
                    memo=memo_for(row["id"]),
                    headers={"X-OpenMCP-Execution-ID": row["id"]},
                    on_event=lambda kind, **detail: self.store.event(
                        row, f"provider_{kind}", **detail
                    ),
                )
                if not response.is_success:
                    raise OpenMCPError(
                        "provider_pending",
                        f"Provider returned HTTP {response.status_code}; the incoming payment is saved. Retry the same request.",
                        503,
                        True,
                    )
                data = response.json()
                if not isinstance(data, dict):
                    raise ValueError("Provider data must be a JSON object")
                outgoing_receipt = receipt_dict(
                    Receipt.from_payment_receipt(response.headers["Payment-Receipt"])
                )
                row = self.store.update(
                    row, "completed", data=data, outgoing_receipt=outgoing_receipt, error=None
                )
                self.store.event(
                    row,
                    "completed",
                    price_cents=row["price"],
                    provider_amount_cents=row["price"] - row["fee"],
                    platform_fee_cents=row["fee"],
                )
                return self.receipt(row)
            except Exception as exc:
                error = (
                    exc
                    if isinstance(exc, OpenMCPError)
                    else OpenMCPError(
                        "provider_pending",
                        "Provider payment or response is pending. Retry the same request; do not create a new purchase.",
                        503,
                        True,
                    )
                )
                self.store.update(row, "provider_pending", error=error.as_dict())
                error.receipt = row["incoming_receipt"]
                raise error from exc

    @staticmethod
    def receipt(row, replayed=False):
        return {
            "execution_id": row["id"],
            "session_id": row["session_id"],
            "status": row["state"],
            "endpoint_id": row["provider"]["id"],
            "provider": row["provider"]["name"],
            "currency": "pathUSD",
            "price_cents": row["price"],
            "platform_fee_cents": row["fee"],
            "provider_amount_cents": row["price"] - row["fee"],
            "agent_to_openmcp": row["incoming_receipt"],
            "openmcp_to_provider": row["outgoing_receipt"],
            "data": row["data"],
            "error": row["error"],
            "replayed": replayed,
            "payment_mode": "mpp_tempo_testnet",
        }

    async def provider_dashboard(self, include_chain=True):
        dashboard = await self.dashboard(include_chain)
        transactions = []
        for row in self.store.provider_transactions():
            transaction = self.receipt(row)
            # Provider reporting does not need purchased evidence or serialized receipts.
            transaction.pop("data")
            for hop in ("agent_to_openmcp", "openmcp_to_provider"):
                if transaction[hop]:
                    transaction[hop] = {
                        key: value for key, value in transaction[hop].items() if key != "header"
                    }
            transactions.append(
                {**transaction, "created_at": row["created"], "paid_at": row["paid_at"]}
            )
        services = []
        for entry in dashboard["providers"]:
            provider = self.catalog[entry["endpoint_id"]]
            fee = (provider.price_cents * self.settings.fee_bps + 5000) // 10000
            services.append(
                {
                    **entry,
                    "session_earned_cents": sum(
                        transaction["provider_amount_cents"]
                        for transaction in transactions
                        if transaction["endpoint_id"] == provider.id
                        and transaction["session_id"] == dashboard["agent"]["session_id"]
                        and (transaction["openmcp_to_provider"] or {}).get("status") == "success"
                        and (transaction["openmcp_to_provider"] or {}).get("reference")
                    ),
                    "description": provider.description,
                    "endpoint_path": provider.url.path,
                    "price_cents": provider.price_cents,
                    "provider_amount_cents": provider.price_cents - fee,
                    "platform_fee_cents": fee,
                }
            )
        return {
            "agent": dashboard["agent"],
            "providers": services,
            "transactions": transactions,
            "currency": dashboard["currency"],
            "chain_id": dashboard["chain_id"],
            "payment_mode": dashboard["payment_mode"],
        }

    async def dashboard(self, include_chain=True):
        self.refresh_catalog()
        rows = self.store.transactions()
        providers = [
            {
                "endpoint_id": p.id,
                "name": p.name,
                "address": self.addresses[p.wallet],
                "session_earned_cents": sum(
                    r["price"] - r["fee"]
                    for r in rows
                    if r["state"] == "completed" and r["provider"]["id"] == p.id
                ),
            }
            for p in self.catalog.values()
        ]
        result = {
            "agent": {**self.store.balance(), "address": self.addresses["agent"]},
            "platform": {
                "address": self.addresses["openmcp"],
                "session_gross_fee_cents": sum(r["fee"] for r in rows if r["state"] == "completed"),
            },
            "providers": providers,
            "transactions": [self.receipt(r) for r in rows],
            "payment_mode": "mpp_tempo_testnet",
            "currency": "pathUSD",
            "chain_id": CHAIN_ID,
        }
        if include_chain:

            async def read(entry):
                try:
                    entry["wallet_balance"] = await self.chain.balance(entry["address"])
                except (httpx.HTTPError, OpenMCPError, ValueError):
                    entry["wallet_balance"] = {
                        "source": "tempo_testnet",
                        "error": "RPC balance unavailable",
                    }

            await asyncio.gather(
                *(read(e) for e in [result["agent"], result["platform"], *providers])
            )
        return result
