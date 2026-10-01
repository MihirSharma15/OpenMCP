"""HTTP tests for /v1/credits using an injected MemoryLedger."""

import ast
from pathlib import Path

import httpx
import pytest

from openmcp.adapters.memory import MemoryAccounts, MemoryLedger
from openmcp.app import create_app

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = {"fastapi", "psycopg", "stripe"}


@pytest.fixture
async def credit_api(settings):
    ledger = MemoryLedger()
    app = create_app(settings, ledger=ledger)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://localhost",
        ) as client:
            yield {"client": client, "ledger": ledger, "settings": settings}


def demo_headers(settings) -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.api_token.get_secret_value()}"}


async def open_account(client, settings) -> tuple[str, dict[str, str]]:
    created = await client.post("/v1/accounts", headers=demo_headers(settings))
    assert created.status_code == 200, created.text
    body = created.json()
    return body["account_id"], {"Authorization": f"Bearer {body['secret']}"}


async def test_confirmed_deposit_is_readable_as_usd_credits(credit_api):
    client, settings = credit_api["client"], credit_api["settings"]
    _, headers = await open_account(client, settings)

    deposited = await client.post(
        "/v1/credits/deposits",
        headers=headers,
        json={"amount_cents": 1000, "charge_id": "ch_1000", "status": "confirmed"},
    )
    credits = await client.get("/v1/credits", headers=headers)

    assert deposited.status_code == 200
    assert deposited.json() == {
        "available_cents": 1000,
        "amount_cents": 1000,
        "charge_id": "ch_1000",
        "outcome": "posted",
    }
    assert credits.status_code == 200
    assert credits.json() == {"available_cents": 1000, "currency": "usd_credits"}


async def test_debit_of_40_cents_leaves_960(credit_api):
    client, settings, ledger = credit_api["client"], credit_api["settings"], credit_api["ledger"]
    account_id, headers = await open_account(client, settings)
    await client.post(
        "/v1/credits/deposits",
        headers=headers,
        json={"amount_cents": 1000, "charge_id": "ch_1000", "status": "confirmed"},
    )

    debited = await client.post(
        "/v1/credits/debits",
        headers=headers,
        json={"price_cents": 40, "idempotency_key": "query-40"},
    )

    assert debited.status_code == 200
    assert debited.json() == {
        "available_cents": 960,
        "price_cents": 40,
        "idempotency_key": "query-40",
        "outcome": "debited",
    }
    assert ledger.balance_cents(account_id) == 960


async def test_debit_larger_than_balance_is_insufficient_and_leaves_960(credit_api):
    client, settings, ledger = credit_api["client"], credit_api["settings"], credit_api["ledger"]
    account_id, headers = await open_account(client, settings)
    await client.post(
        "/v1/credits/deposits",
        headers=headers,
        json={"amount_cents": 1000, "charge_id": "ch_1000", "status": "confirmed"},
    )
    await client.post(
        "/v1/credits/debits",
        headers=headers,
        json={"price_cents": 40, "idempotency_key": "query-40"},
    )

    refused = await client.post(
        "/v1/credits/debits",
        headers=headers,
        json={"price_cents": 1000, "idempotency_key": "query-over"},
    )

    assert refused.status_code == 200
    assert refused.json() == {
        "available_cents": 960,
        "price_cents": 1000,
        "idempotency_key": "query-over",
        "outcome": "insufficient_credits",
    }
    assert ledger.balance_cents(account_id) == 960


async def test_replaying_a_debit_key_does_not_subtract_again(credit_api):
    client, settings, ledger = credit_api["client"], credit_api["settings"], credit_api["ledger"]
    account_id, headers = await open_account(client, settings)
    await client.post(
        "/v1/credits/deposits",
        headers=headers,
        json={"amount_cents": 1000, "charge_id": "ch_1000", "status": "confirmed"},
    )
    await client.post(
        "/v1/credits/debits",
        headers=headers,
        json={"price_cents": 40, "idempotency_key": "query-40"},
    )

    replayed = await client.post(
        "/v1/credits/debits",
        headers=headers,
        json={"price_cents": 40, "idempotency_key": "query-40"},
    )

    assert replayed.status_code == 200
    assert replayed.json() == {
        "available_cents": 960,
        "price_cents": 40,
        "idempotency_key": "query-40",
        "outcome": "replayed",
    }
    assert ledger.balance_cents(account_id) == 960


