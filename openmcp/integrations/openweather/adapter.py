"""Account-worker transport for this provider; protocol rules live alongside it."""

import os

from ..transport import Request
from . import protocol


def validate(service):
    if service.settlement != "api_key":
        raise ValueError("This adapter requires API-key settlement")
    protocol.validate_target(service.endpoint_id, service.url, service.mode)


async def prepare(service, payload, key, http, timeout):
    cost = protocol.request_cost(os.environ.get("OPENWEATHER_REQUEST_COST_MICROUSD", "0"))
    params, authorization = protocol.prepare(
        service.endpoint_id, service.url, service.mode, payload, key
    )
    params["appid"] = authorization
    return Request(service.url, method="GET", params=params, context=cost)


def parse(service, payload, response, data, context):
    result = protocol.parse(service.endpoint_id, payload, data, context)
    return result
