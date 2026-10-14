"""Account-worker transport for this provider; protocol rules live alongside it."""

from ..transport import Request
from . import protocol


def validate(service):
    if service.settlement != "api_key":
        raise ValueError("This adapter requires API-key settlement")
    protocol.validate_target(service.endpoint_id, service.url, service.mode)


async def prepare(service, payload, key, http, timeout):
    body, authorization = protocol.prepare(
        service.endpoint_id, service.url, service.mode, payload, key
    )
    return Request(
        service.url,
        json=body,
        headers={"x-api-key": authorization},
        context=None,
        require_success=True,
    )


def parse(service, payload, response, data, context):
    result = protocol.parse(service.endpoint_id, payload, data)
    return result
