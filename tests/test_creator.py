import asyncio
import json
import time
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from openmcp.agent import Agent
from openmcp.app import create_app as gateway_app
from openmcp.engine import Engine
from openmcp.models import ExecuteRequest, OpenMCPError
from openmcp.payments import PaidClient
from openmcp_creator.adapter import AdapterRuntime
from openmcp_creator.app import create_app
from openmcp_creator.inference import Inference
from openmcp_creator.models import Adapter, BrowserAction, CreateRequest, Decision
from openmcp_creator.network import PublicHTTP
from openmcp_creator.settings import CreatorSettings
from openmcp_creator.store import CreatorStore
from openmcp_creator.vault import Vault
from openmcp_creator.worker import Worker
from openmcp_provider import create_provider_app
from openmcp_provider.settings import ProviderSettings
from tests.conftest import TestChain as SettlementChain


def creation(**kwargs):
    return CreateRequest(
        url="https://source.example/", price_cents=40, idempotency_key="creator-job-0001", **kwargs
    )


def adapter(**kwargs):
    return Adapter(
        name="Weather data",
        description="Observed weather from source API",
        keywords=["weather"],
        kind="http_json",
        url="https://source.example/weather",
        parameters=[{"name": "city", "description": "City name"}],
        query={"q": "city"},
        sample_input={"city": "Boston"},
        evidence_urls=["https://source.example/"],
        **kwargs,
    )


class FakeBrowser:
    actions = []
    reads = []

    def __init__(self, *args):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def read(self, url, selector="body"):
        self.reads.append(url)
        return {
            "url": url,
            "text": "Weather API docs. GET /weather?q=city",
            "links": [],
            "fields": [],
        }

    async def interact(self, action, origins):
        self.actions.append(action)
        return await self.read(action.url)


class FakeInference:
    def __init__(self, *decisions):
        self.decisions = iter(decisions)
        self.contexts = []

    async def decide(self, context):
        self.contexts.append(context)
        return next(self.decisions)


