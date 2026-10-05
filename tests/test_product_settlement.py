"""Actual MPP wire formats with simulated provider/RPC boundaries (no real funds)."""

import copy
import json
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from eth_account import Account
from eth_hash.auto import keccak
from mpp import BodyDigest, Challenge, Credential, Receipt
from mpp.methods.tempo import TempoAccount

from openmcp.payments import memo_for
from openmcp.product.config import ProductSettings, Service
from openmcp.product.models import canonical, now
from openmcp.product.settlement import PendingPayment, TerminalFailure, Treasury


@pytest.fixture
def payment_setup(tmp_path):
    service = Service(
        endpoint_id="example",
        name="Example",
        description="Example service",
        url="https://provider.example/buy",
        recipient="0x" + "12" * 20,
        price_cents=40,
        input_schema={"type": "object"},
        enabled=True,
        mode="test",
        supports_idempotency=True,
    )
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps([service.model_dump()]))
    settings = ProductSettings(_env_file=None, catalog_path=catalog)
    row = {
        "execution_id": "exe_one",
        "service": service.model_dump(),
        "payload": {"query": "hello"},
        "payment_authorization": None,
        "provider_price_cents": 36,
        "payment_status": "unsigned",
        "status": "reserved",
    }
    return settings, service, row


def challenge(settings, service, row, **overrides):
    request = {
        "amount": "360000",
        "currency": settings.token,
        "recipient": service.recipient,
        "methodDetails": {"chainId": settings.chain_id, "memo": memo_for(row["execution_id"])},
    }
    request.update(overrides)
    return Challenge.create(
        secret_key="test-server",
        realm="provider.example",
        method="tempo",
        intent="charge",
        request=request,
        digest=BodyDigest.compute(canonical(row["payload"])),
    )


async def test_real_treasury_sdk_constructor_and_private_key_file(payment_setup, tmp_path):
    settings, _, _ = payment_setup
    key = tmp_path / "treasury.json"
    account = Account.create()
    key.write_text(json.dumps({"private_key": account.key.hex()}))
    key.chmod(0o600)
    settings.treasury_key_file = key
    treasury = Treasury(
        settings, Mock(), transport=httpx.MockTransport(lambda r: httpx.Response(500))
    )
    assert treasury.method.intents["charge"] is treasury.intent
    assert treasury.account.address == account.address
    await treasury.close()
    key.chmod(0o644)
    with pytest.raises(ValueError, match="owner-only"):
        Treasury(settings, Mock())
    key.chmod(0o600)
    link = tmp_path / "linked.json"
    link.symlink_to(key)
    settings.treasury_key_file = link
    with pytest.raises(OSError):
        Treasury(settings, Mock())


@pytest.mark.parametrize(
    "overrides",
    [
        {"recipient": "0x" + "34" * 20},
        {"amount": "400000"},
        {"currency": "0x" + "56" * 20},
        {"methodDetails": {"chainId": 4217}},
        {"nonce_key": 42},
        {"methodDetails": {"chainId": 42431, "memo": "wrong", "feePayer": True}},
    ],
)
async def test_payment_terms_are_pinned_before_signing(payment_setup, overrides):
    settings, service, row = payment_setup
    treasury = Treasury(settings, Mock(), account=TempoAccount.from_key(Account.create().key.hex()))
    try:
        with pytest.raises(TerminalFailure):
            treasury.validate_challenge(
                challenge(settings, service, row, **overrides),
                canonical(row["payload"]),
                service,
                row["execution_id"],
            )
    finally:
        await treasury.close()


