"""Paid replacement defaults and explicit plan overrides; no live vendor calls."""

from unittest.mock import Mock

import httpx
import pytest

from openmcp.integrations.firecrawl.protocol import DEFAULT_CREDIT_COST_MICROUSD as FIRECRAWL_RATE
from openmcp.integrations.tavily.protocol import DEFAULT_CREDIT_COST_MICROUSD as TAVILY_RATE
from openmcp.product.api_call import ApiKeyCaller
from openmcp.product.config import ProductSettings
from tests import test_firecrawl, test_tavily


@pytest.mark.parametrize("provider,rate", [("tavily", TAVILY_RATE), ("firecrawl", FIRECRAWL_RATE)])
@pytest.mark.parametrize("override", [None, 0, 1234])
async def test_worker_uses_paid_default_or_explicit_plan_override(
    monkeypatch, provider, rate, override
):
    assert rate == (8000 if provider == "tavily" else 5000)
    variable = provider.upper() + "_CREDIT_COST_MICROUSD"
    monkeypatch.delenv(variable, raising=False)
    if override is not None:
        monkeypatch.setenv(variable, str(override))
    secret_ref = provider.upper() + "_API_KEY"
    monkeypatch.setenv(secret_ref, "private-mocked-key")
    if provider == "tavily":
        selected = test_tavily.service()
        payload, body = test_tavily.sample(test_tavily.SEARCH)
    else:
        selected = test_firecrawl.service(test_firecrawl.SCRAPE)
        payload, body = test_firecrawl.sample(test_firecrawl.SCRAPE)
    fake = Mock()
    fake.provider_secret_ref.return_value = secret_ref
    caller = ApiKeyCaller(
        ProductSettings(_env_file=None),
        fake,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body)),
    )
    try:
        await caller.purchase(
            {
                "execution_id": "rate-test",
                "payment_status": "unsigned",
                "service": selected.model_dump(),
                "payload": payload,
            }
        )
        fake.mark_paid.assert_called_once()
        assert fake.mark_paid.call_args.kwargs["cost_microusd"] == (
            rate if override is None else override
        )
    finally:
        await caller.close()
