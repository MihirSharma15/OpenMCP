import argparse
import asyncio
import json
import os
import secrets
import sys
from pathlib import Path

import httpx
import uvicorn
from dotenv import dotenv_values, set_key

from .agent import Agent
from .config import CHAIN_ID, TOKEN, Settings
from .models import ExecuteRequest, OpenMCPError
from .wallets import Chain, create_wallets


def initialize():
    path = Path(".env")
    if not path.exists():
        path.touch(mode=0o600)
    existing = dotenv_values(path)
    for name, value in dotenv_values(".env.example").items():
        if name not in existing:
            set_key(str(path), name, value or "")
    for name in ("OPENMCP_API_TOKEN", "OPENMCP_MPP_SECRET"):
        if not existing.get(name) or existing[name].startswith("replace-with-"):
            set_key(str(path), name, secrets.token_urlsafe(32))
    if existing.get("OPENMCP_DATABASE") == ".openmcp/demo.sqlite3":
        set_key(str(path), "OPENMCP_DATABASE", ".openmcp/mpp.sqlite3")
    os.chmod(path, 0o600)
    settings = Settings()
    addresses = create_wallets(settings.wallets)
    print(json.dumps({"chain_id": CHAIN_ID, "token": TOKEN, "wallets": addresses}, indent=2))
    print("Five wallets ready; keys kept in private local files. Existing wallets are preserved.")
    print("Next: uv run openmcp fund — funds only the two paying wallets from the testnet faucet.")


async def inspect_wallets(settings, *, fund=False, network=False):
    addresses = settings.addresses()
    chain = Chain(settings)
    try:
        if fund or network:
            await chain.check_network()
        if fund:
            for name in ("agent", "openmcp"):
                references = await chain.fund(addresses[name])
                print(
                    json.dumps(
                        {
                            "wallet": name,
                            "address": addresses[name],
                            "faucet_transactions": references,
                        }
                    )
                )
        if network or fund:
            wallets = {name: await chain.balance(address) for name, address in addresses.items()}
        else:
            wallets = addresses
        print(
            json.dumps(
                {
                    "payment_mode": "mpp_tempo_testnet",
                    "chain_id": CHAIN_ID,
                    "service_budget_cents": settings.budget_cents,
                    "wallets": wallets,
                },
                indent=2,
            )
        )
    finally:
        await chain.close()


async def api_command(settings, command):
    headers = {"Authorization": f"Bearer {settings.api_token.get_secret_value()}"}
    if command in ("balance", "reset"):
        async with httpx.AsyncClient(
            base_url=settings.base_url, headers=headers, timeout=120
        ) as client:
            response = await (
                client.get("/dashboard") if command == "balance" else client.post("/demo/reset")
            )
            print(json.dumps(Agent.result(response), indent=2))
            if command == "reset":
                print(
                    "New service budget. On-chain wallet balances and MPP payment journals are unchanged."
                )
        return
    agent = Agent(settings)
    try:
        discovery = await agent.discover(
            "FreightFlow operational health, legal liabilities and competitor market share",
            settings.budget_cents,
        )
        print(
            f"Discovered {len(discovery['endpoints'])} endpoints; total {discovery['total_price_cents'] / 100:.2f} test pathUSD"
        )
        for endpoint in discovery["endpoints"]:
            result = await agent.execute(
                ExecuteRequest(
                    session_id=discovery["session_id"],
                    endpoint_id=endpoint["endpoint_id"],
                    payload={"company": "FreightFlow"},
                    idempotency_key=f"demo-{discovery['session_id']}-{endpoint['endpoint_id']}",
                    max_price_cents=endpoint["price_cents"],
                    budget_cents=settings.budget_cents,
                )
            )
            print(json.dumps(result, indent=2))
        print(json.dumps(await agent.balance(), indent=2))
    finally:
        await agent.close()


