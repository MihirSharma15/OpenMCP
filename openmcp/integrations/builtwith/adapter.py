"""Account-worker transport for this provider; protocol rules live alongside it."""

from ..transport import Request
from . import protocol

MIN_INTERVAL = 1.0


def validate(service):
    if service.settlement != "api_key":
        raise ValueError("This adapter requires API-key settlement")
    protocol.validate_target(service.endpoint_id, service.url, service.mode)


async def prepare(service, payload, key, http, timeout):
    params = protocol.prepare(service.endpoint_id, service.url, service.mode, payload, key)
    params["KEY"] = key
    return Request(service.url, method="GET", params=params)


def parse(service, payload, response, data, context):
    result = protocol.parse(service.endpoint_id, payload, data)
    return result
