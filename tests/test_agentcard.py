import asyncio
import hashlib
import hmac
import json
from urllib.parse import parse_qs

import httpx
import pytest
from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool
from pydantic import SecretStr, ValidationError

from openmcp.integrations.agentcard import AgentCardClient, AgentCardError, AgentCardSettings
from openmcp.integrations.agentcard.issuing import IssuedCards
from openmcp.integrations.agentcard.models import IssuedCardRequest
from openmcp.integrations.agentcard.webhooks import verify_webhook


def settings(**kwargs):
    return AgentCardSettings(
        _env_file=None, client_id="test-client", client_secret="org-secret", **kwargs
    )


class AgentCardAPI:
    def __init__(self, *, test_mode=True):
        self.requests = []
        self.test_mode = test_mode
        self.tokens = 0
        self.failure = None

    def __call__(self, request):
        self.requests.append(request)
        path = request.url.path
        if path == "/api/v2/oauth/token":
            assert parse_qs(request.content.decode()) == {
                "grant_type": ["client_credentials"],
                "client_id": ["test-client"],
                "client_secret": ["org-secret"],
            }
            self.tokens += 1
            return httpx.Response(
                200,
                json={
                    "access_token": f"org-token-{self.tokens}",
                    "expires_in": 3600,
                },
            )
        assert request.headers["Authorization"] == f"Bearer org-token-{self.tokens}"
        if path == "/api/v2":
            return httpx.Response(
                200,
                json={
                    "organization_id": "org-test",
                    "test_mode": self.test_mode,
                },
            )
        if self.failure:
            return self.failure(request)
        if path.endswith("/start"):
            return httpx.Response(201, json={"id": "ca-test", "channel": "email"})
        if path.endswith(("/verify", "/refresh")):
            result = {
                "access_token": "user-secret",
                "refresh_token": "refresh-secret",
                "expires_in": 3600,
            }
            if path.endswith("/verify"):
                result["user"] = {"id": "usr-test", "email": "not-retained@example.com"}
            return httpx.Response(200, json=result)
        if path.endswith("/consent"):
            return httpx.Response(200, json={"object": "consent"})
        if path.endswith("/kyc"):
            return httpx.Response(
                200,
                json={
                    "status": "requires_verification",
                    "iframe_url": "https://example.com/kyc",
                },
            )
        raise AssertionError(f"Unexpected path: {path}")


async def test_token_exchange_cached_across_concurrent_calls_and_refreshed_before_expiry():
    api = AgentCardAPI()
    clock = [0]
    async with AgentCardClient(
        settings(), transport=httpx.MockTransport(api), clock=lambda: clock[0]
    ) as client:
        identities = await asyncio.gather(*(client.check_credentials() for _ in range(10)))
        assert all(identity.test_mode for identity in identities)
        assert len(api.requests) == 2
        clock[0] = 3571
        await client.check_credentials()
        assert api.tokens == 2
        assert len(api.requests) == 4


@pytest.mark.parametrize("expected,actual", [(True, False), (False, True)])
async def test_wrong_mode_blocks_onboarding_before_sending_code(expected, actual):
    api = AgentCardAPI(test_mode=actual)
    async with AgentCardClient(
        settings(test_mode=expected), transport=httpx.MockTransport(api)
    ) as client:
        with pytest.raises(AgentCardError, match="mode_mismatch"):
            await client.start_connection(email="user@example.com")
    assert [r.url.path for r in api.requests] == ["/api/v2/oauth/token", "/api/v2"]


async def test_onboarding_and_rotating_connection_tokens_stay_server_side():
    api = AgentCardAPI()
    async with AgentCardClient(settings(), transport=httpx.MockTransport(api)) as client:
        attempt = await client.start_connection(email="user@example.com", external_user_id="usr-1")
        assert attempt.id == "ca-test"
        connection = await client.verify_connection(attempt.id, "111111")
        assert connection.user.id == "usr-test"
        assert "user-secret" not in repr(connection)
        assert "refresh-secret" not in connection.model_dump_json()
        rotated = await client.refresh_connection(connection.refresh_token)
        assert rotated.access_token.get_secret_value() == "user-secret"
        assert json.loads(api.requests[-1].content) == {"refresh_token": "refresh-secret"}
        await client.record_consent(connection.user.id)
        status = await client.verification_status(connection.user.id)
        assert status.status == "requires_verification"
        assert api.requests[-1].url.params["user_id"] == "usr-test"


@pytest.mark.parametrize("contact", [{}, {"email": "a@b.com", "phone": "+15555555555"}])
async def test_invalid_contact_makes_no_network_request(contact):
    api = AgentCardAPI()
    async with AgentCardClient(settings(), transport=httpx.MockTransport(api)) as client:
        with pytest.raises(ValueError):
            await client.start_connection(**contact)
    assert not api.requests


