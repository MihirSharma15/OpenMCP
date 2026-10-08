"""Deepgram transcription and verified audio; automated network calls are mocked."""

import io
import json
import wave
from unittest.mock import Mock

import httpx
import pytest

from openmcp.integrations.deepgram.audio import load_audio, pcm_audio
from openmcp.integrations.deepgram.catalog import (
    ENGLISH,
    MAX_BYTES,
    MULTILINGUAL,
    ORIGIN,
    SERVICES,
    provider,
)
from openmcp.integrations.deepgram.cli import write_catalog
from openmcp.integrations.deepgram.protocol import parse, prepare
from openmcp.product.api_call import ApiKeyCaller
from openmcp.product.app import create_app
from openmcp.product.config import ProductSettings, Provider
from openmcp.product.settlement import TerminalFailure
from openmcp.product.worker import Worker
from tests import test_product_api_call as api_tests

postgres_url = api_tests.postgres_url
store = api_tests.store
SECRET = "deepgram-private-mocked-key"
AUDIO_URL = "https://static.deepgram.com/examples/test.wav"
PAYLOAD = {"audio_url": AUDIO_URL, "diarize": True}


def wav(seconds=1, channels=1, rate=8000):
    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(b"\0\0" * int(seconds * rate) * channels)
    return output.getvalue()


def service(identifier=ENGLISH):
    return next(
        q for q in Provider.model_validate(provider()).queries if q.endpoint_id == identifier
    )


def result():
    return {
        "metadata": {"request_id": "vendor-request-123", "duration": 1, "channels": 1},
        "results": {
            "channels": [
                {
                    "alternatives": [
                        {
                            "transcript": "Hello.",
                            "confidence": 0.99,
                            "words": [
                                {
                                    "word": "hello",
                                    "punctuated_word": "Hello.",
                                    "start": 0.1,
                                    "end": 0.8,
                                    "confidence": 0.99,
                                    "speaker": 0,
                                }
                            ],
                        }
                    ]
                }
            ]
        },
    }


@pytest.mark.parametrize(
    "identifier,language,cost", [(ENGLISH, "en", 72), (MULTILINGUAL, "multi", 87)]
)
def test_fixed_request_options_and_fractional_cost(identifier, language, cost):
    params, auth = prepare(
        identifier, service(identifier).url, "live", PAYLOAD, SECRET, {"static.deepgram.com"}
    )
    assert params["model"] == "nova-3" and params["language"] == language
    assert params["mip_opt_out"] == "true" and params["multichannel"] == "false"
    assert params["diarize"] == "true" and auth == "Token " + SECRET
    data, receipt, amount = parse(identifier, result(), 1)
    assert amount == cost and receipt["request_id"] == "vendor-request-123"
    assert "estimate" in receipt["cost_basis"] and data["words"][0]["speaker"] == 0
    assert SECRET not in json.dumps(data) and ORIGIN not in json.dumps(service(identifier).public())
    assert "provider_price_cents" not in service(identifier).public()


@pytest.mark.parametrize(
    "url",
    [
        "http://static.deepgram.com/a.wav",
        "https://127.0.0.1/a.wav",
        "https://localhost/a.wav",
        "https://static.deepgram.com.evil.example/a.wav",
        "https://evil.example/a.wav",
        "https://user:pass@static.deepgram.com/a.wav",
        "https://static.deepgram.com:8443/a.wav",
        "file:///tmp/a.wav",
        "https://static.deepgram.com/a.wav#fragment",
    ],
)
def test_unapproved_audio_locations(url):
    with pytest.raises(ValueError):
        prepare(ENGLISH, service().url, "test", {"audio_url": url}, SECRET, {"static.deepgram.com"})


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"audio_url": AUDIO_URL, "callback": "https://evil.example"},
        {"audio_url": AUDIO_URL, "model": "whisper"},
        {"audio_url": AUDIO_URL, "diarize": 1},
    ],
)
def test_unknown_options_rejected(payload):
    with pytest.raises(ValueError):
        prepare(ENGLISH, service().url, "test", payload, SECRET, {"static.deepgram.com"})


@pytest.mark.parametrize(
    "audio", [b"mp3", wav(seconds=121), wav(channels=2), wav(rate=4000), wav()[:-10]]
)
def test_invalid_audio(audio):
    with pytest.raises(ValueError):
        pcm_audio(audio)


def test_verified_audio_rebuilt_and_duration_boundary():
    raw = wav(seconds=120)
    sanitized, duration = pcm_audio(raw + b"unverified trailing metadata")
    assert sanitized == raw and duration == 120
    with pytest.raises(ValueError):
        pcm_audio(b"x" * (MAX_BYTES + 1))


@pytest.mark.parametrize(
    "problem",
    ["error", "duration", "channels", "request_id", "results", "words", "confidence", "timing"],
)
def test_unusable_vendor_result(problem):
    body = result()
    if problem == "error":
        body["err_code"] = "BAD"
    elif problem == "duration":
        body["metadata"]["duration"] = 120
    elif problem == "channels":
        body["metadata"]["channels"] = 2
    elif problem == "request_id":
        body["metadata"]["request_id"] = ""
    elif problem == "results":
        body["results"]["channels"] = []
    elif problem == "words":
        body["results"]["channels"][0]["alternatives"][0]["words"] = None
    elif problem == "confidence":
        body["results"]["channels"][0]["alternatives"][0]["confidence"] = float("nan")
    else:
        body["results"]["channels"][0]["alternatives"][0]["words"][0]["end"] = 10
    with pytest.raises(ValueError):
        parse(ENGLISH, body, 1)


def test_silence_is_a_valid_empty_transcript():
    body = result()
    body["results"]["channels"][0]["alternatives"][0].update(transcript="", confidence=0, words=[])
    assert parse(ENGLISH, body, 1)[0]["transcript"] == ""


