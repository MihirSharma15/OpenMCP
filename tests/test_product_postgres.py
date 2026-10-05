"""Mandatory-in-CI PostgreSQL acceptance tests for real accounting and HTTP ownership.

Set OPENMCP_REQUIRE_POSTGRES=1 to fail rather than skip when PostgreSQL is absent.
External identity keys/payment responses are local test fixtures; the Store and
all accounting transactions, concurrency, API routes and worker are production code.
"""

import hashlib
import hmac
import json
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import httpx
import jwt
import psycopg
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from openmcp.database import DatabaseManager
from openmcp.product.app import create_app
from openmcp.product.config import ProductSettings, Service
from openmcp.product.models import Principal, ProductError, now
from openmcp.product.settlement import TerminalFailure
from openmcp.product.store import Store
from openmcp.product.stripe import StripeGateway
from openmcp.product.worker import Worker


@pytest.fixture(scope="module")
def postgres_url():
    url = os.environ.get(
        "OPENMCP_PRODUCT_DATABASE_URL", "postgresql://openmcp:openmcp@localhost:5433/openmcp"
    )
    try:
        with psycopg.connect(url, connect_timeout=10) as connection:
            connection.execute("SELECT 1")
    except psycopg.Error:
        if os.environ.get("OPENMCP_REQUIRE_POSTGRES") == "1":
            pytest.fail(
                "Required PostgreSQL unavailable at OPENMCP_PRODUCT_DATABASE_URL; accounting integration was not run."
            )
        pytest.skip("PostgreSQL unavailable; set OPENMCP_REQUIRE_POSTGRES=1 to make this a failure")
    return url


@pytest.fixture
def store(postgres_url):
    name = "product_test_" + uuid.uuid4().hex
    value = Store(postgres_url, name)
    value.migrate()
    runtime_url = os.environ.get("OPENMCP_TEST_RUNTIME_DATABASE_URL")
    if runtime_url:
        role = conninfo_to_dict(runtime_url)["user"].split(".")[0]
        with psycopg.connect(postgres_url) as connection:
            connection.execute(
                sql.SQL("GRANT {} TO {}").format(
                    sql.Identifier(name + "_runtime"), sql.Identifier(role)
                )
            )
        value.close()
        value = Store(
            DatabaseManager(
                runtime_url, name, provider=os.environ.get("OPENMCP_DATABASE_PROVIDER", "postgres")
            )
        )
    try:
        yield value
    finally:
        value.close()
        with psycopg.connect(postgres_url) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(name)))
            connection.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(name + "_runtime")))


@pytest.fixture
def service():
    return Service(
        endpoint_id="example",
        name="Example",
        description="Useful example service",
        url="https://provider.example/buy",
        recipient="0x" + "12" * 20,
        price_cents=40,
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
        enabled=True,
        mode="test",
        supports_idempotency=True,
    )


def credit(store, account_id, amount=1000):
    top = store.create_top_up(account_id, uuid.uuid4().hex, amount)
    session = {
        "id": "cs_" + top["id"],
        "url": "https://checkout.stripe.com/c/pay/test",
        "status": "complete",
        "expires_at": int(time.time()) + 1000,
        "payment_intent": "pi_" + top["id"],
    }
    store.checkout_state(top["id"], session, paid=True)
    return top, session


def grant(store, account_id, cap=200):
    agent = store.create_agent(account_id, "Research", cap, now() + timedelta(days=1))
    credential = store.issue(account_id, agent["agent_id"])
    return store.authenticate_agent(credential["secret"]), credential


def purchase(service):
    return {
        "endpoint_id": service.endpoint_id,
        "payload": {"query": "answer"},
        "max_price_cents": service.price_cents,
    }


def test_concurrent_bootstrap_is_one_account(store):
    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(lambda _: store.bootstrap("issuer_and_subject"), range(16)))
    assert len({row["account_id"] for row in rows}) == 1