class FakeNetwork:
    def __init__(self):
        self.calls = []

    async def request(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return httpx.Response(200, json={"temperature": 23}, request=httpx.Request("GET", url))


def components(settings, inference=None):
    store = CreatorStore(settings.creator_database)
    config = CreatorSettings(_env_file=None)
    vault = Vault(settings.database.parent / "creator")
    network = FakeNetwork()
    runtime = AdapterRuntime(settings, config, network, vault, browser_factory=FakeBrowser)
    inference = inference or FakeInference(Decision(action="finish", adapter=adapter()))
    worker = Worker(
        store, settings, config, inference, network, vault, runtime, browser_factory=FakeBrowser
    )
    return store, config, vault, network, runtime, inference, worker


def test_jobs_are_idempotent_and_conflicts_do_not_overwrite(settings):
    store = CreatorStore(settings.creator_database)
    first = store.submit(creation())
    assert store.submit(creation()) == first
    changed = creation().model_copy(update={"price_cents": 50})
    with pytest.raises(OpenMCPError, match="different inputs"):
        store.submit(changed)
    assert len(store.list()) == 1


def test_worker_claims_are_exclusive_and_expired_workers_are_fenced(settings):
    first = CreatorStore(settings.creator_database)
    second = CreatorStore(settings.creator_database)
    first.submit(creation())
    job, lease = first.claim()
    assert second.claim() is None
    with first.connection() as db:
        db.execute("UPDATE creator_jobs SET lease_until=?", (time.time() - 1,))
    recovered, new_lease = second.claim()
    assert recovered["id"] == job["id"] and new_lease != lease
    with pytest.raises(RuntimeError, match="lease"):
        first.save(job, lease)
    with pytest.raises(RuntimeError, match="lease"):
        first.publish(
            job,
            lease,
            components(settings)[4].compile({**job, "adapter": adapter().model_dump()})[1],
        )


def test_ambiguous_signup_is_never_automatically_replayed(settings):
    store = CreatorStore(settings.creator_database)
    store.submit(creation())
    job, lease = store.claim()
    job["action_started"] = True
    job["approved_action"] = {"kind": "click"}
    store.save(job, lease)
    with store.connection() as db:
        db.execute("UPDATE creator_jobs SET lease_until=0")
    assert CreatorStore(settings.creator_database).claim() is None
    saved = store.get(job["id"])
    assert saved["state"] == "needs_input" and saved["approved_action"] is None
    assert "uncertain" in saved["message"]


async def test_worker_builds_and_registers_only_after_sample_and_challenge(settings):
    store, config, vault, network, runtime, inference, worker = components(settings)
    job = store.submit(creation())
    assert await worker.run_once()
    assert store.get(job["id"])["state"] == "ready"
    assert len(store.services()) == 1
    assert network.calls[0][0] == "https://source.example/weather?q=Boston"
    service = settings.database.parent / "creator" / "services" / job["id"]
    assert (service / "catalog.json").exists()
    assert (service / "adapter.json").exists()
    assert not await worker.run_once()


async def test_signup_requires_exact_approval_and_resumes_without_secret_context(settings):
    FakeBrowser.actions = []
    action = BrowserAction(
        kind="fill",
        url="https://source.example/",
        selector="#key",
        secret_name="api-key",
        reason="Sign in",
    )
    inference = FakeInference(
        Decision(action="interact", interaction=action),
        Decision(action="finish", adapter=adapter()),
    )
    store, config, vault, network, runtime, inference, worker = components(settings, inference)
    job = store.submit(creation())
    vault.put(job["id"], "api-key", "extremely-secret-value", "https://source.example")
    await worker.run_once()
    assert store.get(job["id"])["state"] == "needs_input"
    assert not FakeBrowser.actions
    with pytest.raises(OpenMCPError, match="explicitly approve"):
        store.resume(job["id"])
    store.resume(job["id"], approve_action=True)
    await worker.run_once()
    assert len(FakeBrowser.actions) == 1
    assert store.get(job["id"])["state"] == "ready"
    assert "extremely-secret-value" not in json.dumps(inference.contexts)


async def test_missing_credential_pauses_and_resume_uses_vault(settings):
    spec = adapter(credential={"secret_name": "api-key"})
    inference = FakeInference(Decision(action="finish", adapter=spec))
    store, config, vault, network, runtime, inference, worker = components(settings, inference)
    job = store.submit(creation())
    await worker.run_once()
    assert store.get(job["id"])["state"] == "needs_input"
    assert not store.services()
    vault.put(job["id"], "api-key", "secret-data", "https://source.example")
    store.resume(job["id"])
    await worker.run_once()
    assert store.get(job["id"])["state"] == "ready"
    assert network.calls[-1][1]["headers"] == {"Authorization": "Bearer secret-data"}
    assert b"secret-data" not in vault._path(job["id"]).read_bytes()
    with pytest.raises(ValueError, match="scoped"):
        vault.secret(job["id"], "api-key", "https://attacker.example")


async def test_failed_live_sample_never_registers(settings):
    store, config, vault, network, runtime, inference, worker = components(settings)

    async def fail(*args, **kwargs):
        raise httpx.ConnectError("secret-token-must-not-appear")

    network.request = fail
    job = store.submit(creation())
    await worker.run_once()
    assert store.get(job["id"])["state"] == "needs_input"
    assert not store.services()
    assert "secret-token" not in json.dumps(store.get(job["id"]))


async def test_step_limit_bounds_inference(settings):
    inference = FakeInference(Decision(action="browse", url="https://source.example/docs"))
    store, *_, worker = components(settings, inference)
    job = store.submit(creation(max_steps=1))
    await worker.run_once()
    assert store.get(job["id"])["steps"] == 1
    assert store.get(job["id"])["state"] == "needs_input"


async def test_generated_service_works_through_remote_discovery_two_hop_payment_and_replay(
    settings,
):
    store, config, vault, network, runtime, inference, worker = components(settings)
    chain = SettlementChain()
    # Construct gateway and agent before registration to test live catalog refresh.
    engine = Engine(settings, incoming_intent=chain.intent(), chain=chain)
    transport = httpx.ASGITransport(app=gateway_app(settings, engine))
    paid = PaidClient(
        settings,
        "agent",
        transport=transport,
        method=chain.method(settings.addresses()["agent"]),
        chain=chain,
    )
    agent = Agent(settings, paid=paid, transport=transport)
    job = store.submit(creation())
    await worker.run_once()
    saved = store.get(job["id"])
    provider, entry = runtime.compile(saved)
    service = settings.database.parent / "creator" / "services" / job["id"]
    provider_app = create_provider_app(
        [provider],
        ProviderSettings(
            _env_file=None,
            state_dir=service / "payments",
            wallets=settings.wallets,
            catalog=service / "catalog.json",
            base_url=config.base_url,
        ),
        intent_factory=chain.intent,
    )
    await engine.outgoing.close()
    engine.outgoing = PaidClient(
        settings,
        "openmcp",
        transport=httpx.ASGITransport(app=provider_app),
        method=chain.method(settings.addresses()["openmcp"]),
        chain=chain,
    )
    try:
        async with provider_app.router.lifespan_context(provider_app):
            discovery = await agent.discover("weather", 100)
            assert discovery["endpoints"][0]["endpoint_id"] == entry.id
            assert entry.id not in agent.catalog
            request = ExecuteRequest(
                session_id=discovery["session_id"],
                endpoint_id=entry.id,
                payload={"city": "Boston"},
                idempotency_key="creator-purchase-0001",
                max_price_cents=40,
                budget_cents=100,
            )
            first, replay = await asyncio.gather(agent.execute(request), agent.execute(request))
            assert first["data"]["data"] == {"temperature": 23}
            assert first["execution_id"] == replay["execution_id"]
            assert chain.broadcasts == chain.signatures == 2
            assert len(network.calls) == 2  # Sample validation plus one fulfillment.
            assert engine.store.balance()["spent_cents"] == 40
    finally:
        await agent.close()
        await engine.close()


@pytest.mark.parametrize(
    "change",
    [
        {"price_cents": 41},
        {"pay_to": "0x" + "1" * 40},
        {"chain_id": 1},
        {"token_address": "0x" + "1" * 40},
        {"execute_path": "https://attacker.example"},
        {"price_cents": True},
        {"endpoint_id": "wrong"},
    ],
)
async def test_remote_terms_are_checked_before_signing(settings, change):
    terms = {
        "endpoint_id": "created-remote",
        "price_cents": 40,
        "chain_id": 42431,
        "token_address": "0x20c0000000000000000000000000000000000000",
        "pay_to": settings.addresses()["openmcp"],
        "execute_path": "/execute",
        "input_schema": {"type": "object"},
        **change,
    }
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=terms))
    chain = SettlementChain()
    paid = PaidClient(
        settings,
        "agent",
        transport=transport,
        method=chain.method(settings.addresses()["agent"]),
        chain=chain,
    )
    agent = Agent(settings, paid=paid, transport=transport)
    try:
        with pytest.raises(OpenMCPError):
            await agent.execute(
                ExecuteRequest(
                    session_id="test",
                    endpoint_id="created-remote",
                    payload={},
                    idempotency_key="remote-test-0001",
                    max_price_cents=40,
                    budget_cents=40,
                )
            )
        assert chain.signatures == 0
    finally:
        await agent.close()