@pytest.mark.parametrize("status", [302, 404])
async def test_audio_fetch_errors_do_not_follow_redirects(status):
    calls = []

    def handler(request):
        calls.append(request)
        assert "authorization" not in request.headers
        return httpx.Response(status, headers={"Location": "https://evil.example/a.wav"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=False
    ) as client:
        with pytest.raises(ValueError):
            await load_audio(client, AUDIO_URL, {"static.deepgram.com"})
    assert len(calls) == 1


def test_catalog_merge_and_fixed_route(tmp_path):
    from openmcp.integrations.companies_house.catalog import provider as companies_house

    path = tmp_path / "catalog.json"
    path.write_text(json.dumps([companies_house()]))
    write_catalog(path, "test")
    assert [p["provider_id"] for p in json.loads(path.read_text())] == [
        "companies-house",
        "deepgram",
    ]
    bad = provider()
    bad["queries"][0]["url"] = ORIGIN + "/v1/speak"
    with pytest.raises(ValueError):
        Provider.model_validate(bad)


@pytest.mark.parametrize("status", [401, 429, 500])
async def test_vendor_failure_is_not_retried_or_captured(monkeypatch, status):
    monkeypatch.setenv("DEEPGRAM_API_KEY", SECRET)
    monkeypatch.delenv("DEEPGRAM_AUDIO_HOSTS", raising=False)
    fake = Mock()
    fake.provider_secret_ref.return_value = "DEEPGRAM_API_KEY"
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.host == "static.deepgram.com":
            return httpx.Response(200, content=wav())
        return httpx.Response(status, json={"err_code": "failed"})

    caller = ApiKeyCaller(
        ProductSettings(_env_file=None), fake, transport=httpx.MockTransport(handler)
    )
    row = {
        "execution_id": "failure",
        "payment_status": "unsigned",
        "service": service().model_dump(),
        "payload": PAYLOAD,
    }
    try:
        with pytest.raises(TerminalFailure):
            await caller.purchase(row)
        with pytest.raises(TerminalFailure):
            await caller.purchase(row | {"payment_status": "sent"})
        assert len(calls) == 2
        fake.mark_paid.assert_not_called()
    finally:
        await caller.close()


@pytest.mark.parametrize("identifier", SERVICES)
async def test_full_account_flow_and_result_recovery(store, monkeypatch, identifier):
    monkeypatch.setenv("DEEPGRAM_API_KEY", SECRET)
    monkeypatch.delenv("DEEPGRAM_AUDIO_HOSTS", raising=False)
    store.sync_catalog([Provider.model_validate(provider())])
    owner = store.bootstrap("deepgram-owner")["account_id"]
    api_tests.credit(store, owner)
    principal, credential = api_tests.grant(store, owner)
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.host == "static.deepgram.com":
            assert request.method == "GET" and "authorization" not in request.headers
            return httpx.Response(200, content=wav())
        assert request.method == "POST" and request.headers["Authorization"] == "Token " + SECRET
        assert request.headers["Content-Type"] == "audio/wav"
        assert request.content == wav() and request.url.params["mip_opt_out"] == "true"
        assert request.url.params["language"] == SERVICES[identifier]["language"]
        return httpx.Response(200, json=result())

    settings = ProductSettings(_env_file=None)
    caller = ApiKeyCaller(settings, store, transport=httpx.MockTransport(handler))
    worker = Worker(settings, store, Mock(), api_caller=caller)
    app = create_app(
        settings, store=store, verifier=api_tests.Closable(), stripe=api_tests.Closable()
    )
    auth = {"Authorization": "Bearer " + credential["secret"]}
    request = {"endpoint_id": identifier, "payload": PAYLOAD, "max_price_cents": 2}
    try:
        await worker.tick()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://api.test"
        ) as client:
            found = await client.post("/v1/discover", headers=auth, json={"query": "Deepgram"})
            assert found.status_code == 200 and identifier in found.text
            assert SECRET not in found.text and ORIGIN not in found.text
            headers = auth | {"Idempotency-Key": "once"}
            first = await client.post("/v1/execute", headers=headers, json=request)
            assert first.status_code == 202 and store.account(owner)["reserved_cents"] == 2
            await worker.tick()
            replay = await client.post("/v1/execute", headers=headers, json=request)
            assert replay.json()["status"] == "completed"
            assert replay.json()["execution_id"] == first.json()["execution_id"]
            row = store.execution_internal(first.json()["execution_id"])
            assert row["provider_cost_microusd"] in (72, 87)
            assert SECRET not in json.dumps(row, default=str) and "RIFF" not in json.dumps(
                row, default=str
            )
            assert (
                store.account(owner)["spent_cents"] == 2
                and store.account(owner)["reserved_cents"] == 0
            )
            saved = store.reserve(principal, "crash", request, service(identifier))
            data, receipt, cost = parse(identifier, result(), 1)
            store.mark_sent(saved["execution_id"])
            store.mark_paid(saved["execution_id"], receipt, data=data, cost_microusd=cost)
            await worker.tick()
            assert (
                store.execution_internal(saved["execution_id"])["status"] == "completed"
                and len(calls) == 2
            )
        store.migrate()
        assert store.account(owner)["spent_cents"] == 4
    finally:
        await caller.close()


async def test_invalid_audio_releases_reservation_before_vendor_send(store, monkeypatch):
    monkeypatch.setenv("DEEPGRAM_API_KEY", SECRET)
    monkeypatch.delenv("DEEPGRAM_AUDIO_HOSTS", raising=False)
    store.sync_catalog([Provider.model_validate(provider())])
    owner = store.bootstrap("deepgram-invalid-audio")["account_id"]
    api_tests.credit(store, owner)
    principal, _ = api_tests.grant(store, owner)
    row = store.reserve(
        principal,
        "bad-audio",
        {"endpoint_id": ENGLISH, "payload": PAYLOAD, "max_price_cents": 2},
        service(),
    )
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.host == "static.deepgram.com"
        return httpx.Response(200, content=wav(seconds=121))

    settings = ProductSettings(_env_file=None)
    caller = ApiKeyCaller(settings, store, transport=httpx.MockTransport(handler))
    try:
        await Worker(settings, store, Mock(), api_caller=caller).tick()
        assert store.execution_internal(row["execution_id"])["status"] == "refunded"
        assert (
            store.account(owner)["spent_cents"] == 0 and store.account(owner)["reserved_cents"] == 0
        )
        assert len(calls) == 1
    finally:
        await caller.close()
