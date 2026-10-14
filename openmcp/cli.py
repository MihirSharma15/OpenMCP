"""Account client, service operator, and API Creator commands."""

import argparse
import asyncio
import json
import sys

import httpx
import uvicorn

from .errors import OpenMCPError


async def check_mcp(mode="account"):
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
            discovery = await session.call_tool(
                "discover",
                {
                    "query": "services",
                    "budget_cents": 0,
                },
            )
            failure = balance.isError or discovery.isError
            if not failure:
                summary = {
                    "stdio": "ok",
                    "tools": [t.name for t in listed.tools],
                    "mode": mode,
                    "discovered_endpoints": (
                        sum(
                            len(provider["queries"])
                            for provider in discovery.structuredContent["providers"]
                        )
                    ),
                    "spent_by_check_cents": 0,
                }
                summary["available_cents"] = balance.structuredContent["available_cents"]
                summary["agent"] = balance.structuredContent.get("agent")
    if failure:
        raise ValueError("MCP tools failed. Start the middleware and check local configuration.")
    print(json.dumps(summary, indent=2))


def main(argv=None):
    arguments = sys.argv[1:] if argv is None else argv
    if arguments and arguments[0] == "providers":
        from .providers import main as run

        return run(arguments[1:])
    if arguments and arguments[0] == "creator":
        from openmcp_creator.cli import main as run

        return run(arguments[1:])
    if arguments and arguments[0] in {
        "worker",
        "migrate",
        "database-check",
        "doctor",
        "review",
        "reconcile",
    }:
        from .product.cli import main as run

        return run(arguments)
    from .client_setup.installer import InstallError, register_commands, run

    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in (
        "providers",
        "creator",
        "worker",
        "migrate",
        "database-check",
        "doctor",
        "review",
        "reconcile",
    ):
        commands.add_parser(command, help=f"See openmcp {command} --help")
    register_commands(commands)
    connect = commands.add_parser("connect", help="Save an account agent credential privately")
    connect.add_argument("--base-url", required=True)
    serve = commands.add_parser("serve", help="Serve the account HTTP API")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--host", default="127.0.0.1")
    mcp = commands.add_parser("mcp", help="Account MCP tools for AI clients")
    check = commands.add_parser("check-mcp", help="Free account MCP connection check")
    for command in (serve, mcp, check):
        command.add_argument(
            "--mode", choices=("account",), default="account", help=argparse.SUPPRESS
        )
    commands.add_parser("balance", help="Read account funds and the agent allowance")
    args = parser.parse_args(arguments)
    try:
        if args.command in ("install", "mcp-config"):
            run(args)
        elif args.command == "connect":
            import getpass

            from .account_client import AccountSettings, configure_account, validate_origin

            origin = validate_origin(args.base_url)
            configure_account(
                AccountSettings(), origin, getpass.getpass("Agent credential (hidden): ")
            )
            print("Account connection saved. Next: openmcp install all --scope user")
        elif args.command == "check-mcp":
            asyncio.run(check_mcp())
        elif args.command == "mcp":
            from .account_mcp import create_account_mcp

            create_account_mcp().run(transport="stdio")
        elif args.command == "serve":
            from .product.app import create_app

            uvicorn.run(create_app(), host=args.host, port=args.port, workers=1)
        else:
            asyncio.run(balance())
    except (InstallError, ValueError, OSError, OpenMCPError, httpx.HTTPError) as exc:
        message = (
            exc.message
            if isinstance(exc, OpenMCPError)
            else f"{type(exc).__name__}: check configuration and network connectivity."
        )
        parser.exit(1, message + "\n")


async def balance():
    from .account_client import AccountClient

    client = AccountClient()
    try:
        print(json.dumps(await client.balance(), indent=2))
    finally:
        await client.close()


if __name__ == "__main__":
    main()