def test_topup_replay_and_reversals_are_exactly_once_including_out_of_order(store):
    owner = store.bootstrap("subject")["account_id"]
    top, session = credit(store, owner)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: store.checkout_state(top["id"], session, paid=True), range(16)))
    assert store.wallet(Principal(owner))["balance_cents"] == 1000
    store.funding_reversal(top["id"], charge_id="ch_one", refund_cents=200)
    store.funding_reversal(top["id"], charge_id="ch_one", refund_cents=200)
    assert store.wallet(Principal(owner))["balance_cents"] == 800
    # An older smaller refund observation cannot restore already reversed funds.
    store.funding_reversal(top["id"], charge_id="ch_one", refund_cents=100)
    assert store.wallet(Principal(owner))["balance_cents"] == 800
    early = store.create_top_up(owner, "early-refund", 500)
    store.funding_reversal(early["id"], charge_id="ch_early", refund_cents=500)
    store.checkout_state(
        early["id"], session | {"id": "cs_early", "payment_intent": "pi_early"}, paid=True
    )
    assert store.wallet(Principal(owner))["balance_cents"] == 800
    transactions = store.transactions(owner, 100, None, None, None)["items"]
    assert len([row for row in transactions if row["type"] == "deposit"]) == 2
    assert len([row for row in transactions if row["type"] == "reversal"]) == 2


@pytest.mark.parametrize(
    "funding,cap,error", [(80, 200, "insufficient_funds"), (1000, 80, "spending_limit_exceeded")]
)
def test_atomic_concurrent_reservations_cannot_overspend_wallet_or_cap(
    store, service, funding, cap, error
):
    owner = store.bootstrap("subject")["account_id"]
    credit(store, owner, funding)
    principal, _ = grant(store, owner, cap)

    def attempt(index):
        try:
            return store.reserve(principal, str(index), purchase(service), service)["execution_id"]
        except ProductError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(16)))
    assert len([value for value in results if value.startswith("exe_")]) == 2
    assert results.count(error) == 14
    wallet = store.wallet(principal)
    assert wallet["reserved_cents"] == wallet["agent"]["reserved_cents"] == 80


def test_idempotency_restart_and_terminal_transition_guards(store, service):
    owner = store.bootstrap("subject")["account_id"]
    credit(store, owner)
    principal, _ = grant(store, owner)
    original = store.reserve(principal, "one", purchase(service), service)
    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(
            pool.map(
                lambda _: store.reserve(principal, "one", purchase(service), service), range(8)
            )
        )
    assert {row["execution_id"] for row in rows} == {original["execution_id"]}
    with pytest.raises(ProductError) as caught:
        store.reserve(
            principal, "one", purchase(service) | {"payload": {"query": "different"}}, service
        )
    assert caught.value.code == "idempotency_conflict"
    store.mark_signed(
        original["execution_id"], "secret-signed-credential", "challenge", "Authorization", "0xtest"
    )
    restored = Store(store.dsn, store.schema)
    assert (
        restored.execution_internal(original["execution_id"])["payment_authorization"]
        == "secret-signed-credential"
    )
    with pytest.raises(ProductError, match="Reconcile"):
        restored.finish(original["execution_id"], refund_reason="timeout is not proof")
    restored.mark_paid(
        original["execution_id"],
        {"reference": "0xtest", "explorer_url": "https://explore.tempo.xyz/tx/0xtest"},
    )
    restored.finish(original["execution_id"], data={"answer": "done"})
    restored.finish(original["execution_id"], data={"answer": "retry"})
    restored.retry_execution(original["execution_id"], "late error", 1, 1)
    restored.needs_review(original["execution_id"], "late review")
    assert restored.execution_internal(original["execution_id"])["status"] == "completed"
    assert restored.wallet(principal)["balance_cents"] == 960
    assert restored.wallet(principal)["reserved_cents"] == 0
    assert restored.wallet(principal)["agent"]["spent_cents"] == 40