async def test_account_id_in_the_body_is_rejected(credit_api):
    client, settings, ledger = credit_api["client"], credit_api["settings"], credit_api["ledger"]
    account_id, headers = await open_account(client, settings)

    response = await client.post(
        "/v1/credits/deposits",
        headers=headers,
        json={
            "amount_cents": 1000,
            "charge_id": "ch_1000",
            "status": "confirmed",
            "account_id": "someone-else",
        },
    )

    assert response.status_code == 422
    assert set(response.json()) == {"error"}
    assert set(response.json()["error"]) == {"code", "message", "retryable"}
    assert response.json()["error"]["retryable"] is False
    assert "Traceback" not in response.text
    assert ledger.balance_cents(account_id) == 0
    assert ledger.balance_cents("someone-else") == 0


async def test_credit_routes_require_an_account_credential(credit_api):
    client, settings = credit_api["client"], credit_api["settings"]
    deposit_body = {"amount_cents": 1000, "charge_id": "ch_1000", "status": "confirmed"}
    debit_body = {"price_cents": 40, "idempotency_key": "query-40"}

    for headers in ({}, demo_headers(settings)):
        balance = await client.get("/v1/credits", headers=headers)
        deposit = await client.post("/v1/credits/deposits", headers=headers, json=deposit_body)
        debit = await client.post("/v1/credits/debits", headers=headers, json=debit_body)
        assert balance.status_code == deposit.status_code == debit.status_code == 401
        assert balance.json()["error"]["code"] == "unauthorized"
        assert deposit.json()["error"]["code"] == "unauthorized"
        assert debit.json()["error"]["code"] == "unauthorized"


@pytest.mark.parametrize("amount", [0, -1, -40, True, False, 1.5, "1000"])
async def test_invalid_amounts_are_422(credit_api, amount):
    client, settings, ledger = credit_api["client"], credit_api["settings"], credit_api["ledger"]
    account_id, headers = await open_account(client, settings)

    deposited = await client.post(
        "/v1/credits/deposits",
        headers=headers,
        json={"amount_cents": amount, "charge_id": "ch_bad", "status": "confirmed"},
    )
    debited = await client.post(
        "/v1/credits/debits",
        headers=headers,
        json={"price_cents": amount, "idempotency_key": "query-bad"},
    )

    for response in (deposited, debited):
        assert response.status_code == 422
        assert response.json() == {
            "error": {
                "code": "invalid_amount",
                "message": "amount must be a positive integer number of cents",
                "retryable": False,
            }
        }
        assert "Traceback" not in response.text
    assert ledger.balance_cents(account_id) == 0


@pytest.mark.parametrize("status", ["pending", "failed", "unknown"])
async def test_unconfirmed_deposit_is_ignored(credit_api, status):
    client, settings, ledger = credit_api["client"], credit_api["settings"], credit_api["ledger"]
    account_id, headers = await open_account(client, settings)

    response = await client.post(
        "/v1/credits/deposits",
        headers=headers,
        json={"amount_cents": 1000, "charge_id": "ch_open", "status": status},
    )

    assert response.status_code == 200
    assert response.json() == {
        "available_cents": 0,
        "amount_cents": 1000,
        "charge_id": "ch_open",
        "outcome": "ignored",
    }
    assert ledger.balance_cents(account_id) == 0


async def test_credits_stay_behind_the_bearer_token(credit_api):
    client = credit_api["client"]

    health = await client.get("/health")
    balance = await client.get("/balance")
    credits = await client.get("/v1/credits", headers={"X-OpenMCP-Account": "acct-1"})

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert balance.status_code == 401
    assert credits.status_code == 401
    assert credits.json()["error"]["code"] == "unauthorized"


