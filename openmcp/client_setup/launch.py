"""Start MCP from its own runtime directory, independent of the editor's cwd."""

import argparse
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        os.chdir(args.runtime_dir)
    except OSError:
        parser.exit(1, "OpenMCP runtime directory is unavailable; rerun the installer.\n")

    # Import after chdir so dotenv and default state paths belong to OpenMCP,
    # never to the project whose assistant happens to launch the process.
    from openmcp.config import Settings
    from openmcp.mcp_server import create_mcp

    try:
        server = create_mcp(Settings())
    except (OSError, ValueError):
        parser.exit(1, "OpenMCP setup is incomplete; run openmcp init in the runtime directory.\n")
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
