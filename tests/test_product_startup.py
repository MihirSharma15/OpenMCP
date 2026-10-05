"""The live API can start without access to the worker's signing key."""

import json
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient

from openmcp.product import app as app_module
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
        ({"catalog_path": None}, "explicitly enabled live provider"),
    ],
)
def test_api_still_requires_live_network_and_provider(live_settings, change, message):
    settings = live_settings.model_copy(update=change)
    with pytest.raises(ValueError, match=message):
        settings.validate_startup(require_treasury_key=False)
