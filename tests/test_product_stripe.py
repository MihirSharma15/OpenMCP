"""Canonical Stripe retrieval, signed events, and checkout binding at HTTP boundary."""

import hashlib
import hmac
import json
import time
from datetime import timedelta
from unittest.mock import Mock

import httpx
import pytest
from pydantic import SecretStr

from openmcp.product.config import ProductSettings
from openmcp.product.models import ProductError, now
from openmcp.product.stripe import StripeGateway


@pytest.mark.parametrize("mode", ["test", "live"])
@pytest.mark.parametrize("kind", ["sk", "rk"])
def test_startup_accepts_server_keys_and_rejects_public_or_wrong_mode(mode, kind, tmp_path):
    signer = tmp_path / "signer.json"
    signer.write_text("{}")  # Startup checks presence; no signing occurs in this test.
    catalog = tmp_path / "services.json"
    catalog.write_text(
        json.dumps(
            [
                {
                    "endpoint_id": "fixture",
                    "name": "Fixture",
                    "description": "Configuration fixture",
                    "url": "https://provider.example/execute",
                    "recipient": "0x1111111111111111111111111111111111111111",
                    "price_cents": 100,
                    "input_schema": {"type": "object"},
                    "enabled": True,
                    "mode": mode,
                    "supports_idempotency": True,
                }
            ]
        )
    )
    settings = ProductSettings(
        _env_file=None,
        mode=mode,
        database_url="postgresql://fixture@localhost:5432/fixture",
        database_provider="postgres",
        clerk_issuer="https://clerk.example",
        clerk_authorized_parties=["https://app.example"],
        frontend_url="https://app.example",
        stripe_key=f"{kind}_{mode}_fixture",
        stripe_webhook_secret="whsec_fixture",
        chain_id=4217 if mode == "live" else 42431,
        token="0x20c000000000000000000000b9537d11c60e8b50",
        rpc_url="https://rpc.tempo.xyz",
        explorer_url="https://explore.tempo.xyz",
        treasury_key_file=signer,
        catalog_path=catalog,
    )
    settings.validate_startup()
    other_mode = "live" if mode == "test" else "test"
    for invalid in (f"{kind}_{other_mode}_fixture", f"pk_{mode}_fixture", ""):
        changed = settings.model_copy(update={"stripe_key": SecretStr(invalid)})
        with pytest.raises(ValueError, match="Stripe server key"):
            changed.validate_startup()


@pytest.fixture
def setup():
    settings = ProductSettings(
        _env_file=None, stripe_key="sk_test_testing", stripe_webhook_secret="whsec_test"
    )
    top = {
        "id": "top_one",
        "account_id": "acct_one",
        "amount_cents": 1000,
        "checkout_id": None,
        "payment_intent_id": None,
        "created_at": now(),
    }
    store = Mock()
    store.top_up_internal.side_effect = lambda identifier: top if identifier == "top_one" else None
    store.account.return_value = {"stripe_customer_id": "cus_one"}
    store.checkout_state.return_value = top
    session = {
        "id": "cs_one",
        "livemode": False,
        "mode": "payment",
        "status": "complete",
        "currency": "usd",
        "amount_total": 1000,
        "payment_status": "paid",
        "client_reference_id": "acct_one",
        "payment_intent": "pi_one",
        "metadata": {"top_up_id": "top_one", "account_id": "acct_one"},
        "url": "https://checkout.stripe.com/c/pay/example",
        "expires_at": int(time.time()) + 1000,
    }
    return settings, store, top, session


@pytest.mark.parametrize("amount", [100, 101, 499, 1000, 1250, 2549])
async def test_checkout_uses_server_price_return_urls_and_stable_idempotency(setup, amount):
    settings, store, top, session = setup
    top["amount_cents"] = amount
    session["amount_total"] = amount
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json=session)

    gateway = StripeGateway(settings, store, transport=httpx.MockTransport(handle))
    try:
        await gateway.create(top)
        request = requests[0]
        assert request.headers["idempotency-key"] == "top_one"
        assert f"unit_amount%5D={amount}".encode() in request.content
        assert b"payment_method_types" not in request.content
        assert b"top_up_id%3Dtop_one" in request.content
        assert b"canceled%3D1" in request.content
        assert store.checkout_state.call_args.kwargs["paid"] is True
        with pytest.raises(ProductError, match="reconciliation"):
            await gateway.create(top | {"created_at": now() - timedelta(hours=24)})
        assert len(requests) == 1
    finally:
        await gateway.close()


def test_signed_webhooks_reject_tampering_expiry_and_wrong_mode(setup):
    settings, store, _, _ = setup
    gateway = StripeGateway(settings, store)
    event = {
        "id": "evt_one",
        "type": "checkout.session.completed",
        "livemode": False,
        "created": int(time.time()),
        "data": {"object": {"id": "cs_one"}},
    }
    body = json.dumps(event).encode()

    def sign(content, timestamp):
        digest = hmac.new(
            b"whsec_test", str(timestamp).encode() + b"." + content, hashlib.sha256
        ).hexdigest()
        return f"t={timestamp},v1={digest}"

    assert gateway.verify_webhook(body, sign(body, event["created"])) == event
    for payload, signature in (
        (body + b" ", sign(body, event["created"])),
        (body, sign(body, event["created"] - 301)),
        (body, "junk"),
    ):
        with pytest.raises(ProductError):
            gateway.verify_webhook(payload, signature)
    live = json.dumps(event | {"livemode": True}).encode()
    with pytest.raises(ProductError, match="mode"):
        gateway.verify_webhook(live, sign(live, event["created"]))


@pytest.mark.parametrize(
    "change",
    [
        {"amount_total": 1001},
        {"currency": "eur"},
        {"livemode": True},
        {"client_reference_id": "acct_other"},
        {"url": "https://evil.example"},
    ],
)
def test_no_credit_for_unexpected_checkout_terms(setup, change):
    settings, store, _, session = setup
    gateway = StripeGateway(settings, store)
    with pytest.raises(ProductError):
        gateway.apply_session(session | change)
    store.checkout_state.assert_not_called()


@pytest.mark.parametrize(
    "movements,expected",
    [
        ([], 0),
        ([{"amount": -1000, "currency": "usd"}], 1000),
        ([{"amount": -1000, "currency": "usd"}, {"amount": 1000, "currency": "usd"}], 0),
    ],
)
async def test_dispute_uses_actual_withdrawal_and_reinstatement_not_warning_amount(
    setup, movements, expected
):
    settings, store, _, _ = setup

    def handle(request):
        if "/disputes/" in request.url.path:
            data = {
                "id": "du_one",
                "livemode": False,
                "charge": "ch_one",
                "amount": 1000,
                "status": "warning_needs_response",
                "balance_transactions": movements,
            }
        elif "/charges/" in request.url.path:
            data = {
                "id": "ch_one",
                "livemode": False,
                "payment_intent": "pi_one",
                "currency": "usd",
                "amount": 1000,
                "amount_refunded": 0,
            }
        else:
            data = {
                "id": "pi_one",
                "livemode": False,
                "metadata": {"top_up_id": "top_one", "account_id": "acct_one"},
            }
        return httpx.Response(200, json=data)

    gateway = StripeGateway(settings, store, transport=httpx.MockTransport(handle))
    try:
        await gateway.process_event(
            {"type": "charge.dispute.updated", "object_id": "du_one", "event_created": 100}
        )
        assert store.funding_reversal.call_args.kwargs["disputed_cents"] == expected
        assert store.funding_reversal.call_args.kwargs["dispute_open"] is True
    finally:
        await gateway.close()
