"""Start MCP from its own runtime directory, independent of the editor's cwd."""

import argparse
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-dir", type=Path, required=True)
    parser.add_argument("--mode", choices=("account",), default="account")
    args = parser.parse_args()
    try:
        os.chdir(args.runtime_dir)
    except OSError:
        parser.exit(1, "OpenMCP runtime directory is unavailable; rerun the installer.\n")

    # Import after chdir so dotenv and default state paths belong to OpenMCP,
    # never to the project whose assistant happens to launch the process.
    try:
        from openmcp.account_mcp import create_account_mcp

        server = create_account_mcp()
    except (OSError, ValueError):
        parser.exit(1, "OpenMCP setup is incomplete; run openmcp connect --base-url API_ORIGIN.\n")
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