async def test_demo_validation_errors_keep_their_shape(credit_api):
    client, settings = credit_api["client"], credit_api["settings"]

    response = await client.post(
        "/demo/reset",
        headers=demo_headers(settings),
        json={"budget_cents": -1},
    )

    assert response.status_code == 422
    assert "detail" in response.json()
    assert "error" not in response.json()


async def test_blank_product_database_url_does_not_open_postgres(settings, monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("postgres should not be opened")

    monkeypatch.setattr("openmcp.adapters.postgres.ledger.migrate", fail)
    monkeypatch.setattr("openmcp.adapters.postgres.ledger.PostgresLedger", fail)
    monkeypatch.setattr("openmcp.adapters.postgres.accounts.migrate", fail)
    monkeypatch.setattr("openmcp.adapters.postgres.accounts.PostgresAccounts", fail)
    for url in ("", "   "):
        configured = settings.model_copy(update={"product_database_url": url})
        app = create_app(configured)
        async with app.router.lifespan_context(app):
            assert isinstance(app.state.ledger, MemoryLedger)
            assert isinstance(app.state.accounts, MemoryAccounts)


async def test_injected_ledger_skips_postgres_even_when_url_is_set(settings, monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("postgres should not be opened")

    monkeypatch.setattr("openmcp.adapters.postgres.ledger.migrate", fail)
    monkeypatch.setattr("openmcp.adapters.postgres.ledger.PostgresLedger", fail)
    monkeypatch.setattr("openmcp.adapters.postgres.accounts.migrate", fail)
    monkeypatch.setattr("openmcp.adapters.postgres.accounts.PostgresAccounts", fail)
    configured = settings.model_copy(
        update={"product_database_url": "postgresql://openmcp:openmcp@localhost:5433/openmcp"}
    )
    ledger = MemoryLedger()
    app = create_app(configured, ledger=ledger)
    async with app.router.lifespan_context(app):
        assert app.state.ledger is ledger
        assert isinstance(app.state.accounts, MemoryAccounts)


async def test_product_database_url_migrates_before_opening_postgres(settings, monkeypatch):
    calls = []

    def migrate_ledger(dsn, *, schema="public"):
        calls.append(("migrate_ledger", dsn, schema))

    def migrate_accounts(dsn, *, schema="public"):
        calls.append(("migrate_accounts", dsn, schema))

    class FakePostgresLedger:
        def __init__(self, dsn, *, schema="public"):
            calls.append(("ledger", dsn, schema))

    class FakePostgresAccounts:
        def __init__(self, dsn, *, schema="public"):
            calls.append(("accounts", dsn, schema))

    monkeypatch.setattr("openmcp.adapters.postgres.ledger.migrate", migrate_ledger)
    monkeypatch.setattr("openmcp.adapters.postgres.ledger.PostgresLedger", FakePostgresLedger)
    monkeypatch.setattr("openmcp.adapters.postgres.accounts.migrate", migrate_accounts)
    monkeypatch.setattr("openmcp.adapters.postgres.accounts.PostgresAccounts", FakePostgresAccounts)
    url = "postgresql://openmcp:openmcp@localhost:5433/openmcp"
    configured = settings.model_copy(update={"product_database_url": url})
    app = create_app(configured)
    async with app.router.lifespan_context(app):
        assert calls == [
            ("migrate_ledger", url, "public"),
            ("migrate_accounts", url, "public"),
            ("ledger", url, "public"),
            ("accounts", url, "public"),
        ]
        assert isinstance(app.state.ledger, FakePostgresLedger)
        assert isinstance(app.state.accounts, FakePostgresAccounts)


def test_domain_does_not_import_fastapi_psycopg_or_stripe():
    domain = ROOT / "openmcp" / "domain"
    for path in domain.rglob("*.py"):
        modules = _imported_modules(path)
        tops = {module.split(".")[0] for module in modules}
        assert tops.isdisjoint(FORBIDDEN), f"{path} imports {tops & FORBIDDEN}"


def _imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules
