"""Hosted initialization never substitutes fake accounts or acknowledges payments."""

from contextlib import asynccontextmanager

import psycopg
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from openmcp.product.vercel import create_hosted_app


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (ValueError("secret configuration value"), "backend_not_configured"),
        (psycopg.OperationalError("private database password"), "backend_unavailable"),
        (FileNotFoundError("private signer path"), "backend_unavailable"),
    ],
)
def test_unconfigured_deployment_is_alive_but_blocks_all_account_operations(error, code, caplog):
    calls = []

    def factory():
        calls.append(True)
        raise error

    app = create_hosted_app(factory)
    assert calls == []  # Import/build does not connect to production services.
    with TestClient(app) as client:
        assert len(calls) == 1
        assert client.get("/health/live").status_code == 200
        assert client.get("/").json()["status"] == code
        for method, path in [
            ("GET", "/health/ready"),
            ("GET", "/v1/wallet"),
            ("POST", "/v1/me/bootstrap"),
            ("POST", "/v1/execute"),
            ("POST", "/v1/webhooks/stripe"),
        ]:
            response = client.request(method, path)
            assert response.status_code == 503
            assert response.json()["error"]["code"] == code
            assert response.headers["Cache-Control"] == "no-store"
            assert response.headers["X-Request-ID"] == response.json()["request_id"]
            assert str(error) not in response.text
    assert str(error) not in caplog.text


def test_configured_deployment_forwards_requests_and_manages_account_lifespan():
    lifecycle = []

    @asynccontextmanager
    async def lifespan(app):
        lifecycle.append("start")
        yield
        lifecycle.append("stop")

    account = FastAPI(lifespan=lifespan)

    @account.post("/v1/webhooks/stripe")
    async def webhook(request: Request):
        return {
            "body": (await request.body()).decode(),
            "signature": request.headers["stripe-signature"],
        }

    @account.get("/health/ready")
    async def ready():
        return JSONResponse({"worker": False}, status_code=503)

    @account.get("/v1/wallet")
    async def wallet():
        return JSONResponse({"error": {"code": "unauthenticated"}}, status_code=401)

    with TestClient(create_hosted_app(lambda: account)) as client:
        assert lifecycle == ["start"]
        assert client.get("/").json()["status"] == "initialized"
        assert client.get("/health/ready").status_code == 503
        assert client.get("/v1/wallet").status_code == 401
        response = client.post(
            "/v1/webhooks/stripe",
            content=b'{ "unaltered": true }',
            headers={"stripe-signature": "test-signature"},
        )
        assert response.json() == {"body": '{ "unaltered": true }', "signature": "test-signature"}
    assert lifecycle == ["start", "stop"]


def test_programming_errors_are_not_reported_as_missing_configuration():
    def broken_factory():
        raise RuntimeError("unexpected programming error")

    with pytest.raises(RuntimeError, match="unexpected programming error"):
        with TestClient(create_hosted_app(broken_factory)):
            pass
