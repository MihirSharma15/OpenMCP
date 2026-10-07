"""Operator catalog setup and an explicitly requested single-credit live check."""

import argparse
import asyncio
import json
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

from .catalog import SEARCH, URL, provider
from .protocol import DEFAULT_CREDIT_COST_MICROUSD, credit_rate, parse, prepare


def write_catalog(path, mode):
    from openmcp.integrations.catalog_tools import write_provider

    write_provider(path, provider(mode))


async def check():
    # One attempt, no SDK retries or automatic advanced-search upgrades.
    payload = {"query": "Tavily official documentation", "max_results": 1}
    body, auth = prepare(SEARCH, URL, "live", payload, os.environ.get("TAVILY_API_KEY", ""))
    rate = credit_rate(
        os.environ.get("TAVILY_CREDIT_COST_MICROUSD", str(DEFAULT_CREDIT_COST_MICROUSD))
    )
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
        response = await client.post(URL, json=body, headers={"Authorization": auth})
    if not response.is_success:
        raise ValueError(f"Tavily check failed (HTTP {response.status_code}); not retried")
    data, receipt, _ = parse(payload, response.json(), rate)
    print(
        json.dumps(
            {"status": "success", "results_count": len(data["results"]), "receipt": receipt},
            indent=2,
        )
    )


def register():
    from openmcp.integrations.catalog_tools import register_provider

    register_provider(provider)


def main(argv=None):
    load_dotenv(".env")
    parser = argparse.ArgumentParser(
        description="Tavily service catalog and minimal basic-search verification"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("register", help="Add Tavily to a database-managed catalog; no deletions")
    catalog = commands.add_parser("catalog", help="Merge Tavily into the complete approved catalog")
    catalog.add_argument("--output", type=Path, required=True)
    catalog.add_argument("--mode", choices=("test", "live"), default="test")
    live = commands.add_parser("check", help="Make ONE real basic search (one Tavily credit)")
    live.add_argument("--allow-one-credit", action="store_true", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "catalog":
            write_catalog(args.output, args.mode)
            print(f"Merged Tavily into {args.output}. Other providers preserved.")
        elif args.command == "register":
            register()
        else:
            asyncio.run(check())
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
    except httpx.HTTPError:
        # Neither upstream error bodies nor request credentials belong in CLI logs.
        parser.exit(1, "Tavily setup/check failed. Check configuration; request was not retried.\n")


if __name__ == "__main__":
    main()
