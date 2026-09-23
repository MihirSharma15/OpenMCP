"""TEST ONLY: MPP contract peer; teammate supplies the actual wrapper and reports."""

import hashlib

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from mpp import Challenge

from openmcp.config import load_catalog
from openmcp.payments import canonical, make_receiver, memo_for


class ProviderFixture:
    def __init__(self, settings, intent_factory=None):
        self.app = FastAPI()
        self.cached = {}
        self.calls = 0
        self.fail_before_payment = False
        self.lose_response_once = False
        self.wrong_price = False
        self.receivers = {}
        self.intents = []
        self.settings = settings
        for provider in load_catalog(settings.catalog).values():
            intent = intent_factory() if intent_factory else None
            receiver, intent = make_receiver(
                settings,
                settings.addresses()[provider.wallet],
                realm=f"{provider.id}.test",
                secret=f"test-contract-secret-{provider.id}",
                database=settings.database.parent / f"fixture-{provider.id}.sqlite3",
                intent=intent,
            )
            self.receivers[provider.id] = receiver
            self.intents.append(intent)

        @self.app.post("/{endpoint}")
        async def paid(endpoint: str, request: Request):
            provider = load_catalog(settings.catalog)[endpoint]
            key = request.headers["Idempotency-Key"]
            assert key == request.headers["X-OpenMCP-Execution-ID"]
            body = await request.json()
            fingerprint = hashlib.sha256(
                canonical({"endpoint": endpoint, "body": body})
            ).hexdigest()
            authorization = request.headers.get("Authorization")
            credential_hash = hashlib.sha256((authorization or "").encode()).hexdigest()
            if key in self.cached:
                saved = self.cached[key]
                if saved["fingerprint"] != fingerprint:
                    return JSONResponse({"error": "idempotency conflict"}, status_code=409)
                if not authorization or credential_hash != saved["credential_hash"]:
                    return JSONResponse(
                        {"error": "original paid credential required"}, status_code=403
                    )
                return JSONResponse(saved["data"], headers={"Payment-Receipt": saved["receipt"]})
            if self.fail_before_payment:
                return JSONResponse({"error": "test failure"}, status_code=503)
            amount = (
                provider.price_cents - (provider.price_cents * settings.fee_bps + 5000) // 10000
            )
            if self.wrong_price:
                amount += 1
            receiver = self.receivers[endpoint]
            result = await receiver.charge(
                authorization,
                f"{amount / 100:.2f}",
                memo=memo_for(key),
                body=body,
            )
            if isinstance(result, Challenge):
                return JSONResponse(
                    {"payment_required": True},
                    status_code=402,
                    headers={"WWW-Authenticate": result.to_www_authenticate(receiver.realm)},
                )
            _, receipt = result
            self.calls += 1
            data = {
                "company": body["company"],
                "content": "Contract test fixture only; no due diligence evidence.",
                "is_demo_data": True,
            }
            self.cached[key] = {
                "fingerprint": fingerprint,
                "credential_hash": credential_hash,
                "data": data,
                "receipt": receipt.to_payment_receipt(),
            }
            if self.lose_response_once:
                self.lose_response_once = False
                return JSONResponse(
                    {"error": "test response lost after settlement"}, status_code=503
                )
            return JSONResponse(data, headers={"Payment-Receipt": receipt.to_payment_receipt()})

    async def close(self):
        for intent in self.intents:
            await intent.aclose()
