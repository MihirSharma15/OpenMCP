"""Operator tools for DataForSEO. Secrets are read from the environment or ignored .env."""

import argparse
import asyncio
import base64
import json
import os
import shutil
from decimal import Decimal
from pathlib import Path

import httpx
from dotenv import load_dotenv

from .catalog import OVERVIEW, RELATED, SEARCH, SERVICES, provider
from .protocol import parse, prepare

SAMPLES = {
    SEARCH: {"keyword": "DataForSEO", "location_code": 2840, "language_code": "en"},
    OVERVIEW: {"keywords": ["keyword research"], "location_code": 2840, "language_code": "en"},
    RELATED: {
        "keyword": "keyword research",
        "limit": 3,
        "location_code": 2840,
        "language_code": "en",
    },
}
MCP_SOURCE = Path(".openmcp/dataforseo/mcp-server")


def write_catalog(path, mode):
    """Merge this provider into an operator file; preserve other providers."""
    from openmcp.product.config import ProductSettings, Provider

    path = Path(path)
    existing = ProductSettings(_env_file=None, catalog_path=path).catalog() if path.exists() else []
    new = Provider.model_validate(provider(mode))
    entries = [p for p in existing if p.provider_id != new.provider_id] + [new]
    ids = [q.endpoint_id for p in entries for q in p.queries]
    if len(ids) != len(set(ids)):
        raise ValueError("An existing provider owns a DataForSEO endpoint ID")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("Catalog must not be a symlink")
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("x") as output:
        output.write(json.dumps([p.model_dump(mode="json") for p in entries], indent=2) + "\n")
    os.replace(temporary, path)


def mcp_command(source):
    node = shutil.which("node")
    entry = Path(source).resolve() / "dist/index.js"
    if not node or not entry.is_file():
        raise ValueError("Build the official MCP server first; see docs/dataforseo.md")
    secret = os.environ.get("DATAFORSEO_AUTH", "")
    try:
        login, password = base64.b64decode(secret, validate=True).decode().split(":", 1)
        if not login or not password:
            raise ValueError()
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Configure DATAFORSEO_AUTH privately before running MCP") from exc
    env = {
        "PATH": os.environ.get("PATH", ""),
        "DATAFORSEO_LOGIN": login,
        "DATAFORSEO_PASSWORD": password,
    }
    cache = Path(".openmcp/dataforseo/docs-cache").resolve()
    return node, [str(entry), "--docs-cache-dir", str(cache)], env


async def check_mcp(source):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    node, args, env = mcp_command(source)
    async with stdio_client(StdioServerParameters(command=node, args=args, env=env)) as (
        read,
        write,
    ):
        async with ClientSession(read, write) as session:
            result = await session.initialize()
            tools = await session.list_tools()
            print(
                json.dumps(
                    {
                        "server": result.serverInfo.model_dump(),
                        "tools": [t.name for t in tools.tools],
                    }
                )
            )
            for endpoint_id, service in SERVICES.items():
                docs = await session.call_tool(
                    "docs_search", {"url": service["path"].removeprefix("/v3/")}
                )
                if docs.isError:
                    raise ValueError("Upstream MCP documentation check failed")
                print(json.dumps({"endpoint_id": endpoint_id, "documentation": "ok"}))


async def check_api(*, live=False, max_cost_usd=None):
    mode = "live" if live else "test"
    # Published prices for these specific small samples; no optional paid extras.
    estimates = {
        SEARCH: Decimal("0.002"),
        OVERVIEW: Decimal("0.01212"),
        RELATED: Decimal("0.01236"),
    }
    if live and (
        max_cost_usd is None
        or not max_cost_usd.is_finite()
        or max_cost_usd < sum(estimates.values())
    ):
        raise ValueError(
            "Live validation requires --max-cost-usd covering the $0.02648 estimated sample cost"
        )
    spent = Decimal(0)
    secret = os.environ.get("DATAFORSEO_AUTH", "")
    async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
        for service in provider(mode)["queries"]:
            endpoint_id = service["endpoint_id"]
            if live and spent + estimates[endpoint_id] > max_cost_usd:
                raise ValueError("Remaining validation budget cannot cover the next sample")
            payload = SAMPLES[endpoint_id]
            body, authorization = prepare(endpoint_id, service["url"], mode, payload, secret)
            response = await client.post(
                service["url"], json=body, headers={"Authorization": authorization}
            )
            if not response.is_success:
                try:
                    status = response.json().get("status_code")
                except (ValueError, AttributeError):
                    status = None
                status = status if type(status) is int else "unknown"
                hint = (
                    " Complete account verification in the DataForSEO dashboard."
                    if status == 40104
                    else ""
                )
                raise ValueError(
                    f"DataForSEO HTTP {response.status_code}, API status {status}.{hint}"
                )
            response.raise_for_status()
            data, receipt, cost = parse(endpoint_id, mode, payload, response.json())
            # Sandbox may return illustrative cost fields; it never bills this account.
            if live:
                spent += Decimal(cost) / 1_000_000
            print(
                json.dumps(
                    {
                        "endpoint_id": endpoint_id,
                        "items": len(data["items"]),
                        "sandbox": not live,
                        "reported_cost_usd": receipt["reported_cost_usd"],
                        "validation_spend_usd": str(spent),
                    }
                )
            )
            if live and spent > max_cost_usd:
                raise ValueError("Reported vendor cost exceeded the validation budget; stopping")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    catalog = commands.add_parser("catalog", help="Merge three services into a catalog file")
    catalog.add_argument("--output", type=Path, default=Path("catalog/dataforseo.json"))
    catalog.add_argument("--mode", choices=["test", "live"], default="test")
    check = commands.add_parser("check", help="Test three small samples; free sandbox by default")
    check.add_argument("--live", action="store_true", help="Use billable production APIs")
    check.add_argument("--max-cost-usd", type=Decimal)
    for name in ("mcp", "mcp-check"):
        sub = commands.add_parser(
            name,
            help="Run the official MCP server"
            if name == "mcp"
            else "Free MCP handshake and documentation checks",
        )
        sub.add_argument("--source", type=Path, default=MCP_SOURCE)
    args = parser.parse_args(argv)
    load_dotenv(".env")
    try:
        if args.command == "catalog":
            write_catalog(args.output, args.mode)
            print(f"DataForSEO {args.mode} catalog saved to {args.output}")
        elif args.command == "check":
            asyncio.run(check_api(live=args.live, max_cost_usd=args.max_cost_usd))
        elif args.command == "mcp-check":
            asyncio.run(check_mcp(args.source))
        else:
            node, arguments, environment = mcp_command(args.source)
            os.execve(node, [node, *arguments], environment)
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
    except Exception as exc:
        # Do not print HTTP objects or arbitrary upstream exception text.
        parser.exit(
            1, f"DataForSEO check failed ({type(exc).__name__}); credentials were not printed.\n"
        )
