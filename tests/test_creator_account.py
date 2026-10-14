"""Creator research → explicit publication → real PostgreSQL account purchase."""

import json
from argparse import Namespace
from unittest.mock import Mock

import httpx
import pytest

from openmcp.product.api_call import ApiKeyCaller
from openmcp.product.app import create_app as account_app
from openmcp.product.cli import run_with_store
from openmcp.product.config import ProductSettings
from openmcp.product.worker import Worker
from openmcp.providers import publish
from openmcp_creator.adapter import provider_definition
from openmcp_creator.app import create_app as creator_app
from tests import test_creator as creator_tests
from tests import test_product_api_call as api_tests

postgres_url = api_tests.postgres_url
store = api_tests.store
settings = creator_tests.settings


@pytest.mark.parametrize("fail_source", [False, True])
async def test_creator_account_purchase_and_replay(store, settings, monkeypatch, fail_source):
    jobs, config, _, source, runtime, _, research = creator_tests.components(settings)
    job = jobs.submit(creator_tests.creation())
    with pytest.raises(ValueError, match="Validate"):
        provider_definition(job, config, "test")
    await research.run_once()
    definition = provider_definition(jobs.get(job["id"]), config, "test")
    publish(store, [definition], "test")
    assert store.service_count("test") == 0
    store.set_service_enabled(job["id"], True, "test")
    # Replaying migrations must preserve both newly supported adapters and state.
    store.migrate()
    store.database.check_schema_version()
    source.calls.clear()
    if fail_source:

        async def fail(url, **kwargs):
            source.calls.append((url, kwargs))
            raise httpx.ReadTimeout("Outcome unknown")

        source.request = fail
    token = settings.api_token.get_secret_value()
    monkeypatch.setenv("OPENMCP_CREATOR_API_TOKEN", token)
    host = creator_app(settings, start_worker=False, store=jobs, runtime=runtime)
    product = ProductSettings(_env_file=None)
    caller = ApiKeyCaller(product, store, transport=httpx.ASGITransport(app=host))
    worker = Worker(product, store, Mock(), api_caller=caller)
    api = account_app(
        product, store=store, verifier=api_tests.Closable(), stripe=api_tests.Closable()
    )
    owner = store.bootstrap("creator-owner")["account_id"]
    api_tests.credit(store, owner)
    _, credential = api_tests.grant(store, owner)
    auth = {"Authorization": "Bearer " + credential["secret"]}
    request = {"endpoint_id": job["id"], "payload": {"city": "Boston"}, "max_price_cents": 40}
    try:
        async with host.router.lifespan_context(host):
            await worker.tick()
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=api), base_url="http://api.test"
            ) as client:
                found = await client.post("/v1/discover", headers=auth, json={"query": "weather"})
                assert found.status_code == 200 and job["id"] in found.text
                assert token not in found.text and "provider_price_cents" not in found.text
                headers = auth | {"Idempotency-Key": "creator-once"}
                first = await client.post("/v1/execute", headers=headers, json=request)
                assert first.status_code == 202 and store.account(owner)["reserved_cents"] == 40
                await worker.tick()
                replay = await client.post("/v1/execute", headers=headers, json=request)
                assert replay.json()["execution_id"] == first.json()["execution_id"]
                assert replay.json()["status"] == ("needs_review" if fail_source else "completed")
                await worker.tick()
                assert len(source.calls) == 1
                row = store.execution_internal(first.json()["execution_id"])
                assert token not in json.dumps(row, default=str)
                if fail_source:
                    assert store.account(owner)["reserved_cents"] == 40
                    assert store.account(owner)["spent_cents"] == 0
                    # An operator can return account credits without an MPP signer.
                    await run_with_store(
                        Namespace(
                            command="reconcile",
                            execution_id=row["execution_id"],
                            refund=True,
                            reason="Source outcome reviewed",
                        ),
                        product,
                        store,
                    )
                    assert store.account(owner)["reserved_cents"] == 0
                    assert len(source.calls) == 1
                else:
                    assert replay.json()["data"]["data"] == {"temperature": 23}
                    assert (
                        row["provider_cost_microusd"] is None and row["provider_cost_cents"] is None
                    )
                    assert store.account(owner)["spent_cents"] == 40
                    assert store.account(owner)["reserved_cents"] == 0
    finally:
        await caller.close()