@pytest.mark.parametrize("failure", ["timeout", "server_error", "malformed", "unauthorized"])
async def test_rotating_refresh_is_never_automatically_replayed(failure):
    api = AgentCardAPI()

    def fail(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("sensitive raw response", request=request)
        if failure == "server_error":
            return httpx.Response(
                503,
                json={
                    "error": {
                        "code": "unavailable",
                        "message": "sensitive raw response",
                    }
                },
            )
        if failure == "unauthorized":
            return httpx.Response(401, json={"error": {"code": "unauthorized"}})
        return httpx.Response(200, json={"access_token": "sensitive raw response"})

    api.failure = fail
    async with AgentCardClient(settings(), transport=httpx.MockTransport(api)) as client:
        with pytest.raises(AgentCardError) as error:
            await client.refresh_connection(SecretStr("rotating-secret"))
        assert error.value.outcome_unknown == (failure != "unauthorized")
        assert "sensitive" not in str(error.value)
        assert error.value.__suppress_context__ or error.value.__context__ is None
    assert sum(r.url.path.endswith("/refresh") for r in api.requests) == 1


async def test_api_redirect_never_forwards_secret_to_another_origin():
    requests = []

    def redirect(request):
        requests.append(request)
        return httpx.Response(307, headers={"Location": "https://example.com/steal"})

    async with AgentCardClient(settings(), transport=httpx.MockTransport(redirect)) as client:
        with pytest.raises(AgentCardError) as error:
            await client.check_credentials()
        assert error.value.status == 307
    assert len(requests) == 1
    assert requests[0].url.host == "api.agentcard.sh"


class ToolSession:
    def __init__(self):
        self.calls = []
        self.discovery = []
        self.fail = False
        self.reject = False
        self.extra_required = False

    async def list_tools(self, cursor=None):
        self.discovery.append(cursor)
        if cursor is None:
            return ListToolsResult(tools=[], nextCursor="second-page")
        schema = {
            "type": "object",
            "required": ["source", "amount_cents"],
            "properties": {
                "source": {"const": "issued"},
                "amount_cents": {"type": "integer", "minimum": 100},
                "type": {"enum": ["single_use", "multi_use"]},
                "scope_preset": {"enum": ["ai_labs"]},
            },
            "additionalProperties": False,
        }
        if self.extra_required:
            schema["required"].append("provider_new_requirement")
        return ListToolsResult(tools=[Tool(name="create_card", inputSchema=schema)])

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if self.fail:
            raise TimeoutError("provider credentials must not appear in errors")
        return CallToolResult(
            content=[TextContent(type="text", text="server-internal result")],
            isError=self.reject,
        )


async def test_card_uses_live_schema_and_explicit_issued_source():
    session = ToolSession()
    result = await IssuedCards(session).create(IssuedCardRequest(amount_cents=2500))
    assert not result.isError
    assert session.discovery == [None, "second-page"]
    assert session.calls == [
        (
            "create_card",
            {
                "source": "issued",
                "amount_cents": 2500,
                "type": "single_use",
            },
        )
    ]


@pytest.mark.parametrize("amount", [True, 99, 100.0, "100"])
def test_card_rejects_invalid_amounts(amount):
    with pytest.raises(ValidationError):
        IssuedCardRequest(amount_cents=amount)


async def test_changed_remote_contract_prevents_card_mutation():
    session = ToolSession()
    session.extra_required = True
    with pytest.raises(AgentCardError, match="tool_contract_mismatch"):
        await IssuedCards(session).create(IssuedCardRequest(amount_cents=2500))
    assert not session.calls


@pytest.mark.parametrize("failure", ["timeout", "error_result"])
async def test_ambiguous_card_creation_is_not_retried(failure):
    session = ToolSession()
    session.fail = failure == "timeout"
    session.reject = failure == "error_result"
    with pytest.raises(AgentCardError) as error:
        await IssuedCards(session).create(IssuedCardRequest(amount_cents=2500))
    assert error.value.outcome_unknown
    assert "provider credentials" not in str(error.value)
    assert len(session.calls) == 1


WEBHOOK_SECRET = SecretStr("webhook-secret")


def signed_event(*, timestamp=1000, livemode=False):
    body = json.dumps(
        {
            "id": "evt-1",
            "type": "card.created",
            "created": 990,
            "livemode": livemode,
            "data": {"id": "card-1", "label": "café"},
        },
        ensure_ascii=False,
    ).encode()
    digest = hmac.new(
        WEBHOOK_SECRET.get_secret_value().encode(),
        str(timestamp).encode() + b"." + body,
        hashlib.sha256,
    ).hexdigest()
    return body, f"t={timestamp},v1={digest}"


def test_webhook_verifies_exact_bytes_and_exposes_event_id_for_deduplication():
    body, header = signed_event()
    event = verify_webhook(body, header, WEBHOOK_SECRET, now=1001)
    assert event.id == "evt-1"
    assert event.data["label"] == "café"
    with pytest.raises(AgentCardError, match="invalid_webhook_signature"):
        verify_webhook(body + b" ", header, WEBHOOK_SECRET, now=1001)


@pytest.mark.parametrize("timestamp", [699, 1301])
def test_webhook_rejects_old_and_future_timestamps(timestamp):
    body, header = signed_event(timestamp=timestamp)
    with pytest.raises(AgentCardError, match="expired_webhook_signature"):
        verify_webhook(body, header, WEBHOOK_SECRET, now=1000)


@pytest.mark.parametrize("header", ["", "sha256=legacy", "t=1000,t=1000,v1=a", "t=x,v1=a"])
def test_webhook_rejects_malformed_and_legacy_signatures(header):
    body, _ = signed_event()
    with pytest.raises(AgentCardError, match="invalid_webhook_signature"):
        verify_webhook(body, header, WEBHOOK_SECRET, now=1000)


def test_webhook_rejects_valid_signature_for_wrong_mode():
    body, header = signed_event(livemode=True)
    with pytest.raises(AgentCardError, match="mode_mismatch"):
        verify_webhook(body, header, WEBHOOK_SECRET, now=1000)
