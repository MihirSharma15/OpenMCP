"""Launch the MPP provider service and its three traditional APIs."""

import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from openmcp.config import CHAIN_ID
from openmcp_provider import ProviderSettings, load_public_addresses

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"


@dataclass(frozen=True, slots=True)
class Server:
    name: str
    app: str
    port: int


SERVERS = (
    Server("SupplySignal traditional API", "traditional_apis.supplysignal:app", 9101),
    Server("CourtLens traditional API", "traditional_apis.courtlens:app", 9102),
    Server("MarketScope traditional API", "traditional_apis.marketscope:app", 9103),
    Server("MPP provider service", "providers.app:app", 9001),
)


def _preflight() -> ProviderSettings:
    settings = ProviderSettings()
    addresses = load_public_addresses(settings.wallets)
    required = ("operations", "legal", "market")
    if any(name not in addresses for name in required):
        raise RuntimeError("Provider wallets are missing; run `uv run openmcp init`.")
    if len({addresses[name].lower() for name in required}) != len(required):
        raise RuntimeError("Provider recipient wallets must be distinct.")
    print(f"Preflight passed: Tempo Moderato chain {CHAIN_ID}; provider wallets are ready.")
    print("Provider startup will verify catalog routes, fees, prices, and public recipients.")
    print(f"Persistent provider state: {settings.state_dir}")
    return settings


def _terminate(processes: list[tuple[Server, subprocess.Popen[bytes]]]) -> None:
    for _, process in processes:
        if process.poll() is None:
            process.terminate()
    for _, process in processes:
        if process.poll() is not None:
            continue
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
    for _, process in processes:
        if process.poll() is None:
            process.wait()


def main() -> int:
    os.chdir(PROJECT_ROOT)
    load_dotenv(ENV_PATH, override=False)
    try:
        _preflight()
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    stopping = False

    def request_stop(signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True
        print(f"\nReceived signal {signum}; stopping all provider servers.")

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    processes: list[tuple[Server, subprocess.Popen[bytes]]] = []
    exit_code = 0
    try:
        for server in SERVERS:
            command = [
                sys.executable,
                "-m",
                "uvicorn",
                server.app,
                "--host",
                "127.0.0.1",
                "--port",
                str(server.port),
                "--workers",
                "1",
            ]
            process = subprocess.Popen(
                command,
                cwd=PROJECT_ROOT,
                env=os.environ.copy(),
                shell=False,
            )
            processes.append((server, process))
            print(f"Started {server.name} on http://127.0.0.1:{server.port}")

        print("All four provider-side servers started. Press Ctrl-C to stop.")
        while not stopping:
            for server, process in processes:
                result = process.poll()
                if result is not None:
                    print(
                        f"{server.name} exited unexpectedly with status {result}.",
                        file=sys.stderr,
                    )
                    exit_code = result or 1
                    stopping = True
                    break
            if not stopping:
                time.sleep(0.25)
    finally:
        _terminate(processes)

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
