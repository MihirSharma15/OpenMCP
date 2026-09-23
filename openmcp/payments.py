"""Real MPP/Tempo charge exchange. No Stripe and no payment simulation in runtime."""

import asyncio
import hashlib
import json
from dataclasses import asdict

import httpx
from eth_hash.auto import keccak
from mpp import BodyDigest, Challenge, Credential, Receipt
from mpp.methods.tempo import ChargeIntent, tempo
from mpp.server import Mpp

from .config import CHAIN_ID, EXPLORER, TOKEN, Settings
from .models import OpenMCPError
from .store import PaymentJournal, ReplayStore
from .wallets import Chain, load_wallet


def canonical(body) -> bytes:
    return json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


def memo_for(identifier: str) -> str:
    return "0x" + hashlib.sha256(identifier.encode()).hexdigest()


def receipt_dict(receipt: Receipt) -> dict:
    return {
        **asdict(receipt),
        "timestamp": receipt.timestamp.isoformat(),
        "chain_id": CHAIN_ID,
        "explorer_url": f"{EXPLORER}/tx/{receipt.reference}",
        "header": receipt.to_payment_receipt(),
    }


def make_receiver(
    settings: Settings,
    recipient: str,
    *,
    realm="openmcp.local",
    secret=None,
    database=None,
    requires_auth=False,
    intent=None,
):
    intent = intent or ChargeIntent(chain_id=CHAIN_ID, rpc_url=settings.rpc_url, timeout=40)
    receiver = Mpp.create(
        method=tempo(
            intents={"charge": intent},
            chain_id=CHAIN_ID,
            rpc_url=settings.rpc_url,
            currency=TOKEN,
            recipient=recipient,
        ),
        realm=realm,
        secret_key=secret or settings.payment_secret.get_secret_value(),
        store=ReplayStore(database or settings.database),
        requires_auth=requires_auth,
    )
    return receiver, intent


