import json
import sqlite3
from pathlib import Path

import httpx
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.memory import create_connected_server_and_client_session

from openmcp.account_client import AccountClient, AccountSettings, configure_account
from openmcp.account_mcp import create_account_mcp
from openmcp.client_setup.installer import apply_plan, plan_install, server_entry, skill_text
from openmcp.models import OpenMCPError

TOKEN = "private-test-agent-credential"
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def account_settings(tmp_path):
    settings = AccountSettings(_env_file=None, state=tmp_path / "client")
    configure_account(settings, "http://127.0.0.1:8000", TOKEN)
    return settings


def completed():
    return {
        "execution_id": "exe_1",
        "status": "completed",
        "price_cents": 40,
        "charged_cents": 40,
        "refunded_cents": 0,
        "data": {"answer": "Evidence"},
    }


async def test_account_calls_use_credential_without_loading_a_crypto_wallet(account_settings):
    requests = []

    def handle(request):
        requests.append(request)
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        if request.url.path == "/v1/wallet":
            return httpx.Response(200, json={"available_cents": 1000, "agent": {}})
        if request.url.path == "/v1/discover":
            assert json.loads(request.content) == {"query": "research", "budget_cents": 100}
            return httpx.Response(200, json={"endpoints": []})
        assert request.headers["Idempotency-Key"] == "purchase-0001"
        assert json.loads(request.content) == {
            "endpoint_id": "service",
            "payload": {"q": "topic"},
            "max_price_cents": 40,
        }
        return httpx.Response(200, json=completed())

    client = AccountClient(account_settings, transport=httpx.MockTransport(handle))
    try:
        assert (await client.balance())["available_cents"] == 1000
        await client.discover("research", 100)
        assert (await client.execute("service", {"q": "topic"}, 40, "purchase-0001"))["data"]
    finally:
        await client.close()
    assert len(requests) == 3
    assert not (account_settings.state.parent / "wallets").exists()
    assert not (account_settings.state.parent / "agent-payments.sqlite3").exists()


async def test_invalid_price_ceiling_never_submits_or_journals_purchase(account_settings):
    def no_request(request):
        pytest.fail("Invalid purchase must not reach the gateway")

    client = AccountClient(account_settings, transport=httpx.MockTransport(no_request))
    try:
        for amount in (0, -1, True, 1.5, 1_000_001):
            with pytest.raises(OpenMCPError, match="price ceiling"):
                await client.execute("service", {}, amount, "purchase-0001")
        with client.journal.connect() as db:
            assert db.execute("SELECT count(*) FROM requests").fetchone()[0] == 0
    finally:
        await client.close()


async def test_lost_reply_restart_and_retry_reuses_identical_purchase(account_settings):
    purchases = {}
    attempts = []

    def handle(request):
        key = request.headers["Idempotency-Key"]
        attempts.append((key, request.content))
        if key not in purchases:
            purchases[key] = completed()
            raise httpx.ReadError("lost response", request=request)
        return httpx.Response(200, json=purchases[key])

    client = AccountClient(account_settings, transport=httpx.MockTransport(handle))
    with pytest.raises(httpx.ReadError):
        await client.execute("service", {}, 40, "purchase-0001")
    await client.close()
    restarted = AccountClient(account_settings, transport=httpx.MockTransport(handle))
    try:
        result = await restarted.execute("service", {}, 40, "purchase-0001")
        assert result["execution_id"] == "exe_1"
        assert len(purchases) == 1 and attempts[0] == attempts[1]
        with pytest.raises(OpenMCPError, match="different purchase"):
            await restarted.execute("service", {"q": "changed"}, 40, "purchase-0001")
        assert len(attempts) == 2
    finally:
        await restarted.close()


async def test_status_key_survives_restart_and_never_follows_remote_status_url(account_settings):
    paths = []

    def handle(request):
        paths.append((request.method, request.url.path))
        if request.method == "POST":
            return httpx.Response(
                202,
                json={
                    "execution_id": "exe_1",
                    "status": "payment_pending",
                    "status_url": "https://attacker.example/steal-token",
                },
            )
        return httpx.Response(200, json={**completed(), "status": "refunded"})

    client = AccountClient(account_settings, transport=httpx.MockTransport(handle))
    await client.execute("service", {}, 40, "purchase-0001")
    await client.close()
    restarted = AccountClient(account_settings, transport=httpx.MockTransport(handle))
    try:
        result = await restarted.execution_status(idempotency_key="purchase-0001")
        assert result["status"] == "refunded"
        unknown = await restarted.execution_status(idempotency_key="purchase-unknown")
        assert unknown["status"] == "submission_unknown"
        assert paths == [("POST", "/v1/execute"), ("GET", "/v1/executions/exe_1")]
    finally:
        await restarted.close()


