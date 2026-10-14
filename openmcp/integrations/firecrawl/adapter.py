"""Account-worker transport for this provider; protocol rules live alongside it."""

import os

from ..transport import Request
from . import protocol


def validate(service):
    if service.settlement != "api_key":
        raise ValueError("This adapter requires API-key settlement")
    protocol.validate_target(service.endpoint_id, service.url, service.mode)


async def prepare(service, payload, key, http, timeout):
    rate = protocol.credit_rate(
        os.environ.get("FIRECRAWL_CREDIT_COST_MICROUSD", str(protocol.DEFAULT_CREDIT_COST_MICROUSD))
    )
    body, authorization = protocol.prepare(
        service.endpoint_id, service.url, service.mode, payload, key
    )
    return Request(
        service.url,
        json=body,
        headers={"Authorization": authorization},
        context=rate,
        require_success=True,
    )


def parse(service, payload, response, data, context):
    result = protocol.parse(service.endpoint_id, payload, data, context)
    return result
