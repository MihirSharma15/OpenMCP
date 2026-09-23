"""Local testnet keys. Server code loads only openmcp.json; Claude loads agent.json."""

import asyncio
import json
import os
from pathlib import Path

import httpx
from eth_account import Account
from mpp.methods.tempo import TempoAccount

from .config import CHAIN_ID, EXPLORER, TOKEN, Settings
from .models import OpenMCPError

WALLET_NAMES = ("agent", "openmcp", "operations", "legal", "market")


def create_wallets(directory: Path) -> dict[str, str]:
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    addresses = {}
    for name in WALLET_NAMES:
        path = directory / f"{name}.json"
        if not path.exists():
            account = Account.create()
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as file:
                json.dump(
                    {
                        "address": account.address,
                        "private_key": "0x" + account.key.hex().removeprefix("0x"),
                    },
                    file,
                )
        account = load_wallet(directory, name)
        addresses[name] = account.address
    (directory / "public.json").write_text(json.dumps(addresses, indent=2) + "\n")
    return addresses


def load_wallet(directory: Path, name: str) -> TempoAccount:
    if name not in WALLET_NAMES:
        raise ValueError("Unknown demo wallet")
    data = json.loads((directory / f"{name}.json").read_text())
    account = TempoAccount.from_key(data["private_key"])
    if account.address.lower() != data["address"].lower():
        raise ValueError(f"Wallet address does not match key: {name}")
    return account


class Chain:
    def __init__(self, settings: Settings, transport=None):
        self.settings = settings
        self.http = httpx.AsyncClient(timeout=40, transport=transport)

    async def close(self):
        await self.http.aclose()

    async def rpc(self, method: str, params: list):
        response = await self.http.post(
            self.settings.rpc_url,
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        )
        response.raise_for_status()
        data = response.json()
        if "error" in data:
            raise OpenMCPError("rpc_error", f"Tempo RPC rejected {method}.", 503, True)
        return data["result"]

    async def check_network(self):
        if int(await self.rpc("eth_chainId", []), 16) != CHAIN_ID:
            raise ValueError("Only Tempo Moderato testnet (42431) is permitted")

    async def balance(self, address: str) -> dict:
        data = "0x70a08231" + address.removeprefix("0x").lower().zfill(64)
        units = int(await self.rpc("eth_call", [{"to": TOKEN, "data": data}, "latest"]), 16)
        return {
            "source": "tempo_testnet",
            "address": address,
            "token": "pathUSD",
            "token_address": TOKEN,
            "chain_id": CHAIN_ID,
            "balance_units": units,
            "decimals": 6,
            "balance": f"{units // 1_000_000}.{units % 1_000_000:06d}",
            "explorer_url": f"{EXPLORER}/address/{address}",
        }

    async def fund(self, address: str):
        await self.check_network()
        references = await self.rpc("tempo_fundAddress", [address])
        for _ in range(30):
            if (await self.balance(address))["balance_units"] > 0:
                return references
            await asyncio.sleep(0.5)
        raise OpenMCPError(
            "faucet_pending",
            "Faucet transfers submitted; check balances shortly with doctor --chain.",
            503,
            True,
        )

    async def verify_transfer(self, tx_hash, sender, recipient, cents, memo):
        receipt = await self.rpc("eth_getTransactionReceipt", [tx_hash])
        if not receipt or receipt.get("status") != "0x1":
            raise OpenMCPError(
                "payment_unconfirmed", "MPP transaction is not confirmed on Tempo.", 503, True
            )
        topic = "0x57bc7354aa85aed339e000bccffabbc529466af35f0772c8f8ee1145927de7f0"
        for log in receipt.get("logs", []):
            topics = log.get("topics", [])
            if (
                log.get("address", "").lower() == TOKEN.lower()
                and len(topics) == 4
                and topics[0].lower() == topic
                and topics[1][-40:].lower() == sender[2:].lower()
                and topics[2][-40:].lower() == recipient[2:].lower()
                and topics[3].lower() == memo.lower()
                and int(log.get("data", "0x0"), 16) == cents * 10_000
            ):
                return
        raise OpenMCPError(
            "invalid_transfer",
            "On-chain receipt does not contain the approved MPP transfer.",
            502,
            True,
        )
