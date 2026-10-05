"""One outgoing MPP/Tempo payment from a separately funded platform treasury.

Signed transactions are journaled before the provider sees them. Recovery only
replays that exact credential. An unconfirmed signed transaction blocks further
signing because the treasury has one nonce stream.
"""

import json
import os
import stat

import httpx
from eth_hash.auto import keccak
from mpp import BodyDigest, Challenge, Receipt
from mpp.methods.tempo import ChargeIntent, TempoAccount, tempo

from ..payments import memo_for
from .config import Service
from .models import ProductError, canonical


class TerminalFailure(Exception):
    def __init__(self, message, *, reverted=False):
        super().__init__(message)
        self.reverted = reverted


class PendingPayment(Exception):
    pass


class Treasury:
    def __init__(self, settings, store, *, transport=None, account=None, method=None):
        self.settings, self.store = settings, store
        if account is None:
            if not settings.treasury_key_file:
                raise ValueError("OPENMCP_TREASURY_KEY_FILE is required by the payment worker")
            path = settings.treasury_key_file
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(fd) as handle:
                info = os.fstat(handle.fileno())
                if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
                    raise ValueError("Treasury key must be a regular owner-only file (chmod 600)")
                key = handle.read().strip()
            if key.startswith("{"):
                key = json.loads(key)["private_key"]
            account = TempoAccount.from_key(key)
        self.account = account
        self.store.bind_treasury(account.address)
        self.intent = ChargeIntent(chain_id=settings.chain_id, rpc_url=settings.rpc_url)
        self.method = method or tempo(
            intents={"charge": self.intent},
            account=account,
            chain_id=settings.chain_id,
            rpc_url=settings.rpc_url,
            currency=settings.token,
        )
        self.http = httpx.AsyncClient(
            timeout=settings.provider_timeout, transport=transport, follow_redirects=False
        )

    async def close(self):
        await self.http.aclose()
        await self.intent.aclose()

    async def rpc(self, method, params):
        try:
            response = await self.http.post(
                self.settings.rpc_url,
                json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
            )
            response.raise_for_status()
            data = response.json()
            if "error" in data or "result" not in data:
                raise ValueError("RPC rejected request")
            return data["result"]
        except (httpx.HTTPError, ValueError) as exc:
            raise PendingPayment("Treasury network confirmation is unavailable.") from exc

    async def network_and_balance(self):
        if int(await self.rpc("eth_chainId", []), 16) != self.settings.chain_id:
            raise TerminalFailure("Treasury RPC network does not match the approved chain.")
        decimals = int(
            await self.rpc(
                "eth_call", [{"to": self.settings.token, "data": "0x313ce567"}, "latest"]
            ),
            16,
        )
        if decimals != 6:
            raise TerminalFailure("Treasury token must have six decimals.")
        data = "0x70a08231" + self.account.address[2:].lower().zfill(64)
        return int(
            await self.rpc("eth_call", [{"to": self.settings.token, "data": data}, "latest"]), 16
        )

    def validate_challenge(self, challenge, body, service, execution_id):
        request = challenge.request
        detail = request.get("methodDetails", {})
        valid = (
            isinstance(detail, dict)
            and challenge.method == "tempo"
            and challenge.intent == "charge"
            and request.get("currency", "").lower() == self.settings.token.lower()
            and request.get("recipient", "").lower() == service.recipient.lower()
            and request.get("amount") == str(service.provider_price_cents * 10_000)
            and detail.get("chainId") == self.settings.chain_id
            and detail.get("memo", "").lower() == memo_for(execution_id)
            and not detail.get("splits")
            and not detail.get("feePayer")
            and request.get("nonce_key", 0) == 0
            and challenge.header in (None, "Authorization", "Payment-Authorization")
            and challenge.digest is not None
            and BodyDigest.verify(challenge.digest, body)
        )
        if not valid:
            raise TerminalFailure("Provider payment challenge differs from approved payment terms.")

    async def request(self, service, body, headers):
        async with self.http.stream("POST", service.url, content=body, headers=headers) as response:
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > 1_000_000:
                    raise PendingPayment("Provider response exceeded the maximum size.")
            return httpx.Response(
                response.status_code, headers=response.headers, content=bytes(content)
            )

    async def confirmation(self, row, service):
        receipt = await self.rpc("eth_getTransactionReceipt", [row["payment_hash"]])
        if receipt is None:
            return None
        if receipt.get("status") == "0x0":
            raise TerminalFailure(
                "The approved provider transfer reverted on chain.", reverted=True
            )
        if receipt.get("status") != "0x1":
            raise PendingPayment("The provider payment is not confirmed.")
        transfer_topic = "0x57bc7354aa85aed339e000bccffabbc529466af35f0772c8f8ee1145927de7f0"
        for log in receipt.get("logs", []):
            topics = log.get("topics", [])
            if (
                log.get("address", "").lower() == self.settings.token.lower()
                and len(topics) == 4
                and topics[0].lower() == transfer_topic
                and topics[1][-40:].lower() == self.account.address[2:].lower()
                and topics[2][-40:].lower() == service.recipient[2:].lower()
                and topics[3].lower() == memo_for(row["execution_id"])
                and int(log.get("data", "0x0"), 16) == row["provider_price_cents"] * 10_000
            ):
                return {
                    "reference": row["payment_hash"],
                    "explorer_url": f"{self.settings.explorer_url.rstrip('/')}/tx/{row['payment_hash']}",
                }
        raise PendingPayment(
            "Confirmed transaction does not contain the approved transfer; review required."
        )

    @staticmethod
    def ensure_lock(lock_connection):
        if lock_connection is None or lock_connection.closed:
            raise ProductError("worker_lease_lost", "Treasury worker lock was lost.", 503, True)
        lock_connection.execute("SELECT 1")
        lock_connection.commit()

    async def purchase(self, row, lock_connection):
        service = Service.model_validate(row["service"])
        # Removing/disabling a service stops new signatures. Already signed transfers
        # remain reconcilable using the immutable approved snapshot.
        body = canonical(row["payload"])
        headers = {
            "Content-Type": "application/json",
            "Idempotency-Key": row["execution_id"],
            "X-OpenMCP-Execution-ID": row["execution_id"],
        }
        if not row["payment_authorization"]:
            current = self.settings.services().get(service.endpoint_id)
            if not current or current.model_dump() != service.model_dump():
                raise TerminalFailure(
                    "Service terms changed before settlement. Discover and authorize a new purchase."
                )
            if self.store.uncertain_signed(row["execution_id"]):
                raise PendingPayment("Treasury is reconciling an earlier signed payment.")
            balance = await self.network_and_balance()
            if balance < (row["provider_price_cents"] + self.settings.fee_reserve_cents) * 10_000:
                raise TerminalFailure(
                    "Platform settlement funds are unavailable; customer credits returned."
                )
            response = await self.request(service, body, headers)
            if response.status_code != 402:
                if response.status_code >= 500 or response.status_code == 429:
                    raise PendingPayment("Provider is temporarily unavailable before payment.")
                raise TerminalFailure("Provider did not offer the required MPP payment challenge.")
            try:
                raw_challenge = response.headers["WWW-Authenticate"]
                challenge = Challenge.from_www_authenticate(raw_challenge)
                self.validate_challenge(challenge, body, service, row["execution_id"])
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                raise TerminalFailure("Provider returned an invalid payment challenge.") from exc
            self.ensure_lock(lock_connection)
            credential = await self.method.create_credential(challenge)
            self.ensure_lock(lock_connection)
            authorization = credential.to_authorization()
            payment_hash = (
                "0x"
                + keccak(bytes.fromhex(credential.payload["signature"].removeprefix("0x"))).hex()
            )
            self.store.mark_signed(
                row["execution_id"],
                authorization,
                raw_challenge,
                challenge.header or "Authorization",
                payment_hash,
            )
            row = self.store.execution_internal(row["execution_id"])
        else:
            if int(await self.rpc("eth_chainId", []), 16) != self.settings.chain_id:
                raise PendingPayment("Configured RPC cannot reconcile this payment network.")
            receipt = await self.confirmation(row, service)
            if receipt:
                self.store.mark_paid(row["execution_id"], receipt)
        self.ensure_lock(lock_connection)
        headers[row["header_name"]] = row["payment_authorization"]
        response = await self.request(service, body, headers)
        receipt_header = response.headers.get("Payment-Receipt")
        if receipt_header:
            try:
                received = Receipt.from_payment_receipt(receipt_header)
                if (
                    received.method != "tempo"
                    or received.status != "success"
                    or received.reference.lower() != row["payment_hash"].lower()
                ):
                    raise ValueError("Mismatched receipt")
            except (ValueError, KeyError, TypeError) as exc:
                raise PendingPayment(
                    "Provider receipt does not match the journaled payment."
                ) from exc
        receipt = await self.confirmation(row, service)
        if receipt:
            self.store.mark_paid(row["execution_id"], receipt)
        else:
            raise PendingPayment("The signed provider payment is awaiting chain confirmation.")
        if response.is_success:
            if not receipt_header:
                raise PendingPayment(
                    "Provider result is missing its MPP receipt; retrying the saved credential."
                )
            try:
                data = response.json()
                canonical(data)  # Reject non-finite values before PostgreSQL storage.
                if not isinstance(data, dict):
                    raise ValueError("Not an object")
            except (ValueError, TypeError) as exc:
                raise TerminalFailure(
                    "Provider returned an unusable result after confirmed payment."
                ) from exc
            self.store.finish(row["execution_id"], data=data)
        elif response.status_code in {400, 404, 410, 422}:
            raise TerminalFailure("Provider confirmed payment but could not fulfill the request.")
        else:
            raise PendingPayment("Provider payment is confirmed; result delivery is still pending.")
