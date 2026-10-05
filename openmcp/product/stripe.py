"""Stripe-hosted Checkout, verified webhooks, and canonical provider reconciliation.

Uses Stripe's HTTPS API directly; card details never pass through OpenMCP. Enable
Link in Stripe's payment-method configuration; dynamic methods are left enabled.
"""

import hashlib
import hmac
import json
import re
import time
from datetime import timedelta
from urllib.parse import urlsplit

import httpx

from .models import ProductError, now


class StripeGateway:
    def __init__(self, settings, store, *, transport=None):
        self.settings, self.store = settings, store
        self.http = httpx.AsyncClient(
            base_url="https://api.stripe.com/v1/",
            timeout=20,
            follow_redirects=False,
            transport=transport,
            auth=(settings.stripe_key.get_secret_value(), ""),
            headers={"Stripe-Version": settings.stripe_api_version},
        )

    async def close(self):
        await self.http.aclose()

    async def request(self, method, path, **kwargs):
        try:
            response = await self.http.request(method, path, **kwargs)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("Invalid Stripe response")
            return data
        except (httpx.HTTPError, ValueError) as exc:
            raise ProductError(
                "stripe_unavailable",
                "Payment service unavailable. Retry this same request.",
                503,
                True,
            ) from exc

    @staticmethod
    def resource(value):
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_]{1,255}", value):
            raise ProductError("invalid_stripe_resource", "Invalid payment reference.", 409)
        return value

    async def create(self, top):
        if top["checkout_id"]:
            return await self.reconcile(top["checkout_id"])
        # Stripe may evict an idempotency key after 24h. Never create a second
        # Checkout for an uncertain old request; operator can locate its metadata.
        if now() - top["created_at"] > timedelta(hours=23):
            raise ProductError(
                "checkout_needs_review",
                "This checkout needs payment reconciliation before retrying.",
                409,
            )
        account = self.store.account(top["account_id"])
        customer = account["stripe_customer_id"]
        if not customer:
            # Stripe's durable metadata supports operator recovery if the customer
            # creation response is lost; creation and checkout share a <23h window.
            created = await self.request(
                "POST",
                "customers",
                data={"metadata[account_id]": top["account_id"]},
                headers={"Idempotency-Key": "customer-" + top["account_id"]},
            )
            customer = created["id"]
            self.store.save_customer(top["account_id"], customer)
        return_url = f"{self.settings.frontend_url.rstrip('/')}/dashboard/top-up/return?top_up_id={top['id']}"
        fields = {
            "mode": "payment",
            "customer": customer,
            "client_reference_id": top["account_id"],
            "success_url": return_url,
            "cancel_url": return_url + "&canceled=1",
            "line_items[0][quantity]": "1",
            "line_items[0][price_data][currency]": "usd",
            "line_items[0][price_data][unit_amount]": str(top["amount_cents"]),
            "line_items[0][price_data][product_data][name]": "OpenMCP prepaid service credits",
            "metadata[top_up_id]": top["id"],
            "metadata[account_id]": top["account_id"],
            "payment_intent_data[metadata][top_up_id]": top["id"],
            "payment_intent_data[metadata][account_id]": top["account_id"],
        }
        session = await self.request(
            "POST", "checkout/sessions", data=fields, headers={"Idempotency-Key": top["id"]}
        )
        return self.apply_session(session)

    def verify_mode(self, resource):
        if resource.get("livemode") is not (self.settings.mode == "live"):
            raise ProductError(
                "payment_mode_mismatch", "Payment mode does not match this application.", 409
            )

    def apply_session(self, session, *, failed=False):
        self.verify_mode(session)
        meta = session.get("metadata", {})
        top = self.store.top_up_internal(meta.get("top_up_id"))
        if not top:
            raise ProductError(
                "unknown_top_up", "Checkout does not belong to this application.", 404
            )
        if (
            meta.get("account_id") != top["account_id"]
            or session.get("client_reference_id") != top["account_id"]
            or session.get("mode") != "payment"
            or session.get("currency") != "usd"
            or type(session.get("amount_total")) is not int
            or session["amount_total"] != top["amount_cents"]
        ):
            raise ProductError(
                "payment_mismatch", "Checkout amount, currency, or owner does not match.", 409
            )
        if session.get("url"):
            parsed = urlsplit(session["url"])
            if (
                parsed.scheme != "https"
                or parsed.hostname != "checkout.stripe.com"
                or parsed.username
            ):
                raise ProductError(
                    "invalid_checkout_url", "Stripe returned an unexpected checkout URL.", 502
                )
        session = dict(session)
        session["_failed"] = failed
        return self.store.checkout_state(
            top["id"], session, paid=session.get("payment_status") == "paid"
        )

    async def reconcile(self, checkout_id, *, failed=False):
        session = await self.request("GET", "checkout/sessions/" + self.resource(checkout_id))
        return self.apply_session(session, failed=failed)

    def verify_webhook(self, body, signature):
        try:
            entries = [part.split("=", 1) for part in signature.split(",")]
            timestamps = [value for key, value in entries if key == "t"]
            signatures = [value for key, value in entries if key == "v1"]
            if len(timestamps) != 1 or abs(time.time() - int(timestamps[0])) > 300:
                raise ValueError("Expired signature")
            expected = hmac.new(
                self.settings.stripe_webhook_secret.get_secret_value().encode(),
                timestamps[0].encode() + b"." + body,
                hashlib.sha256,
            ).hexdigest()
            if not any(hmac.compare_digest(expected, item) for item in signatures):
                raise ValueError("Bad signature")
            event = json.loads(body)
            if (
                not isinstance(event, dict)
                or not isinstance(event["id"], str)
                or not isinstance(event["type"], str)
                or type(event["created"]) is not int
                or not isinstance(event["data"]["object"]["id"], str)
            ):
                raise ValueError("Malformed event")
            self.verify_mode(event)
            return event
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise ProductError(
                "invalid_signature", "Stripe webhook signature or event is invalid.", 400
            ) from exc

    async def process_event(self, event):
        kind, object_id = event["type"], event["object_id"]
        if kind in {
            "checkout.session.completed",
            "checkout.session.async_payment_succeeded",
            "checkout.session.async_payment_failed",
            "checkout.session.expired",
        }:
            session = await self.request("GET", "checkout/sessions/" + self.resource(object_id))
            top_id = session.get("metadata", {}).get("top_up_id")
            if not self.store.top_up_internal(top_id):
                return  # Other products may share the Stripe account.
            self.apply_session(session, failed=kind == "checkout.session.async_payment_failed")
        elif kind in {
            "charge.refunded",
            "charge.dispute.created",
            "charge.dispute.updated",
            "charge.dispute.closed",
            "charge.dispute.funds_withdrawn",
            "charge.dispute.funds_reinstated",
        }:
            dispute = None
            if kind.startswith("charge.dispute."):
                dispute = await self.request("GET", "disputes/" + self.resource(object_id))
                self.verify_mode(dispute)
                charge_id = dispute["charge"]
            else:
                charge_id = object_id
            charge = await self.request("GET", "charges/" + self.resource(charge_id))
            self.verify_mode(charge)
            intent = await self.request(
                "GET", "payment_intents/" + self.resource(charge["payment_intent"])
            )
            self.verify_mode(intent)
            top_id = intent.get("metadata", {}).get("top_up_id")
            top = self.store.top_up_internal(top_id)
            if not top:
                return
            if (
                intent.get("metadata", {}).get("account_id") != top["account_id"]
                or charge.get("currency") != "usd"
                or charge.get("amount") != top["amount_cents"]
                or (top["payment_intent_id"] and top["payment_intent_id"] != intent["id"])
            ):
                raise ProductError(
                    "payment_mismatch", "Funding reversal does not match its deposit.", 409
                )
            disputed = None
            if dispute:
                # balance_transactions records actual principal movement. Warnings
                # and inquiries can be open without any withdrawal.
                movements = dispute.get("balance_transactions", [])
                if not all(
                    isinstance(item, dict)
                    and item.get("currency") == "usd"
                    and type(item.get("amount")) is int
                    for item in movements
                ):
                    raise ProductError(
                        "dispute_unreconciled", "Dispute funding evidence is incomplete.", 409
                    )
                disputed = max(0, -sum(item["amount"] for item in movements))
            self.store.funding_reversal(
                top_id,
                charge_id=charge_id,
                refund_cents=int(charge.get("amount_refunded", 0)),
                disputed_cents=disputed,
                dispute_open=bool(
                    dispute
                    and dispute.get("status") not in {"won", "lost", "warning_closed", "prevented"}
                ),
                event_created=event["event_created"],
            )
