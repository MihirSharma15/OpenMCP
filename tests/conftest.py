import json
from collections import defaultdict
from pathlib import Path

import httpx
import pytest
from eth_hash.auto import keccak
from mpp import Credential, Receipt

from openmcp.adapters.memory import MemoryLedger
from openmcp.agent import Agent
from openmcp.app import create_app
from openmcp.config import CHAIN_ID, Settings
from openmcp.engine import Engine
from openmcp.payments import PaidClient, canonical
from openmcp.wallets import create_wallets
from tests.provider_fixture import ProviderFixture

ROOT = Path(__file__).resolve().parents[1]


class TestChain:
    """Test-only settlement double. MPP challenge/credential/receipt parsing is the real SDK."""

    def __init__(self):
        self.balances = defaultdict(lambda: 20_000_000)
        self.transactions = {}
        self.signatures = 0
        self.broadcasts = 0

    async def check_network(self):
        pass

    async def balance(self, address):
        return {
            "address": address,
            "balance_units": self.balances[address.lower()],
            "source": "tempo_testnet",
        }

    async def close(self):
        pass

    async def verify_transfer(self, reference, sender, recipient, cents, memo):
        transfer = self.transactions[reference]
        assert transfer["sender"].lower() == sender.lower()
        assert transfer["request"]["recipient"].lower() == recipient.lower()
        assert int(transfer["request"]["amount"]) == cents * 10_000
        assert transfer["request"]["methodDetails"]["memo"] == memo

    def method(self, address):
        chain = self

        class Method:
            async def create_credential(self, challenge):
                chain.signatures += 1
                payload = {
                    "sender": address,
                    "request": challenge.request,
                    "nonce": chain.signatures,
                }
                return Credential(
                    challenge.to_echo(),
                    {"type": "transaction", "signature": "0x" + canonical(payload).hex()},
                    source=f"did:pkh:eip155:{CHAIN_ID}:{address}",
                )

        return Method()

    def intent(self):
        chain = self

        class Intent:
            name = "charge"

            async def verify(self, credential, request):
                raw = bytes.fromhex(credential.payload["signature"][2:])
                transfer = json.loads(raw)
                assert transfer["request"] == request
                reference = "0x" + keccak(raw).hex()
                if reference not in chain.transactions:
                    chain.broadcasts += 1
                    chain.transactions[reference] = transfer
                    chain.balances[transfer["sender"].lower()] -= int(request["amount"])
                    chain.balances[request["recipient"].lower()] += int(request["amount"])
                return Receipt.success(reference)

            async def aclose(self):
                pass

        return Intent()


@pytest.fixture
def settings(tmp_path):
    wallets = tmp_path / "wallets"
    create_wallets(wallets)
    return Settings(
        _env_file=None,
        api_token="test-local-connection-token",
        payment_secret="test-mpp-challenge-secret",
        database=tmp_path / "mpp.db",
        wallets=wallets,
        catalog=ROOT / "catalog/providers.json",
        product_database_url="",
    )


@pytest.fixture
async def system(settings):
    chain = TestChain()
    providers = ProviderFixture(settings, intent_factory=chain.intent)
    addresses = settings.addresses()
    outgoing = PaidClient(
        settings,
        "openmcp",
        transport=httpx.ASGITransport(app=providers.app),
        method=chain.method(addresses["openmcp"]),
        chain=chain,
    )
    engine = Engine(settings, incoming_intent=chain.intent(), outgoing=outgoing, chain=chain)
    app = create_app(settings, engine, ledger=MemoryLedger())
    transport = httpx.ASGITransport(app=app)
    paid = PaidClient(
        settings, "agent", transport=transport, method=chain.method(addresses["agent"]), chain=chain
    )
    agent = Agent(settings, paid=paid, transport=transport)
    yield {
        "chain": chain,
        "engine": engine,
        "providers": providers,
        "agent": agent,
        "app": app,
        "settings": settings,
    }
    await agent.close()
    await engine.close()
    await providers.close()