class PaidClient:
    """A wallet on the caller side: get challenge, check policy, sign once, retry with credential.

    Used by Claude's LOCAL stdio tool with agent.json, and by OpenMCP with openmcp.json.
    Signed credentials are journaled before the HTTP retry. A second 402 never signs again.
    """

    def __init__(self, settings: Settings, owner: str, *, transport=None, method=None, chain=None):
        self.settings = settings
        self.account = load_wallet(settings.wallets, owner)
        self.intent = ChargeIntent(chain_id=CHAIN_ID, rpc_url=settings.rpc_url)
        self.method = method or tempo(
            intents={"charge": self.intent},
            account=self.account,
            chain_id=CHAIN_ID,
            rpc_url=settings.rpc_url,
            currency=TOKEN,
        )
        self.journal = PaymentJournal(settings.database.parent / f"{owner}-payments.sqlite3")
        self.http = httpx.AsyncClient(
            timeout=settings.provider_timeout_seconds, follow_redirects=False, transport=transport
        )
        self.chain = chain or Chain(settings)
        self.lock = asyncio.Lock()

    async def close(self):
        await self.http.aclose()
        await self.intent.aclose()
        await self.chain.close()

    async def _request(self, url, body, headers):
        async with self.http.stream("POST", url, content=body, headers=headers) as response:
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > 1_000_000:
                    raise OpenMCPError(
                        "response_too_large",
                        "Paid response exceeds 1 MB; retry the same request.",
                        502,
                        True,
                    )
            return httpx.Response(
                response.status_code, headers=response.headers, content=bytes(data)
            )

    @staticmethod
    def check_challenge(challenge, body, recipient, cents, memo):
        request = challenge.request
        details = request.get("methodDetails", {})
        valid = (
            challenge.method == "tempo"
            and challenge.intent == "charge"
            and request.get("currency", "").lower() == TOKEN.lower()
            and request.get("recipient", "").lower() == recipient.lower()
            and request.get("amount") == str(cents * 10_000)
            and details.get("chainId") == CHAIN_ID
            and details.get("memo", "").lower() == memo.lower()
            and not details.get("splits")
            and not details.get("feePayer")
            and challenge.header in (None, "Payment-Authorization")
            and challenge.digest is not None
            and BodyDigest.verify(challenge.digest, body)
        )
        if not valid:
            raise OpenMCPError(
                "unapproved_challenge",
                "MPP challenge does not match approved amount, wallet, network, token, or request.",
                409,
            )

    async def post(
        self,
        url,
        payload,
        *,
        key,
        recipient,
        cents,
        scope,
        budget,
        memo,
        headers=None,
        on_event=None,
    ):
        body = canonical(payload)
        headers = {"Content-Type": "application/json", "Idempotency-Key": key, **(headers or {})}
        fingerprint = hashlib.sha256(
            canonical(
                {"url": url, "body": payload, "recipient": recipient, "amount": cents, "memo": memo}
            )
        ).hexdigest()
        journal_key = f"{scope}:{key}"

        async def emit(kind, **detail):
            if on_event:
                on_event(kind, **detail)

        async with self.lock:
            saved = self.journal.get(journal_key)
            if saved and saved["fingerprint"] != fingerprint:
                raise OpenMCPError(
                    "idempotency_conflict", "Wallet key already belongs to another payment.", 409
                )
            if not saved:
                response = await self._request(url, body, headers)
                if response.status_code != 402:
                    # A configured paid route must actually require MPP. Do not accept a free stub as a paid success.
                    if response.is_success:
                        raise OpenMCPError(
                            "mpp_required",
                            "Paid endpoint returned data without an MPP challenge.",
                            502,
                        )
                    return response
                raw = response.headers.get("WWW-Authenticate", "")
                try:
                    challenge = Challenge.from_www_authenticate(raw)
                except Exception as exc:
                    raise OpenMCPError(
                        "invalid_challenge", "Provider did not return a valid MPP challenge.", 502
                    ) from exc
                self.check_challenge(challenge, body, recipient, cents, memo)
                await emit("challenge_received", amount_cents=cents, challenge_id=challenge.id)
                # Check network even for signing; an overridden RPC may never redirect us to mainnet.
                await self.chain.check_network()
                credential = await self.method.create_credential(challenge)
                saved = {
                    "fingerprint": fingerprint,
                    "authorization": credential.to_authorization(),
                    "challenge": raw,
                    "header_name": challenge.header or "Authorization",
                    "receipt": None,
                }
                self.journal.save(journal_key, scope, cents, saved, budget)
                await emit("credential_created", amount_cents=cents, challenge_id=challenge.id)
            headers[saved["header_name"]] = saved["authorization"]
            response = await self._request(url, body, headers)
            if response.status_code == 402:
                raise OpenMCPError(
                    "credential_rejected",
                    "The saved MPP credential was rejected. It was not replaced or paid again; reconcile this request before retrying with a new key.",
                    409,
                )
            receipt_header = response.headers.get("Payment-Receipt")
            if receipt_header:
                receipt = Receipt.from_payment_receipt(receipt_header)
                credential = Credential.from_authorization(saved["authorization"])
                expected_hash = (
                    "0x"
                    + keccak(
                        bytes.fromhex(credential.payload["signature"].removeprefix("0x"))
                    ).hex()
                )
                if (
                    receipt.method != "tempo"
                    or receipt.status != "success"
                    or receipt.reference.lower() != expected_hash.lower()
                ):
                    raise OpenMCPError(
                        "invalid_receipt",
                        "MPP receipt does not match the signed payment.",
                        502,
                        True,
                    )
                if not saved["receipt"]:
                    await self.chain.verify_transfer(
                        receipt.reference, self.account.address, recipient, cents, memo
                    )
                    saved["receipt"] = receipt_dict(receipt)
                    self.journal.save(journal_key, scope, cents, saved, budget)
                    await emit("payment_confirmed", amount_cents=cents, receipt=saved["receipt"])
            elif response.is_success:
                raise OpenMCPError(
                    "missing_receipt",
                    "Paid endpoint returned no MPP receipt; payment may have settled. Retry the same key.",
                    502,
                    True,
                )
            return response