@pytest.mark.parametrize(
    "origin",
    [
        "http://external.example",
        "https://user:secret@example.com",
        "https://api.example/v1",
        "https://api.example?token=secret",
        "https://api.example#fragment",
        "file:///tmp/api",
    ],
)
def test_configure_rejects_unsafe_api_origins_before_writing(tmp_path, origin):
    settings = AccountSettings(_env_file=None, state=tmp_path / "client")
    with pytest.raises(ValueError):
        configure_account(settings, origin, TOKEN)
    assert not settings.state.exists()


async def test_credential_files_and_journal_are_private_and_journal_has_no_token(account_settings):
    client = AccountClient(account_settings)
    token_file = account_settings.state / "agent-token"
    assert token_file.stat().st_mode & 0o777 == 0o600
    assert account_settings.state.stat().st_mode & 0o777 == 0o700
    assert client.journal.path.stat().st_mode & 0o777 == 0o600
    client.journal.prepare("purchase-0001", {"endpoint_id": "service"})
    with sqlite3.connect(client.journal.path) as db:
        rows = repr(db.execute("SELECT * FROM requests").fetchall())
    assert TOKEN not in rows
    assert TOKEN not in (account_settings.state / "connection.json").read_text()
    await client.close()


def test_interrupted_connection_change_cannot_send_new_credential_to_old_origin(account_settings):
    (account_settings.state / "agent-token").write_text("different-private-agent-credential")
    with pytest.raises(ValueError, match="interrupted"):
        AccountClient(account_settings)


def test_refuses_world_readable_or_symlink_credential(account_settings, tmp_path):
    path = account_settings.state / "agent-token"
    path.chmod(0o644)
    with pytest.raises(ValueError, match="private"):
        AccountClient(account_settings)
    path.unlink()
    unrelated = tmp_path / "unrelated"
    unrelated.write_text(TOKEN)
    path.symlink_to(unrelated)
    with pytest.raises(OSError):
        AccountClient(account_settings)


async def test_redirect_does_not_forward_agent_authorization(account_settings):
    urls = []

    def handle(request):
        urls.append(str(request.url))
        return httpx.Response(307, headers={"Location": "https://attacker.example"})

    client = AccountClient(account_settings, transport=httpx.MockTransport(handle))
    try:
        with pytest.raises(OpenMCPError, match="Invalid gateway"):
            await client.balance()
        assert urls == ["http://127.0.0.1:8000/v1/wallet"]
    finally:
        await client.close()


async def test_account_mcp_protocol_reports_four_tools_and_no_demo_payment_hop(account_settings):
    def handle(request):
        if request.url.path == "/v1/execute":
            return httpx.Response(200, json=completed())
        return httpx.Response(200, json={"available_cents": 1000, "agent": {}})

    client = AccountClient(account_settings, transport=httpx.MockTransport(handle))
    async with create_connected_server_and_client_session(
        create_account_mcp(client=client)
    ) as session:
        tools = (await session.list_tools()).tools
        assert {tool.name for tool in tools} == {
            "balance",
            "discover",
            "execute",
            "execution_status",
        }
        execute = next(tool for tool in tools if tool.name == "execute")
        assert "session_id" not in execute.inputSchema["properties"]
        assert "budget_cents" not in execute.inputSchema["properties"]
        result = await session.call_tool(
            "execute",
            {
                "endpoint_id": "service",
                "payload": {},
                "max_price_cents": 40,
                "idempotency_key": "purchase-0001",
            },
        )
        assert not result.isError
        assert result.structuredContent["charged_cents"] == 40


def test_account_installer_uses_account_mode_and_correct_skill_without_secrets(tmp_path):
    changes = plan_install("all", "project", tmp_path, ROOT, mode="account", environ={})
    apply_plan(changes)
    document = json.loads((tmp_path / ".mcp.json").read_text())
    args = document["mcpServers"]["openmcp"]["args"]
    assert args[args.index("--mode") + 1] == "account"
    text = (tmp_path / ".agents/skills/openmcp/SKILL.md").read_text()
    assert text == skill_text("account")
    assert "execution_status" in text and "prepaid" in text
    assert all(TOKEN not in change.after for change in changes)


async def test_account_stdio_launch_works_without_demo_wallets(tmp_path):
    runtime = tmp_path / "account-runtime"
    runtime.mkdir()
    configure_account(
        AccountSettings(_env_file=None, state=runtime / ".openmcp/account-client"),
        "http://127.0.0.1:8000",
        TOKEN,
    )
    entry = server_entry(runtime, mode="account")
    params = StdioServerParameters(command=entry["command"], args=entry["args"], cwd=str(tmp_path))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            initialized = await session.initialize()
            assert "prepaid USD credits" in initialized.instructions
            assert {tool.name for tool in (await session.list_tools()).tools} == {
                "balance",
                "discover",
                "execute",
                "execution_status",
            }
    assert not (runtime / ".openmcp/wallets").exists()
