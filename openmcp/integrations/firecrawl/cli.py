"""Operator catalog commands. No command here makes a paid vendor request."""

import argparse
from pathlib import Path

from dotenv import load_dotenv

from openmcp.integrations.catalog_tools import register_provider, write_provider

from .catalog import provider


def write_catalog(path, mode):
    write_provider(path, provider(mode))


def main(argv=None):
    load_dotenv(".env")
    parser = argparse.ArgumentParser(description="Firecrawl catalog setup (no vendor calls)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("register", help="Add Firecrawl to the database catalog without deletions")
    catalog = commands.add_parser("catalog", help="Merge Firecrawl into a full approved catalog")
    catalog.add_argument("--output", type=Path, required=True)
    catalog.add_argument("--mode", choices=("test", "live"), default="test")
    args = parser.parse_args(argv)
    try:
        if args.command == "register":
            register_provider(provider)
        else:
            write_catalog(args.output, args.mode)
            print(f"Merged Firecrawl into {args.output}. Other providers preserved.")
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
