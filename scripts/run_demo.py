"""Launch every Python process required by the live frontend demo."""

import os
import signal
import sys
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

from openmcp.config import Settings
from scripts.processes import (
    ManagedProcess,
    ProcessSpec,
    monitor_processes,
    start_processes,
    terminate_processes,
    uvicorn_process,
    wait_until_ready,
)
from scripts.run_providers import PROVIDER_PROCESSES, provider_preflight

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"


def _preflight() -> None:
    provider_preflight()
    settings = Settings()
    settings.addresses()
    if (
        min(
            len(settings.api_token.get_secret_value()),
            len(settings.payment_secret.get_secret_value()),
        )
        < 16
    ):
        raise RuntimeError("Run `uv run openmcp init` to create the local demo secrets.")
    gateway = urlparse(settings.base_url)
    if (
        gateway.scheme != "http"
        or gateway.hostname not in {"127.0.0.1", "localhost"}
        or gateway.port != 8000
        or gateway.path not in {"", "/"}
    ):
        raise RuntimeError("OPENMCP_BASE_URL must point to http://127.0.0.1:8000.")


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
        print(f"\nReceived signal {signum}; stopping the local demo stack.")

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    gateway = ProcessSpec(
        "OpenMCP gateway",
        (sys.executable, "-m", "openmcp.cli", "serve", "--port", "8000"),
        8000,
    )
    runner = uvicorn_process("OpenMCP demo runner", "demo_runner.app:app", 8100)
    specs = (*PROVIDER_PROCESSES, gateway, runner)
    processes: list[ManagedProcess] = []
    exit_code = 0
    try:
        processes = start_processes(
            specs,
            project_root=PROJECT_ROOT,
            env=os.environ.copy(),
        )
        ready = wait_until_ready(processes, should_stop=lambda: stopping)
        if ready:
            print(
                "Python demo stack is ready. Start the frontend separately with "
                "`cd frontend && npm run dev`."
            )
            exit_code = monitor_processes(processes, should_stop=lambda: stopping)
    except (OSError, RuntimeError) as exc:
        print(f"Demo startup error: {exc}", file=sys.stderr)
        exit_code = 1
    finally:
        # Stop the observer while the gateway/providers remain alive, then tear
        # down the upstream processes.
        terminate_processes(processes, timeout=180)

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