@pytest.mark.parametrize(
    "address", ["127.0.0.1", "::1", "169.254.169.254", "10.0.0.1", "192.168.1.1", "0.0.0.0"]
)
async def test_public_network_rejects_private_addresses(address):
    async def resolver(host):
        return [address]

    network = PublicHTTP(resolver=resolver)
    try:
        with pytest.raises(ValueError, match="prohibited"):
            await network.address("https://source.example/")
    finally:
        await network.close()


async def test_network_pins_connection_and_rejects_cross_origin_credential_redirect():
    async def resolver(host):
        return ["1.1.1.1"]

    requests = []

    def respond(request):
        requests.append(request)
        assert request.url.host == "1.1.1.1"
        assert request.headers["host"] == "source.example"
        assert request.extensions["sni_hostname"] == b"source.example"
        return httpx.Response(302, headers={"location": "https://attacker.example/"})

    network = PublicHTTP(resolver=resolver, transport=httpx.MockTransport(respond))
    try:
        with pytest.raises(ValueError, match="another origin"):
            await network.request(
                "https://source.example/",
                headers={"Authorization": "secret"},
                allowed_origin="https://source.example",
            )
        assert len(requests) == 1
    finally:
        await network.close()


async def test_inference_contract_uses_configured_model_and_validates_output():
    def respond(request):
        body = json.loads(request.content)
        assert body["model"] == "chosen-model"
        assert body["response_format"] == {"type": "json_object"}
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {"action": "finish", "adapter": adapter().model_dump()}
                            )
                        },
                    }
                ]
            },
        )

    inference = Inference(
        CreatorSettings(_env_file=None, model="chosen-model", inference_api_key="test-key"),
        transport=httpx.MockTransport(respond),
    )
    try:
        decision = await inference.decide({"url": "https://source.example/"})
        assert decision.adapter.name == "Weather data"
    finally:
        await inference.close()


def test_adapter_rejects_code_unknown_query_inputs_and_secret_urls():
    for update in (
        {"code": "print('unsafe')"},
        {"url": "https://user:secret@source.example"},
        {"query": {"q": "unknown"}},
        {"url": "https://source.example/?api_key=secret"},
    ):
        with pytest.raises(ValidationError):
            Adapter.model_validate({**adapter().model_dump(), **update})


