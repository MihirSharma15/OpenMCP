"""The live API can start without access to the worker's signing key."""

from argparse import Namespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient

from openmcp.product import app as app_module
from openmcp.product import cli as cli_module
from openmcp.product.config import ProductSettings


@pytest.fixture
def live_settings(tmp_path):
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
    store.sync_catalog.assert_not_called()
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


@pytest.mark.parametrize("contents", [None, "[]", "not JSON"])
def test_startup_never_reads_or_mutates_catalog_files(
    live_settings, monkeypatch, tmp_path, contents
):
    catalog = tmp_path / "catalog.json"
    if contents is not None:
        catalog.write_text(contents)
    monkeypatch.setenv("OPENMCP_PRODUCT_CATALOG", str(catalog))
    store = Mock()
    monkeypatch.setattr(app_module.DatabaseManager, "from_settings", Mock(return_value=Mock()))
    monkeypatch.setattr(app_module, "Store", Mock(return_value=store))
    with TestClient(
        app_module.create_app(live_settings, verifier=AsyncMock(), stripe=AsyncMock())
    ) as client:
        assert client.get("/health/live").status_code == 200
    store.sync_catalog.assert_not_called()


async def test_worker_cli_starts_without_catalog_or_treasury(live_settings, monkeypatch):
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
    store.sync_catalog.assert_not_called()


async def test_worker_cli_requires_signer_for_mpp_even_without_catalog_file(
    live_settings, monkeypatch
):
    store = Mock()
    store.requires_treasury.return_value = True
    stripe = Mock(close=AsyncMock())
    monkeypatch.setattr(cli_module, "StripeGateway", Mock(return_value=stripe))
    with pytest.raises(ValueError, match="OPENMCP_TREASURY_KEY_FILE"):
        await cli_module.run_with_store(
            Namespace(command="worker", once=True), live_settings, store
        )
    stripe.close.assert_awaited_once()


@pytest.mark.parametrize("command", ["doctor", "review"])
async def test_account_operator_inspection_needs_no_mpp_signer(live_settings, monkeypatch, command):
    store = Mock()
    store.review.return_value = []
    store.service_count.return_value = 0
    store.health.return_value = {"database": True, "worker": False}
    monkeypatch.setattr(cli_module, "ProductSettings", Mock(return_value=live_settings))
    monkeypatch.setattr(cli_module.DatabaseManager, "from_settings", Mock(return_value=Mock()))
    monkeypatch.setattr(cli_module, "Store", Mock(return_value=store))
    monkeypatch.setattr(cli_module, "Treasury", Mock(side_effect=AssertionError("No signer")))
    await cli_module.run(Namespace(command=command, chain=False))
    store.close.assert_called_once()
