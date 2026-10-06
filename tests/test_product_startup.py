"""The live API can start without access to the worker's signing key."""

import json
from argparse import Namespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient

from openmcp.product import app as app_module
from openmcp.product import cli as cli_module
from openmcp.product.config import ProductSettings


@pytest.fixture
def live_settings(tmp_path):
    catalog = tmp_path / "services.json"
    catalog.write_text(
        json.dumps(
            [
                {
                    "endpoint_id": "fixture",
                    "name": "Fixture",
                    "description": "Startup fixture",
                    "url": "https://provider.example/execute",
                    "recipient": "0x1111111111111111111111111111111111111111",
                    "price_cents": 100,
                    "input_schema": {"type": "object"},
                    "enabled": True,
                    "mode": "live",
                    "supports_idempotency": True,
                }
            ]
        )
    )
    return ProductSettings(
        _env_file=None,
        mode="live",
        database_url="postgresql://fixture@localhost:5432/fixture",
        database_provider="postgres",
        clerk_issuer="https://clerk.example",
        clerk_authorized_parties=["https://app.example"],
        frontend_url="https://app.example",
        stripe_key="rk_live_fixture",
        stripe_webhook_secret="whsec_fixture",
        chain_id=4217,
        token="0x20c000000000000000000000b9537d11c60e8b50",
        rpc_url="https://rpc.tempo.xyz",
        explorer_url="https://explore.tempo.xyz",
        treasury_key_file=None,
        catalog_path=catalog,
    )


@pytest.mark.parametrize("missing_path", [False, True])
def test_live_api_starts_without_signer_but_worker_requires_it(
    live_settings, monkeypatch, tmp_path, missing_path
):
    if missing_path:
        live_settings.treasury_key_file = tmp_path / "not-mounted.json"
    store = Mock()
    monkeypatch.setattr(app_module.DatabaseManager, "from_settings", Mock(return_value=Mock()))
    monkeypatch.setattr(app_module, "Store", Mock(return_value=store))
    app = app_module.create_app(live_settings, verifier=AsyncMock(), stripe=AsyncMock())
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
    store.database.check_schema_version.assert_called_once()
    store.bind_runtime.assert_called_once_with(live_settings)
    store.close.assert_called_once()
    with pytest.raises(ValueError, match="private treasury key file"):
        live_settings.validate_startup()


@pytest.mark.parametrize(
    "change,message",
    [
        ({"chain_id": 42431}, "Treasury chain"),
    ],
)
def test_api_still_requires_live_network(live_settings, change, message):
    settings = live_settings.model_copy(update=change)
    with pytest.raises(ValueError, match=message):
        settings.validate_startup(require_treasury_key=False)


@pytest.mark.parametrize("catalog_state", ["unset", "empty", "missing"])
def test_live_api_accepts_no_providers(live_settings, monkeypatch, catalog_state):
    if catalog_state == "empty":
        live_settings.catalog_path.write_text("[]")
    elif catalog_state == "missing":
        live_settings.catalog_path.unlink()
    else:
        live_settings.catalog_path = None
    store = Mock()
    monkeypatch.setattr(app_module.DatabaseManager, "from_settings", Mock(return_value=Mock()))
    monkeypatch.setattr(app_module, "Store", Mock(return_value=store))
    app = app_module.create_app(live_settings, verifier=AsyncMock(), stripe=AsyncMock())
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
    store.sync_catalog.assert_called_once_with(None if catalog_state == "unset" else [])


def test_missing_catalog_returns_no_services_and_logs_warning(live_settings, tmp_path, caplog):
    live_settings.catalog_path = tmp_path / "missing.json"
    assert live_settings.services() == {}
    assert any(
        record.levelname == "WARNING" and "empty service catalog" in record.message
        for record in caplog.records
    )


def test_invalid_catalog_is_not_silently_ignored(live_settings):
    live_settings.catalog_path.write_text("not JSON")
    with pytest.raises(json.JSONDecodeError):
        live_settings.catalog()


def test_catalog_permission_error_is_not_silently_ignored(live_settings, monkeypatch):
    def denied(_):
        raise PermissionError("Cannot read catalog")

    monkeypatch.setattr(type(live_settings.catalog_path), "read_text", denied)
    with pytest.raises(PermissionError):
        live_settings.catalog()


async def test_worker_cli_starts_without_catalog_or_treasury(live_settings, monkeypatch):
    live_settings.catalog_path = None
    store = Mock()
    store.requires_treasury.return_value = False
    stripe = Mock(close=AsyncMock())
    worker = Mock(tick=AsyncMock(), api_caller=None)
    treasury = Mock(side_effect=AssertionError("No signer should be loaded"))
    monkeypatch.setattr(cli_module, "ProductSettings", Mock(return_value=live_settings))
    monkeypatch.setattr(cli_module.DatabaseManager, "from_settings", Mock(return_value=Mock()))
    monkeypatch.setattr(cli_module, "Store", Mock(return_value=store))
    monkeypatch.setattr(cli_module, "StripeGateway", Mock(return_value=stripe))
    monkeypatch.setattr(cli_module, "Treasury", treasury)
    factory = Mock(return_value=worker)
    monkeypatch.setattr(cli_module, "Worker", factory)
    await cli_module.run(Namespace(command="worker", once=True))
    treasury.assert_not_called()
    factory.assert_called_once_with(live_settings, store, stripe, None)
    worker.tick.assert_awaited_once()
    stripe.close.assert_awaited_once()
    store.close.assert_called_once()


async def test_worker_cli_requires_signer_for_mpp_even_without_catalog_file(
    live_settings, monkeypatch
):
    live_settings.catalog_path = None
    store = Mock()
    store.requires_treasury.return_value = True
    stripe = Mock(close=AsyncMock())
    monkeypatch.setattr(cli_module, "StripeGateway", Mock(return_value=stripe))
    with pytest.raises(ValueError, match="OPENMCP_TREASURY_KEY_FILE"):
        await cli_module.run_with_store(
            Namespace(command="worker", once=True), live_settings, store
        )
    stripe.close.assert_awaited_once()