async def test_creator_job_api_requires_auth_and_reuses_submission(settings):
    app = create_app(settings, CreatorSettings(_env_file=None), start_worker=False)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            assert (await client.post("/jobs", json=creation().model_dump())).status_code == 401
            headers = {"Authorization": "Bearer " + settings.api_token.get_secret_value()}
            first = await client.post("/jobs", json=creation().model_dump(), headers=headers)
            second = await client.post("/jobs", json=creation().model_dump(), headers=headers)
            assert first.status_code == 202 and first.json() == second.json()
            assert "observations" not in first.json()


@pytest.mark.skipif(
    not Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome").exists(),
    reason="Requires local Chrome",
)
async def test_real_browser_renders_page_and_blocks_unapproved_submission(tmp_path):
    from openmcp_creator.browser import Browser

    async def resolver(host):
        return ["1.1.1.1"]

    calls = []

    def respond(request):
        calls.append(request.method)
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text='<html><body><h1>Live browser</h1><form method="post"><input id="email" name="email"><button>Submit</button></form><script>document.querySelector("h1").textContent="Rendered by JavaScript";fetch("/write",{method:"POST"})</script></body></html>',
        )

    config = CreatorSettings(
        _env_file=None,
        browser_executable=Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    )
    network = PublicHTTP(resolver=resolver, transport=httpx.MockTransport(respond))
    vault = Vault(tmp_path)
    try:
        async with Browser(config, network, vault, "created-" + "a" * 32) as browser:
            observation = await browser.read("https://source.example/")
            assert "Rendered by JavaScript" in observation["text"]
            assert any(field["id"] == "email" for field in observation["fields"])
            assert "POST" not in calls
    finally:
        await network.close()


async def test_ip_pinning_does_not_leak_http_client_cookie_jar():
    async def resolver(host):
        return ["1.1.1.1"]

    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, headers={"set-cookie": "private=secret; Path=/"})

    network = PublicHTTP(resolver=resolver, transport=httpx.MockTransport(respond))
    try:
        await network.request("https://first.example/")
        await network.request("https://second.example/")
        assert requests[1].headers.get("cookie", "") == ""
    finally:
        await network.close()


@pytest.mark.skipif(
    not Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome").exists(),
    reason="Requires local Chrome",
)
async def test_real_browser_restores_approved_form_and_captures_credential(tmp_path):
    from openmcp_creator.browser import Browser

    async def resolver(host):
        return ["1.1.1.1"]

    submitted = []

    def respond(request):
        if request.method == "POST":
            submitted.append(request.content)
            return httpx.Response(
                303,
                headers={
                    "location": "https://source.example/account",
                    "set-cookie": "session=signed-in; Path=/; Secure",
                },
            )
        if request.url.path == "/account":
            assert "session=signed-in" in request.headers.get("cookie", "")
            html = '<html><body><input id="api-key" value="captured-secret"><h1>Account</h1></body></html>'
        else:
            html = '<html><body><form method="post"><input id="email" name="email"><button id="signup">Sign up</button></form></body></html>'
        return httpx.Response(200, headers={"content-type": "text/html"}, text=html)

    config = CreatorSettings(
        _env_file=None,
        browser_executable=Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    )
    network = PublicHTTP(resolver=resolver, transport=httpx.MockTransport(respond))
    vault, job_id = Vault(tmp_path), "created-" + "b" * 32
    vault.put(job_id, "email", "test@example.com", "https://source.example")
    try:
        async with Browser(config, network, vault, job_id) as browser:
            await browser.interact(
                BrowserAction(
                    kind="fill",
                    url="https://source.example/",
                    selector="#email",
                    secret_name="email",
                    reason="Fill approved signup email",
                ),
                {"https://source.example"},
            )
        async with Browser(config, network, vault, job_id) as browser:
            await browser.interact(
                BrowserAction(
                    kind="click",
                    url="https://source.example/",
                    selector="#signup",
                    reason="Submit approved signup",
                ),
                {"https://source.example"},
            )
            await browser.page.wait_for_url("https://source.example/account")
            await browser.interact(
                BrowserAction(
                    kind="capture_secret",
                    url="https://source.example/account",
                    selector="#api-key",
                    secret_name="api-key",
                    reason="Store account API key",
                ),
                {"https://source.example"},
            )
        assert submitted == [b"email=test%40example.com"]
        assert vault.secret(job_id, "api-key", "https://source.example") == "captured-secret"
        assert b"captured-secret" not in vault._path(job_id).read_bytes()
    finally:
        await network.close()
