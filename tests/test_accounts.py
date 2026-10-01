"""Account identity, hashed credentials, and per-account credit access."""

import ast
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from openmcp.adapters.memory import MemoryAccounts, MemoryLedger
from openmcp.app import create_app
from openmcp.domain.accounts import (
    AuthenticationFailed,
    Scope,
    create_account,
    create_agent,
    issue_credential,
    resolve_bearer,
    revoke_credential,
)

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = {"fastapi", "psycopg", "psycopg2", "stripe", "sqlite3"}


@pytest.fixture
async def accounts_api(settings):
    ledger = MemoryLedger()
    accounts = MemoryAccounts()
    app = create_app(settings, ledger=ledger, accounts=accounts)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://localhost",
        ) as client:
            yield {
                "client": client,
                "ledger": ledger,
                "accounts": accounts,
                "settings": settings,
            }


def _demo(settings) -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.api_token.get_secret_value()}"}


def _bearer(secret: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {secret}"}


async def _open_account(client, settings) -> dict:
    created = await client.post("/v1/accounts", headers=_demo(settings))
    assert created.status_code == 200, created.text
    body = created.json()
    assert set(body) == {"account_id", "credential_id", "secret", "scopes"}
    assert body["scopes"] == ["owner:billing"]
    return body


def _sha256(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _stored_state(accounts: MemoryAccounts):
    return accounts.apply(lambda state: (state, state))


async def test_secret_is_returned_once_and_is_not_the_stored_hash(accounts_api):
    client, settings, accounts = (
        accounts_api["client"],
        accounts_api["settings"],
        accounts_api["accounts"],
    )
    first = await _open_account(client, settings)
    second = await _open_account(client, settings)
    secret = first["secret"]

    assert secret != second["secret"]
    assert secret != _sha256(secret)
    record = accounts.credential_by_hash(_sha256(secret))
    assert record is not None
    assert record.token_hash == _sha256(secret)
    assert record.revoked is False
    assert secret not in repr(_stored_state(accounts))
    for value in (
        record.credential_id,
        record.account_id,
        record.agent_id,
        record.token_hash,
        record.expires_at,
        record.revoked,
    ):
        assert secret not in str(value)

    credits = await client.get("/v1/credits", headers=_bearer(secret))
    again = await client.get(f"/v1/accounts/{first['account_id']}", headers=_bearer(secret))
    assert credits.status_code == 200
    assert secret not in credits.text
    assert again.status_code in {404, 405}
    assert secret not in again.text


async def test_revoked_credential_is_401_on_get_credits(accounts_api):
    client, settings, ledger = (
        accounts_api["client"],
        accounts_api["settings"],
        accounts_api["ledger"],
    )
    owner = await _open_account(client, settings)
    owner_headers = _bearer(owner["secret"])
    await client.post(
        "/v1/credits/deposits",
        headers=owner_headers,
        json={"amount_cents": 1000, "charge_id": "ch_revoke", "status": "confirmed"},
    )
    agent = await client.post("/v1/agents", headers=owner_headers)
    assert agent.status_code == 200
    agent_id = agent.json()["agent_id"]
    issued = await client.post(f"/v1/agents/{agent_id}/credentials", headers=owner_headers)
    assert issued.status_code == 200
    secret = issued.json()["secret"]
    agent_headers = _bearer(secret)

    readable = await client.get("/v1/credits", headers=agent_headers)
    revoked = await client.post(
        f"/v1/agents/{agent_id}/credentials/{issued.json()['credential_id']}/revoke",
        headers=owner_headers,
    )
    denied = await client.get("/v1/credits", headers=agent_headers)
    spent = await client.post(
        "/v1/credits/debits",
        headers=agent_headers,
        json={"price_cents": 40, "idempotency_key": "revoked-spend"},
    )
    owner_still = await client.get("/v1/credits", headers=owner_headers)

    assert readable.status_code == 200
    assert readable.json()["available_cents"] == 1000
    assert revoked.status_code == 200
    assert revoked.json()["revoked"] is True
    assert secret not in revoked.text
    assert denied.status_code == 401
    assert denied.json()["error"]["code"] == "unauthorized"
    assert spent.status_code == 401
    assert owner_still.status_code == 200
    assert owner_still.json()["available_cents"] == 1000
    assert ledger.balance_cents(owner["account_id"]) == 1000


async def test_account_a_cannot_see_account_b_balance(accounts_api):
    client, settings, ledger = (
        accounts_api["client"],
        accounts_api["settings"],
        accounts_api["ledger"],
    )
    account_a = await _open_account(client, settings)
    account_b = await _open_account(client, settings)
    headers_a = _bearer(account_a["secret"])
    headers_b = _bearer(account_b["secret"])
    await client.post(
        "/v1/credits/deposits",
        headers=headers_a,
        json={"amount_cents": 100, "charge_id": "ch_a", "status": "confirmed"},
    )
    await client.post(
        "/v1/credits/deposits",
        headers=headers_b,
        json={"amount_cents": 1000, "charge_id": "ch_b", "status": "confirmed"},
    )

    sneaky = dict(headers_a)
    sneaky["X-OpenMCP-Account"] = account_b["account_id"]
    seen = await client.get("/v1/credits", headers=sneaky)
    spent = await client.post(
        "/v1/credits/debits",
        headers=headers_a,
        json={"price_cents": 1000, "idempotency_key": "take-b"},
    )
    balance_b = await client.get("/v1/credits", headers=headers_b)

    assert seen.status_code == 200
    assert seen.json() == {"available_cents": 100, "currency": "usd_credits"}
    assert seen.json()["available_cents"] != 1000
    assert spent.status_code == 200
    assert spent.json()["outcome"] == "insufficient_credits"
    assert spent.json()["available_cents"] == 100
    assert balance_b.json()["available_cents"] == 1000
    assert ledger.balance_cents(account_a["account_id"]) == 100
    assert ledger.balance_cents(account_b["account_id"]) == 1000


async def test_agent_execute_cannot_create_an_agent_or_a_credential(accounts_api):
    client, settings = accounts_api["client"], accounts_api["settings"]
    owner = await _open_account(client, settings)
    owner_headers = _bearer(owner["secret"])
    agent = await client.post("/v1/agents", headers=owner_headers)
    agent_id = agent.json()["agent_id"]
    issued = await client.post(f"/v1/agents/{agent_id}/credentials", headers=owner_headers)
    agent_headers = _bearer(issued.json()["secret"])

    created = await client.post("/v1/agents", headers=agent_headers)
    credential = await client.post(
        f"/v1/agents/{agent_id}/credentials",
        headers=agent_headers,
    )
    revoked = await client.post(
        f"/v1/agents/{agent_id}/credentials/{issued.json()['credential_id']}/revoke",
        headers=agent_headers,
    )

    for response in (created, credential, revoked):
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "forbidden"
        assert response.json()["error"]["retryable"] is False


async def test_agent_execute_can_read_and_debit_but_not_deposit(accounts_api):
    client, settings, ledger = (
        accounts_api["client"],
        accounts_api["settings"],
        accounts_api["ledger"],
    )
    owner = await _open_account(client, settings)
    owner_headers = _bearer(owner["secret"])
    await client.post(
        "/v1/credits/deposits",
        headers=owner_headers,
        json={"amount_cents": 1000, "charge_id": "ch_agent", "status": "confirmed"},
    )
    agent = await client.post("/v1/agents", headers=owner_headers)
    issued = await client.post(
        f"/v1/agents/{agent.json()['agent_id']}/credentials",
        headers=owner_headers,
    )
    agent_headers = _bearer(issued.json()["secret"])

    credits = await client.get("/v1/credits", headers=agent_headers)
    debited = await client.post(
        "/v1/credits/debits",
        headers=agent_headers,
        json={"price_cents": 40, "idempotency_key": "agent-40"},
    )
    deposited = await client.post(
        "/v1/credits/deposits",
        headers=agent_headers,
        json={"amount_cents": 500, "charge_id": "ch_agent_deposit", "status": "confirmed"},
    )

    assert credits.status_code == 200
    assert credits.json()["available_cents"] == 1000
    assert debited.status_code == 200
    assert debited.json()["outcome"] == "debited"
    assert debited.json()["available_cents"] == 960
    assert deposited.status_code == 403
    assert ledger.balance_cents(owner["account_id"]) == 960


async def test_owner_can_create_an_agent_and_an_agent_credential(accounts_api):
    client, settings, accounts = (
        accounts_api["client"],
        accounts_api["settings"],
        accounts_api["accounts"],
    )
    owner = await _open_account(client, settings)
    headers = _bearer(owner["secret"])

    created = await client.post("/v1/agents", headers=headers)
    assert created.status_code == 200
    assert created.json() == {
        "agent_id": created.json()["agent_id"],
        "account_id": owner["account_id"],
    }
    rejected = await client.post(
        "/v1/agents",
        headers=headers,
        json={"account_id": "someone-else"},
    )
    assert rejected.status_code == 422

    credential = await client.post(
        f"/v1/agents/{created.json()['agent_id']}/credentials",
        headers=headers,
    )
    assert credential.status_code == 200
    body = credential.json()
    assert body["account_id"] == owner["account_id"]
    assert body["agent_id"] == created.json()["agent_id"]
    assert body["scopes"] == ["agent:execute"]
    assert body["secret"] != _sha256(body["secret"])
    record = accounts.credential_by_hash(_sha256(body["secret"]))
    assert record is not None
    assert record.agent_id == created.json()["agent_id"]
    assert record.account_id == owner["account_id"]
    assert record.scopes == frozenset({Scope.AGENT_EXECUTE})
    assert body["secret"] not in repr(_stored_state(accounts))

    usable = await client.get("/v1/credits", headers=_bearer(body["secret"]))
    assert usable.status_code == 200


async def test_owner_cannot_manage_another_accounts_agent(accounts_api):
    client, settings = accounts_api["client"], accounts_api["settings"]
    account_a = await _open_account(client, settings)
    account_b = await _open_account(client, settings)
    headers_a = _bearer(account_a["secret"])
    headers_b = _bearer(account_b["secret"])
    agent_b = await client.post("/v1/agents", headers=headers_b)
    agent_id = agent_b.json()["agent_id"]
    credential_b = await client.post(f"/v1/agents/{agent_id}/credentials", headers=headers_b)

    cross_credential = await client.post(f"/v1/agents/{agent_id}/credentials", headers=headers_a)
    cross_revoke = await client.post(
        f"/v1/agents/{agent_id}/credentials/{credential_b.json()['credential_id']}/revoke",
        headers=headers_a,
    )
    still_valid = await client.get("/v1/credits", headers=_bearer(credential_b.json()["secret"]))

    assert cross_credential.status_code == 404
    assert cross_revoke.status_code == 404
    assert still_valid.status_code == 200


async def test_expired_credential_is_401(accounts_api):
    client, settings = accounts_api["client"], accounts_api["settings"]
    owner = await _open_account(client, settings)
    headers = _bearer(owner["secret"])
    agent = await client.post("/v1/agents", headers=headers)
    issued = await client.post(
        f"/v1/agents/{agent.json()['agent_id']}/credentials",
        headers=headers,
        json={"expires_at": "2000-01-01T00:00:00Z"},
    )
    assert issued.status_code == 200
    denied = await client.get("/v1/credits", headers=_bearer(issued.json()["secret"]))
    assert denied.status_code == 401
    assert denied.json()["error"]["code"] == "unauthorized"


async def test_account_bootstrap_uses_the_demo_token(accounts_api):
    client, settings, accounts = (
        accounts_api["client"],
        accounts_api["settings"],
        accounts_api["accounts"],
    )
    missing = await client.post("/v1/accounts")
    owner = await _open_account(client, settings)
    with_account_credential = await client.post("/v1/accounts", headers=_bearer(owner["secret"]))

    assert missing.status_code == 401
    assert missing.json()["error"] == {
        "code": "unauthorized",
        "message": "OpenMCP connection token required.",
        "retryable": False,
    }
    assert with_account_credential.status_code == 401
    assert with_account_credential.json()["error"]["message"] == (
        "OpenMCP connection token required."
    )
    assert owner["secret"] not in repr(_stored_state(accounts))


async def test_account_credential_cannot_call_demo_routes(accounts_api):
    client, settings = accounts_api["client"], accounts_api["settings"]
    owner = await _open_account(client, settings)
    account_headers = _bearer(owner["secret"])

    balance = await client.get("/balance", headers=account_headers)
    execute = await client.post("/execute", headers=account_headers, json={})
    reset = await client.post("/demo/reset", headers=account_headers, json={})
    demo_reset = await client.post("/demo/reset", headers=_demo(settings), json={})

    assert balance.status_code == execute.status_code == reset.status_code == 401
    for response in (balance, execute, reset):
        assert response.json()["error"]["message"] == "OpenMCP connection token required."
    assert demo_reset.status_code == 200


def test_unknown_revoked_and_expired_tokens_fail_in_the_domain():
    store = MemoryAccounts()
    issued = create_account(store)
    now = datetime.now(timezone.utc)
    owner = resolve_bearer(store, issued.secret, now=now)
    assert owner.account_id == issued.account_id
    assert owner.agent_id is None
    assert Scope.OWNER_BILLING in owner.scopes
    assert issued.secret not in repr(store.apply(lambda state: (state, state)))

    agent = create_agent(store, owner)
    expired = issue_credential(
        store,
        owner,
        agent_id=agent.agent_id,
        scopes={Scope.AGENT_EXECUTE},
        expires_at=datetime(2000, 1, 1, tzinfo=timezone.utc),
    )
    with pytest.raises(AuthenticationFailed) as expired_error:
        resolve_bearer(store, expired.secret, now=now)
    assert expired_error.value.reason == "expired"

    with pytest.raises(AuthenticationFailed) as unknown_error:
        resolve_bearer(store, "omcp_not-a-real-token", now=now)
    assert unknown_error.value.reason == "unknown"

    live = issue_credential(
        store,
        owner,
        agent_id=agent.agent_id,
        scopes={Scope.AGENT_EXECUTE},
    )
    revoke_credential(store, owner, live.credential_id, agent_id=agent.agent_id)
    with pytest.raises(AuthenticationFailed) as revoked_error:
        resolve_bearer(store, live.secret, now=now)
    assert revoked_error.value.reason == "revoked"


def test_domain_does_not_import_fastapi_or_psycopg():
    domain = ROOT / "openmcp" / "domain"
    for path in domain.rglob("*.py"):
        modules = _imported_modules(path)
        tops = {module.split(".")[0] for module in modules}
        assert tops.isdisjoint(FORBIDDEN), f"{path} imports {tops & FORBIDDEN}"
        assert all(not module.startswith("openmcp.adapters") for module in modules)


def _imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules
