"""Opt-in: genuine Tempo testnet settlement against the provider CONTRACT fixture."""

import json
import os
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from openmcp.agent import Agent
from openmcp.app import create_app
from openmcp.config import Settings
from openmcp.engine import Engine
from openmcp.models import ExecuteRequest
from openmcp.payments import PaidClient
from tests.provider_fixture import ProviderFixture


@pytest.mark.skipif(
    os.environ.get("OPENMCP_LIVE_TEST") != "1", reason="opt-in test spends valueless testnet tokens"
)
async def test_live_two_hop_settlement():
    run = Path(".openmcp/live-check") / uuid4().hex
    settings = Settings(database=run / "mpp.sqlite3", product_database_url="")
    providers = ProviderFixture(settings)
    outgoing = PaidClient(settings, "openmcp", transport=httpx.ASGITransport(app=providers.app))
    engine = Engine(settings, outgoing=outgoing)
    app = create_app(settings, engine)
    agent = Agent(settings, transport=httpx.ASGITransport(app=app))
    proof = {
        "network": "Tempo Moderato testnet",
        "chain_id": 42431,
        "provider_type": "test-only contract fixture",
        "purchases": [],
    }
    try:
        await engine.chain.check_network()
        before = {
            name: await engine.chain.balance(address)
            for name, address in settings.addresses().items()
        }
        found = await agent.discover("FreightFlow due diligence", 1500)
        for endpoint in found["endpoints"]:
            request = ExecuteRequest(
                session_id=found["session_id"],
                endpoint_id=endpoint["endpoint_id"],
                payload={"company": "FreightFlow"},
                idempotency_key=f"live-{endpoint['endpoint_id']}",
                max_price_cents=endpoint["price_cents"],
                budget_cents=1500,
            )
            result = await agent.execute(request)
            proof["purchases"].append(result)
            replay = await agent.execute(request)
            assert replay["replayed"]
            assert (
                replay["agent_to_openmcp"]["reference"] == result["agent_to_openmcp"]["reference"]
            )
            assert (
                replay["openmcp_to_provider"]["reference"]
                == result["openmcp_to_provider"]["reference"]
            )
            print(
                f"\n{endpoint['endpoint_id']}: {result['agent_to_openmcp']['reference']} -> {result['openmcp_to_provider']['reference']}"
            )
        after = {
            name: await engine.chain.balance(address)
            for name, address in settings.addresses().items()
        }
        assert (
            after["operations"]["balance_units"] - before["operations"]["balance_units"] == 360_000
        )
        assert after["legal"]["balance_units"] - before["legal"]["balance_units"] == 450_000
        assert after["market"]["balance_units"] - before["market"]["balance_units"] == 270_000
        assert engine.store.balance()["remaining_cents"] == 1380
        proof.update(
            {"wallets_before": before, "wallets_after": after, "spending": engine.store.balance()}
        )
    finally:
        Path(".openmcp/live-proof.json").write_text(json.dumps(proof, indent=2) + "\n")
        await agent.close()
        await engine.close()
        await providers.close()