async def check_mcp(mode="demo"):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    failure, summary = False, None
    async with stdio_client(
        StdioServerParameters(
            command=sys.executable, args=["-m", "openmcp.cli", "mcp", "--mode", mode]
        )
    ) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            balance = await session.call_tool("balance", {})
            discovery = await session.call_tool("discover", {
                "query": "services" if mode == "account" else "FreightFlow due diligence",
                "budget_cents": 0 if mode == "account" else 1500,
            })
            failure = balance.isError or discovery.isError
            if not failure:
                summary = {
                    "stdio": "ok",
                    "tools": [t.name for t in listed.tools],
                    "mode": mode,
                    "discovered_endpoints": len(discovery.structuredContent["endpoints"]),
                    "spent_by_check_cents": 0,
                }
                if mode == "account":
                    summary["available_cents"] = balance.structuredContent["available_cents"]
                    summary["agent"] = balance.structuredContent.get("agent")
                else:
                    summary["agent_wallet"] = balance.structuredContent["address"]
    if failure:
        raise ValueError("MCP tools failed. Start the middleware and check local configuration.")
    print(json.dumps(summary, indent=2))


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "creator":
        from openmcp_creator.cli import main as creator_main

        creator_main(sys.argv[2:])
        return
    from .client_setup.installer import InstallError, register_commands, run

    parser = argparse.ArgumentParser(
        description="OpenMCP — account-funded service purchases and an isolated testnet demo"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("creator", help="URL-to-paid-service worker; see creator --help")
    register_commands(commands)
    connect = commands.add_parser("connect", help="Save an account agent credential privately")
    connect.add_argument("--base-url", required=True, help="HTTPS account API origin")
    commands.add_parser("init", help="Create five fresh testnet wallets; preserve existing keys")
    commands.add_parser(
        "fund", help="Fund agent and OpenMCP wallets using the Tempo testnet faucet"
    )
    serve = commands.add_parser("serve", help="Serve the MPP payment-gated HTTP middleware")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--host", default="127.0.0.1")
    mcp = commands.add_parser("mcp", help="Local MCP tools for AI clients")
    check = commands.add_parser("check-mcp", help="Free stdio MCP connection check")
    for command in (serve, mcp, check):
        command.add_argument(
            "--mode", choices=("demo", "account"), default=os.environ.get("OPENMCP_MODE", "demo")
        )
    doctor = commands.add_parser("doctor", help="Show public configuration, never private keys")
    doctor.add_argument("--chain", action="store_true", help="Also query testnet wallet balances")
    commands.add_parser("balance", help="Show spending and all five on-chain wallet balances")
    commands.add_parser("reset", help="New service budget; no reversal of testnet transactions")
    commands.add_parser(
        "demo", help="Purchase all three sources, making six real MPP testnet payments"
    )
    args = parser.parse_args()
    try:
        if args.command in ("install", "mcp-config"):
            run(args)
            return
        if args.command == "init":
            initialize()
            return
        if args.command == "connect":
            import getpass

            from .account_client import AccountSettings, configure_account, validate_origin

            origin = validate_origin(args.base_url)
            credential = getpass.getpass("Agent credential (hidden): ")
            configure_account(AccountSettings(), origin, credential)
            print("Account connection saved privately. No payment was made.")
            print("Next: openmcp install all --mode account --scope user")
            return
        if args.command == "check-mcp":
            asyncio.run(check_mcp(args.mode))
            return
        if args.command == "mcp" and args.mode == "account":
            from .account_mcp import create_account_mcp

            create_account_mcp().run(transport="stdio")
            return
        if args.command == "serve" and args.mode == "account":
            from .product.app import create_app as create_product_app

            uvicorn.run(create_product_app(), host=args.host, port=args.port, workers=1)
            return
        settings = Settings()
        if args.command == "serve":
            from .app import create_app

            uvicorn.run(create_app(settings), host=args.host, port=args.port, workers=1)
        elif args.command == "mcp":
            from .mcp_server import create_mcp

            create_mcp(settings).run(transport="stdio")
        elif args.command == "fund":
            asyncio.run(inspect_wallets(settings, fund=True))
        elif args.command == "doctor":
            asyncio.run(inspect_wallets(settings, network=args.chain))
        else:
            asyncio.run(api_command(settings, args.command))
    except InstallError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    except (ValueError, OSError, OpenMCPError, httpx.HTTPError) as exc:
        # No SDK exception strings or signed credentials in terminal output.
        message = (
            exc.message
            if isinstance(exc, OpenMCPError)
            else f"{type(exc).__name__}: check configuration and network connectivity."
        )
        print(message, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