def test_terminal_failure_refund_once_and_shared_replacement_cap(store, service):
    owner = store.bootstrap("subject")["account_id"]
    credit(store, owner)
    principal, original_credential = grant(store, owner, 40)
    row = store.reserve(principal, "one", purchase(service), service)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(
            pool.map(
                lambda _: store.finish(
                    row["execution_id"], refund_reason="provider cannot fulfill"
                ),
                range(8),
            )
        )
    store.needs_review(row["execution_id"], "late error cannot reopen")
    assert store.execution_internal(row["execution_id"])["status"] == "refunded"
    assert store.wallet(principal)["available_cents"] == 1000
    assert store.wallet(principal)["agent"]["remaining_cents"] == 40
    refunds = store.transactions(owner, 100, None, "refund", None)["items"]
    assert (
        len(refunds) == 1 and refunds[0]["related_transaction_id"] == row["ledger_transaction_id"]
    )
    replacement = store.issue(owner, principal.agent_id)
    other = store.authenticate_agent(replacement["secret"])
    next_row = store.reserve(other, "two", purchase(service), service)
    store.mark_paid(next_row["execution_id"], {"reference": "0xpaid"})
    store.finish(next_row["execution_id"], data={"answer": "done"})
    credit(store, owner)
    assert store.wallet(other)["agent"]["remaining_cents"] == 0
    with pytest.raises(ProductError) as caught:
        store.reserve(principal, "three", purchase(service), service)
    assert caught.value.code == "spending_limit_exceeded"
    store.revoke(owner, principal.agent_id, original_credential["credential_id"])
    with pytest.raises(ProductError):
        store.authenticate_agent(original_credential["secret"])
    assert store.authenticate_agent(replacement["secret"]).agent_id == principal.agent_id


def test_disputes_restrict_without_phantom_debits_and_deficit_can_be_cured(store, service):
    owner = store.bootstrap("subject")["account_id"]
    top, _ = credit(store, owner, 40)
    principal, _ = grant(store, owner)
    row = store.reserve(principal, "one", purchase(service), service)
    store.mark_paid(row["execution_id"], {"reference": "0xpaid"})
    store.finish(row["execution_id"], data={"answer": "done"})
    store.funding_reversal(
        top["id"],
        charge_id="ch_one",
        refund_cents=0,
        disputed_cents=0,
        dispute_open=True,
        event_created=1,
    )
    assert store.wallet(principal)["balance_cents"] == 0
    assert store.wallet(principal)["status"] == "restricted"
    store.funding_reversal(
        top["id"],
        charge_id="ch_one",
        refund_cents=0,
        disputed_cents=40,
        dispute_open=True,
        event_created=2,
    )
    assert store.wallet(principal)["deficit_cents"] == 40
    store.funding_reversal(
        top["id"],
        charge_id="ch_one",
        refund_cents=0,
        disputed_cents=40,
        dispute_open=False,
        event_created=3,
    )
    credit(store, owner, 500)
    assert store.wallet(principal)["status"] == "active"
    assert store.wallet(principal)["available_cents"] == 460
    store.funding_reversal(
        top["id"],
        charge_id="ch_one",
        refund_cents=0,
        disputed_cents=0,
        dispute_open=False,
        event_created=4,
    )
    assert store.wallet(principal)["balance_cents"] == 500


def test_row_ownership_revocation_expiry_and_rate_limit(store, service):
    owner = store.bootstrap("one")["account_id"]
    stranger = store.bootstrap("two")["account_id"]
    top, _ = credit(store, owner)
    principal, credential = grant(store, owner)
    row = store.reserve(principal, "one", purchase(service), service)
    sibling, _ = grant(store, owner)
    for operation in (
        lambda: store.top_up(stranger, top["id"]),
        lambda: store.issue(stranger, principal.agent_id),
        lambda: store.transaction(stranger, row["ledger_transaction_id"]),
        lambda: store.execution(Principal(stranger), row["execution_id"]),
        lambda: store.execution(sibling, row["execution_id"]),
    ):
        with pytest.raises(ProductError) as caught:
            operation()
        assert caught.value.status == 404
    with store.connection() as c:
        c.execute(
            "UPDATE agents SET expires_at=now()-interval '1 second' WHERE agent_id=%s",
            (principal.agent_id,),
        )
    with pytest.raises(ProductError):
        store.authenticate_agent(credential["secret"])
    store.rate_limit("test", 1)
    with pytest.raises(ProductError) as caught:
        store.rate_limit("test", 1)
    assert caught.value.status == 429


def test_worker_lock_excludes_second_process_and_webhook_acceptance_deduplicates(store):
    other = Store(store.dsn, store.schema)
    with store.worker_lock() as first:
        assert first is not None
        with other.worker_lock() as second:
            assert second is None
    with other.worker_lock() as second:
        assert second is not None
    event = {
        "id": "evt_one",
        "type": "checkout.session.completed",
        "data": {"object": {"id": "cs_one"}},
        "created": 1,
    }
    store.accept_event(event)
    store.accept_event(event)
    assert len(store.pending_events()) == 1
    store.event_done("evt_one")
    store.accept_event(event)
    assert store.pending_events() == []


async def test_http_stripe_to_wallet_to_service_success_and_failure(store, service, tmp_path):
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps([service.model_dump()]))
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = (
        private.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    settings = ProductSettings(
        _env_file=None,
        catalog_path=catalog,
        clerk_issuer="https://clerk.example",
        clerk_public_key=public,
        stripe_key="sk_test_testing",
        stripe_webhook_secret="whsec_test",
    )
    sessions = {}

    def stripe_transport(request):
        from urllib.parse import parse_qs

        if request.url.path == "/v1/customers":
            return httpx.Response(200, json={"id": "cus_one"})
        if request.method == "POST":
            data = parse_qs(request.content.decode())
            topid = data["metadata[top_up_id]"][0]
            sessions["cs_one"] = {
                "id": "cs_one",
                "livemode": False,
                "mode": "payment",
                "status": "open",
                "currency": "usd",
                "amount_total": 1000,
                "payment_status": "unpaid",
                "client_reference_id": data["client_reference_id"][0],
                "metadata": {"top_up_id": topid, "account_id": data["metadata[account_id]"][0]},
                "url": "https://checkout.stripe.com/c/pay/test",
                "expires_at": int(time.time()) + 1000,
                "payment_intent": "pi_one",
            }
        return httpx.Response(200, json=sessions["cs_one"])

    stripe = StripeGateway(settings, store, transport=httpx.MockTransport(stripe_transport))
    app = create_app(settings, store=store, stripe=stripe)
    claims = {
        "sub": "user_one",
        "iss": "https://clerk.example",
        "azp": "http://localhost:3000",
        # Hosted acceptance has many sequential network round trips. Keep this
        # synthetic identity valid for the journey; expiry has separate tests.
        "exp": int(time.time()) + 1800,
        "nbf": int(time.time()) - 1,
        "iat": int(time.time()) - 1,
    }
    human = {"Authorization": "Bearer " + jwt.encode(claims, private, algorithm="RS256")}

    class Provider:
        fail = False
        ensure_lock = staticmethod(lambda _: None)

        async def purchase(self, row, lock):
            if self.fail:
                raise TerminalFailure("Provider definitively refused the purchase before signing")
            store.mark_paid(row["execution_id"], {"reference": "0xpaid"})
            store.finish(row["execution_id"], data={"answer": "delivered"})

    provider = Provider()
    worker = Worker(settings, store, stripe, provider)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://api.example"
        ) as client:
            assert (await client.post("/v1/me/bootstrap", headers=human)).status_code == 200
            response = await client.post(
                "/v1/wallet/top-ups",
                headers=human | {"Idempotency-Key": "fund"},
                json={"amount_cents": 1000},
            )
            assert response.status_code == 200
            stranger = {
                "Authorization": "Bearer "
                + jwt.encode(claims | {"sub": "user_two"}, private, algorithm="RS256")
            }
            assert (await client.post("/v1/me/bootstrap", headers=stranger)).status_code == 200
            assert (
                await client.get("/v1/wallet/top-ups/" + response.json()["id"], headers=stranger)
            ).status_code == 404
            assert (await client.get("/v1/wallet", headers=human)).json()["available_cents"] == 0
            sessions["cs_one"].update(status="complete", payment_status="paid")
            event = {
                "id": "evt_one",
                "type": "checkout.session.completed",
                "livemode": False,
                "created": int(time.time()),
                "data": {"object": {"id": "cs_one"}},
            }
            raw = json.dumps(event).encode()
            signature = hmac.new(
                b"whsec_test", str(event["created"]).encode() + b"." + raw, hashlib.sha256
            ).hexdigest()
            for _ in range(2):
                assert (
                    await client.post(
                        "/v1/webhooks/stripe",
                        content=raw,
                        headers={"Stripe-Signature": f"t={event['created']},v1={signature}"},
                    )
                ).status_code == 202
            await worker.tick()
            agent = (
                await client.post(
                    "/v1/agents", headers=human, json={"name": "Research", "spend_limit_cents": 200}
                )
            ).json()
            credential = (
                await client.post(
                    f"/v1/agents/{agent['agent_id']}/credentials", headers=human, json={}
                )
            ).json()
            machine = {"Authorization": "Bearer " + credential["secret"]}
            assert (
                await client.post("/v1/discover", headers=machine, json={"query": "example"})
            ).json()["providers"][0]["queries"][0]["affordable"] is True
            first = await client.post(
                "/v1/execute", headers=machine | {"Idempotency-Key": "buy"}, json=purchase(service)
            )
            assert first.status_code == 202
            execution_path = "/v1/executions/" + first.json()["execution_id"]
            assert (await client.get(execution_path, headers=stranger)).status_code == 404
            assert (await client.get(execution_path, headers=human)).status_code == 200
            sibling = (
                await client.post(
                    "/v1/agents", headers=human, json={"name": "Sibling", "spend_limit_cents": 200}
                )
            ).json()
            sibling_credential = (
                await client.post(
                    f"/v1/agents/{sibling['agent_id']}/credentials", headers=human, json={}
                )
            ).json()
            sibling_header = {"Authorization": "Bearer " + sibling_credential["secret"]}
            assert (await client.get(execution_path, headers=sibling_header)).status_code == 404
            assert (await client.get("/v1/wallet", headers=machine)).json()["reserved_cents"] == 40
            await worker.tick()
            replay = await client.post(
                "/v1/execute", headers=machine | {"Idempotency-Key": "buy"}, json=purchase(service)
            )
            assert replay.status_code == 200 and replay.json()["data"] == {"answer": "delivered"}
            assert (await client.get("/v1/wallet", headers=machine)).json()[
                "available_cents"
            ] == 960
            provider.fail = True
            failed = (
                await client.post(
                    "/v1/execute",
                    headers=machine | {"Idempotency-Key": "failure"},
                    json=purchase(service),
                )
            ).json()
            await worker.tick()
            outcome = (
                await client.get(f"/v1/executions/{failed['execution_id']}", headers=machine)
            ).json()
            assert outcome["status"] == "refunded" and outcome["refunded_cents"] == 40
            final = (await client.get("/v1/wallet", headers=machine)).json()
            assert final["available_cents"] == 960 and final["agent"]["remaining_cents"] == 160
            history = (await client.get("/v1/transactions", headers=human)).json()["items"]
            assert sorted(item["type"] for item in history) == [
                "deposit",
                "purchase",
                "purchase",
                "refund",
            ]
    finally:
        await stripe.close()


def catalog_query(endpoint_id, name, description, price_cents, *, keywords=None, mode="test"):
    return {
        "endpoint_id": endpoint_id,
        "name": name,
        "description": description,
        "keywords": keywords or [],
        "url": f"https://provider.example/{endpoint_id}",
        "recipient": "0x" + "12" * 20,
        "price_cents": price_cents,
        "input_schema": {"type": "object"},
        "output_schema": {
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "additionalProperties": False,
        },
        "enabled": True,
        "mode": mode,
        "supports_idempotency": True,
    }


class Closable:
    async def close(self):
        return None


def test_catalog_sync_replaces_rows_without_touching_purchases(store, service, tmp_path):
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps([service.model_dump()]))
    settings = ProductSettings(_env_file=None, catalog_path=catalog)
    store.sync_catalog(settings.catalog())
    assert store.catalog_service(service.endpoint_id).model_dump() == service.model_dump()
    with store.connection() as connection:
        provider_id = connection.execute(
            "SELECT provider_id FROM queries WHERE endpoint_id=%s", (service.endpoint_id,)
        ).fetchone()["provider_id"]
    assert provider_id == service.endpoint_id

    owner = store.bootstrap("subject")["account_id"]
    credit(store, owner)
    principal, _ = grant(store, owner)
    execution = store.reserve(principal, "keep", purchase(service), service)
    other = service.model_copy(update={"endpoint_id": "other-service", "name": "Other"})
    catalog.write_text(json.dumps([other.model_dump()]))
    store.sync_catalog(ProductSettings(_env_file=None, catalog_path=catalog).catalog())
    assert store.catalog_service(service.endpoint_id) is None
    assert store.catalog_service("other-service").name == "Other"
    saved = store.execution_internal(execution["execution_id"])
    assert saved["endpoint_id"] == service.endpoint_id
    assert saved["service"]["price_cents"] == service.price_cents

    store.sync_catalog(None)
    assert store.service_count("test") == 1
    catalog.write_text("[]")
    store.sync_catalog(ProductSettings(_env_file=None, catalog_path=catalog).catalog())
    assert store.service_count("test") == 0
    assert store.execution_internal(execution["execution_id"])["endpoint_id"] == service.endpoint_id


async def test_discover_groups_queries_under_providers(store, tmp_path):
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps(
            [
                {
                    "provider_id": "acme",
                    "name": "Acme Freight",
                    "description": "Logistics coverage for shippers",
                    "queries": [
                        catalog_query("lane-cost", "Lane cost", "Estimates a lane", 80),
                        catalog_query(
                            "fleet-size", "Fleet size", "Counts trucks", 25, keywords=["zephyr"]
                        ),
                        catalog_query("hidden-lane", "Hidden lane", "Logistics secret", 10),
                    ],
                },
                {
                    "provider_id": "beta-data",
                    "name": "Beta Data",
                    "description": "Secondary source",
                    "queries": [
                        catalog_query("zeta-report", "Zeta report", "Monthly totals", 40),
                        catalog_query("alpha-report", "Alpha report", "Daily totals", 40),
                    ],
                },
                {
                    "provider_id": "harbor",
                    "name": "Harbor Watch",
                    "description": "Port incident history",
                    "queries": [
                        catalog_query("storm-risk", "Storm risk", "Weather delays at ports", 60),
                        catalog_query("live-only", "Live only", "Mainnet coverage", 2, mode="live"),
                    ],
                },
            ]
        )
    )
    app = create_app(
        ProductSettings(_env_file=None, catalog_path=catalog),
        store=store,
        verifier=Closable(),
        stripe=Closable(),
    )
    store.disable_service("hidden-lane", "operator hold")
    owner = store.bootstrap("subject")["account_id"]
    credit(store, owner, 30)
    _, credential = grant(store, owner, 200)
    headers = {"Authorization": "Bearer " + credential["secret"]}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://api.example"
    ) as client:

        async def discover(query, budget=None):
            body = {"query": query}
            if budget is not None:
                body["budget_cents"] = budget
            response = await client.post("/v1/discover", headers=headers, json=body)
            assert response.status_code == 200, response.text
            return response.json()

        listed = await discover("")
        assert [item["provider_id"] for item in listed["providers"]] == [
            "acme",
            "beta-data",
            "harbor",
        ]
        assert [query["endpoint_id"] for query in listed["providers"][0]["queries"]] == [
            "fleet-size",
            "lane-cost",
        ]
        assert [query["endpoint_id"] for query in listed["providers"][1]["queries"]] == [
            "alpha-report",
            "zeta-report",
        ]
        flags = {
            query["endpoint_id"]: query["affordable"]
            for provider in listed["providers"]
            for query in provider["queries"]
        }
        assert flags["fleet-size"] is True
        assert flags["lane-cost"] is False
        assert flags["storm-risk"] is False
        assert "hidden-lane" not in flags and "live-only" not in flags
        sample = listed["providers"][0]["queries"][0]
        assert sample["output_schema"]["type"] == "object"
        assert "url" not in sample and "recipient" not in sample and "keywords" not in sample

        logistics = await discover("logistics")
        assert [item["provider_id"] for item in logistics["providers"]] == ["acme"]
        assert [query["endpoint_id"] for query in logistics["providers"][0]["queries"]] == [
            "fleet-size",
            "lane-cost",
        ]

        daily = await discover("daily")
        assert [item["provider_id"] for item in daily["providers"]] == ["beta-data"]
        assert [query["endpoint_id"] for query in daily["providers"][0]["queries"]] == [
            "alpha-report"
        ]

        assert (await discover("zephyr"))["providers"] == []
        tight = await discover("fleet", 20)
        assert tight["providers"][0]["queries"][0]["endpoint_id"] == "fleet-size"
        assert tight["providers"][0]["queries"][0]["affordable"] is False


def test_test_credits_cannot_be_reused_in_live_mode_or_another_treasury(store):
    settings = ProductSettings(_env_file=None)
    store.bind_runtime(settings)
    store.bind_runtime(settings)
    store.bind_treasury("0x" + "12" * 20)
    store.bind_treasury("0x" + "12" * 20)
    with pytest.raises(ValueError, match="another payment mode"):
        store.bind_runtime(settings.model_copy(update={"mode": "live", "chain_id": 4217}))
    with pytest.raises(ValueError, match="another treasury"):
        store.bind_treasury("0x" + "34" * 20)
