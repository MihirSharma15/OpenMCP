"""Cross-provider transport regressions: credentials and compressed billing headers."""

import gzip
import json
import logging
from unittest.mock import Mock

import httpx
import pytest

from openmcp.product.api_call import ApiKeyCaller
from openmcp.product.config import ProductSettings
from tests import test_builtwith, test_nansen, test_openweather


@pytest.mark.parametrize(
    "module,identifier,variable,param",
    [
        (test_openweather, test_openweather.CURRENT, "OPENWEATHER_API_KEY", "appid"),
        (test_builtwith, test_builtwith.SUMMARY, "BUILTWITH_API_KEY", "KEY"),
    ],
)
async def test_query_credentials_reach_vendor_but_not_logs(
    monkeypatch, caplog, module, identifier, variable, param
):
    secret = "private-query-key-do-not-log"
    monkeypatch.setenv(variable, secret)
    payload, body = module.sample(identifier)
    fake = Mock()
    fake.provider_secret_ref.return_value = variable

    def handler(request):
        assert request.url.params[param] == secret
        return httpx.Response(200, json=body)

    caller = ApiKeyCaller(
        ProductSettings(_env_file=None), fake, transport=httpx.MockTransport(handler)
    )
    try:
        with caplog.at_level(logging.INFO, logger="httpx"):
            await caller.purchase(
                {
                    "execution_id": "redacted-log-check",
                    "payment_status": "unsigned",
                    "service": module.service(identifier).model_dump(),
                    "payload": payload,
                }
            )
        assert "200 OK" in caplog.text
        assert secret not in caplog.text and f"{param}=" not in caplog.text
        fake.mark_paid.assert_called_once()
    finally:
        await caller.close()


async def test_compressed_response_retains_nansen_credit_headers(monkeypatch):
    monkeypatch.setenv("NANSEN_API_KEY", "mocked-nansen-key")
    monkeypatch.setenv("NANSEN_CREDIT_COST_MICROUSD", "1000")
    payload, body = test_nansen.sample(test_nansen.BALANCES)
    encoded = gzip.compress(json.dumps(body).encode())
    fake = Mock()
    fake.provider_secret_ref.return_value = "NANSEN_API_KEY"
    caller = ApiKeyCaller(
        ProductSettings(_env_file=None),
        fake,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                headers=test_nansen.HEADERS
                | {"Content-Encoding": "gzip", "Content-Length": str(len(encoded))},
                stream=httpx.ByteStream(encoded),
            )
        ),
    )
    try:
        await caller.purchase(
            {
                "execution_id": "compressed-nansen",
                "payment_status": "unsigned",
                "service": test_nansen.service(test_nansen.BALANCES).model_dump(),
                "payload": payload,
            }
        )
        receipt = fake.mark_paid.call_args.args[1]
        assert receipt["credits_used"] == 1
        assert receipt["vendor_reference"] == "vendor-request-123"
        assert fake.mark_paid.call_args.kwargs["cost_microusd"] == 1000
    finally:
        await caller.close()
