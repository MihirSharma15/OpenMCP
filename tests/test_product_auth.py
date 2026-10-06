"""Real RSA verification and HTTP authority boundaries without network services."""

import time
from unittest.mock import AsyncMock, Mock

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from openmcp.product.app import create_app
from openmcp.product.auth import ClerkVerifier
from openmcp.product.config import ProductSettings
from openmcp.product.models import ProductError


@pytest.fixture
def auth_setup():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    settings = ProductSettings(
        _env_file=None, clerk_issuer="https://clerk.example", clerk_public_key=public
    )
    claims = {
        "sub": "user_1",
        "iss": "https://clerk.example",
        "azp": "http://localhost:3000",
        "exp": int(time.time()) + 60,
        "nbf": int(time.time()) - 5,
        "iat": int(time.time()) - 5,
    }
    return settings, key, claims


async def test_clerk_accepts_only_configured_issuer_party_and_signature(auth_setup):
    settings, key, claims = auth_setup
    verifier = ClerkVerifier(settings)
    try:
        assert await verifier.subject(jwt.encode(claims, key, algorithm="RS256")) == "user_1"
        for change in (
            {"azp": "https://attacker.example"},
            {"iss": "https://other.clerk.example"},
            {"exp": int(time.time()) - 50},
            {"nbf": int(time.time()) + 50},
            {"sts": "pending"},
        ):
            with pytest.raises(ProductError, match="valid Clerk"):
                await verifier.subject(jwt.encode(claims | change, key, algorithm="RS256"))
        with pytest.raises(ProductError):
            await verifier.subject(jwt.encode(claims, "a" * 32, algorithm="HS256"))
    finally:
        await verifier.close()


async def test_clerk_requires_claims_and_checks_audience(auth_setup):
    settings, key, claims = auth_setup
    settings.clerk_audience = "openmcp"
    verifier = ClerkVerifier(settings)
    try:
        with pytest.raises(ProductError):
            await verifier.subject(jwt.encode(claims, key, algorithm="RS256"))
        assert (
            await verifier.subject(jwt.encode(claims | {"aud": "openmcp"}, key, algorithm="RS256"))
            == "user_1"
        )
        for missing in ("sub", "exp", "nbf", "iat", "azp"):
            incomplete = {k: v for k, v in (claims | {"aud": "openmcp"}).items() if k != missing}
            with pytest.raises(ProductError):
                await verifier.subject(jwt.encode(incomplete, key, algorithm="RS256"))
    finally:
        await verifier.close()


async def test_http_auth_errors_and_no_legacy_credit_mutations(auth_setup):
    settings, key, claims = auth_setup
    store = Mock()
    store.bootstrap.return_value = {"account_id": "acct_one", "status": "active"}
    store.account_for_subject.return_value = {"account_id": "acct_one", "status": "active"}
    app = create_app(settings, store=store, stripe=Mock(close=AsyncMock()))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://api.example"
    ) as client:
        missing = await client.get("/v1/wallet")
        assert missing.status_code == 401 and missing.json()["request_id"].startswith("req_")
        assert missing.headers["cache-control"] == "no-store"
        owner = {"Authorization": "Bearer " + jwt.encode(claims, key, algorithm="RS256")}
        boot = await client.post("/v1/me/bootstrap", headers=owner)
        assert boot.status_code == 200 and boot.json()["account_id"] == "acct_one"
        assert store.bootstrap.call_args[0][0] != "user_1"  # issuer-bound namespace
        assert (
            await client.post(
                "/v1/execute",
                headers=owner,
                json={"endpoint_id": "x", "payload": {}, "max_price_cents": 1},
            )
        ).status_code == 403
        machine = {"Authorization": "Bearer omcp_test"}
        assert (
            await client.post(
                "/v1/agents", headers=machine, json={"name": "a", "spend_limit_cents": 1}
            )
        ).status_code == 403
        assert (
            await client.post("/v1/wallet/top-ups", headers=owner, json={"amount_cents": 1000})
        ).status_code == 422
        assert (
            await client.post(
                "/v1/wallet/top-ups",
                headers=owner | {"Idempotency-Key": "valid"},
                json={"amount_cents": True},
            )
        ).status_code == 422
        for path in ("/v1/credits/deposit", "/v1/credits/debit", "/reset"):
            response = await client.post(path, headers=owner, json={})
            assert response.status_code == 404 and response.json()["error"]["code"] == "not_found"
        assert (
            await client.post("/v1/me/bootstrap", headers=owner, content=b"x" * 131073)
        ).status_code == 413


@pytest.mark.parametrize("amount", [500, 1250, 2549, 5000])
async def test_top_up_accepts_custom_cents_without_changing_checkout_authority(auth_setup, amount):
    settings, key, claims = auth_setup
    store = Mock()
    store.account_for_subject.return_value = {"account_id": "acct_one", "status": "active"}
    top = {"id": "top_one", "amount_cents": amount, "status": "awaiting_payment"}
    store.create_top_up.return_value = top
    store.top_up_public.return_value = top
    stripe = Mock(create=AsyncMock(return_value=top), close=AsyncMock())
    app = create_app(settings, store=store, stripe=stripe)
    headers = {
        "Authorization": "Bearer " + jwt.encode(claims, key, algorithm="RS256"),
        "Idempotency-Key": "custom-amount",
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://api.example"
    ) as client:
        response = await client.post(
            "/v1/wallet/top-ups", headers=headers, json={"amount_cents": amount}
        )
    assert response.status_code == 200
    assert response.json()["amount_cents"] == amount
    store.create_top_up.assert_called_once_with("acct_one", "custom-amount", amount)
    store.rate_limit.assert_any_call("top-up:acct_one", 10)
    stripe.create.assert_awaited_once_with(top)


@pytest.mark.parametrize("amount", [0, 499, 5001, -1000, True, 1250.5, "1250"])
async def test_invalid_top_up_amount_never_creates_a_checkout(auth_setup, amount):
    settings, key, claims = auth_setup
    store = Mock()
    store.account_for_subject.return_value = {"account_id": "acct_one", "status": "active"}
    stripe = Mock(create=AsyncMock(), close=AsyncMock())
    app = create_app(settings, store=store, stripe=stripe)
    headers = {
        "Authorization": "Bearer " + jwt.encode(claims, key, algorithm="RS256"),
        "Idempotency-Key": "invalid-amount",
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://api.example"
    ) as client:
        response = await client.post(
            "/v1/wallet/top-ups", headers=headers, json={"amount_cents": amount}
        )
    assert response.status_code == 422
    store.create_top_up.assert_not_called()
    stripe.create.assert_not_awaited()