@pytest.mark.parametrize("failure", ["lost_reply", "missing_receipt", "none"])
async def test_journal_precedes_send_and_recovery_reuses_exact_credential(payment_setup, failure):
    settings, service, row = payment_setup
    account = TempoAccount.from_key(Account.create().key.hex())
    signatures, deliveries = [], []
    saved = copy.deepcopy(row)
    store = Mock()
    store.uncertain_signed.return_value = None
    store.execution_internal.side_effect = lambda _: copy.deepcopy(saved)

    def save(identifier, authorization, raw, header, txhash):
        saved.update(
            payment_authorization=authorization,
            challenge=raw,
            header_name=header,
            payment_hash=txhash,
            payment_status="signed",
            status="payment_pending",
        )

    store.mark_signed.side_effect = save
    store.mark_paid.side_effect = lambda *args: saved.update(
        payment_status="confirmed", status="fulfillment_pending"
    )
    store.finish.side_effect = lambda *args, **kwargs: saved.update(
        status="completed", data=kwargs["data"]
    )

    class Signer:
        async def create_credential(self, offered):
            signatures.append(offered)
            return Credential(
                challenge=offered.to_echo(),
                payload={"type": "transaction", "signature": "0x123456"},
            )

    paid = False

    def transport(request):
        nonlocal paid
        if request.url.host != "provider.example":
            message = json.loads(request.content)
            if message["method"] == "eth_chainId":
                result = hex(settings.chain_id)
            elif message["method"] == "eth_call":
                result = hex(6) if message["params"][0]["data"] == "0x313ce567" else hex(10_000_000)
            elif not paid:
                result = None
            else:
                result = {
                    "status": "0x1",
                    "logs": [
                        {
                            "address": settings.token,
                            "topics": [
                                "0x57bc7354aa85aed339e000bccffabbc529466af35f0772c8f8ee1145927de7f0",
                                "0x" + account.address[2:].zfill(64),
                                "0x" + service.recipient[2:].zfill(64),
                                memo_for(row["execution_id"]),
                            ],
                            "data": hex(360000),
                        }
                    ],
                }
            return httpx.Response(200, json={"jsonrpc": "2.0", "result": result})
        auth = request.headers.get("authorization")
        if not auth:
            return httpx.Response(
                402,
                headers={
                    "WWW-Authenticate": challenge(settings, service, row).to_www_authenticate(
                        "provider.example"
                    )
                },
            )
        assert saved["payment_authorization"] == auth  # committed before external send
        deliveries.append(auth)
        paid = True
        if len(deliveries) == 1 and failure == "lost_reply":
            raise httpx.ReadTimeout("simulated lost reply")
        headers = {}
        if len(deliveries) != 1 or failure != "missing_receipt":
            headers["Payment-Receipt"] = Receipt(
                status="success",
                timestamp=now(),
                reference="0x" + keccak(bytes.fromhex("123456")).hex(),
            ).to_payment_receipt()
        return httpx.Response(200, headers=headers, json={"answer": "real-format test result"})

    lock = Mock(spec=["assert_held"])
    treasury = Treasury(
        settings, store, account=account, method=Signer(), transport=httpx.MockTransport(transport)
    )
    try:
        if failure != "none":
            with pytest.raises((httpx.ReadTimeout, PendingPayment)):
                await treasury.purchase(row, lock)
            await treasury.close()
            # Restart constructs a new process adapter against the persisted journal.
            treasury = Treasury(
                settings,
                store,
                account=account,
                method=Signer(),
                transport=httpx.MockTransport(transport),
            )
            await treasury.purchase(copy.deepcopy(saved), lock)
        else:
            await treasury.purchase(row, lock)
        assert len(signatures) == 1
        assert len(set(deliveries)) == 1
        assert saved["status"] == "completed"
        assert saved["data"]["answer"] == "real-format test result"
    finally:
        await treasury.close()


async def test_unknown_signed_payment_blocks_new_signature(payment_setup):
    settings, _, row = payment_setup
    store = Mock()
    store.uncertain_signed.return_value = {"execution_id": "earlier"}
    method = SimpleNamespace(create_credential=Mock())
    treasury = Treasury(
        settings, store, account=TempoAccount.from_key(Account.create().key.hex()), method=method
    )
    try:
        with pytest.raises(PendingPayment, match="earlier"):
            await treasury.purchase(row, Mock(spec=["assert_held"]))
        method.create_credential.assert_not_called()
    finally:
        await treasury.close()
