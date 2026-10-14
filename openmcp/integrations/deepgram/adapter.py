"""Account-worker transport for this provider; protocol rules live alongside it."""

import asyncio
import os

from ..transport import Request
from . import protocol
from .audio import load_audio


def validate(service):
    if service.settlement != "api_key":
        raise ValueError("This adapter requires API-key settlement")
    protocol.validate_target(service.endpoint_id, service.url, service.mode)


async def prepare(service, payload, key, http, timeout):
    hosts = {
        h.strip().lower()
        for h in os.environ.get("DEEPGRAM_AUDIO_HOSTS", "static.deepgram.com").split(",")
        if h.strip()
    }
    params, authorization = protocol.prepare(
        service.endpoint_id, service.url, service.mode, payload, key, hosts
    )
    async with asyncio.timeout(min(timeout, 30)):
        audio, duration = await load_audio(http, payload["audio_url"], hosts)
    return Request(
        service.url,
        content=audio,
        params=params,
        headers={"Authorization": authorization, "Content-Type": "audio/wav"},
        context=duration,
    )


def parse(service, payload, response, data, context):
    result = protocol.parse(service.endpoint_id, data, context)
    return result
