"""Launch the MPP provider service and its three traditional APIs."""

import os
import signal
import sys
from pathlib import Path

from dotenv import load_dotenv

from openmcp.config import CHAIN_ID
from openmcp_provider import ProviderSettings, load_public_addresses
from scripts.processes import (
    ManagedProcess,
    monitor_processes,
    start_processes,
    terminate_processes,
    uvicorn_process,
    wait_until_ready,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"


PROVIDER_PROCESSES = (
    uvicorn_process("SupplySignal traditional API", "traditional_apis.supplysignal:app", 9101),
    uvicorn_process("CourtLens traditional API", "traditional_apis.courtlens:app", 9102),
    uvicorn_process("MarketScope traditional API", "traditional_apis.marketscope:app", 9103),
    uvicorn_process("MPP provider service", "providers.app:app", 9001),
)


def provider_preflight() -> ProviderSettings:
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


def main() -> int:
    os.chdir(PROJECT_ROOT)
    load_dotenv(ENV_PATH, override=False)
    try:
        provider_preflight()
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

    processes: list[ManagedProcess] = []
    exit_code = 0
    try:
        processes = start_processes(
            PROVIDER_PROCESSES,
            project_root=PROJECT_ROOT,
            env=os.environ.copy(),
        )
        ready = wait_until_ready(processes, should_stop=lambda: stopping)
        if ready:
            print("All four provider-side servers are ready. Press Ctrl-C to stop.")
            exit_code = monitor_processes(processes, should_stop=lambda: stopping)
    except (OSError, RuntimeError) as exc:
        print(f"Provider startup error: {exc}", file=sys.stderr)
        exit_code = 1
    finally:
        terminate_processes(processes)

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
