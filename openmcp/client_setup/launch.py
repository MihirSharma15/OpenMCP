"""Start MCP from its own runtime directory, independent of the editor's cwd."""

import argparse
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-dir", type=Path, required=True)
    parser.add_argument("--mode", choices=("demo", "account"), default="demo")
    args = parser.parse_args()
    try:
        os.chdir(args.runtime_dir)
    except OSError:
        parser.exit(1, "OpenMCP runtime directory is unavailable; rerun the installer.\n")

    # Import after chdir so dotenv and default state paths belong to OpenMCP,
    # never to the project whose assistant happens to launch the process.
    try:
        if args.mode == "account":
            from openmcp.account_mcp import create_account_mcp

            server = create_account_mcp()
        else:
            from openmcp.config import Settings
            from openmcp.mcp_server import create_mcp

            server = create_mcp(Settings())
    except (OSError, ValueError):
        command = "openmcp connect --base-url API_ORIGIN" if args.mode == "account" else "openmcp init"
        parser.exit(1, f"OpenMCP setup is incomplete; run {command} in the runtime directory.\n")
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
