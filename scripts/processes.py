"""Shared process supervision for the local demo servers."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ProcessSpec:
    name: str
    command: tuple[str, ...]
    port: int


@dataclass(frozen=True, slots=True)
class ManagedProcess:
    spec: ProcessSpec
    process: subprocess.Popen[bytes]


def uvicorn_process(name: str, app: str, port: int) -> ProcessSpec:
    return ProcessSpec(
        name,
        (
            sys.executable,
            "-m",
            "uvicorn",
            app,
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--workers",
            "1",
        ),
        port,
    )


def start_processes(
    specs: Iterable[ProcessSpec],
    *,
    project_root: Path,
    env: dict[str, str] | None = None,
) -> list[ManagedProcess]:
    processes: list[ManagedProcess] = []
    try:
        for spec in specs:
            process = subprocess.Popen(
                spec.command,
                cwd=project_root,
                env=env or os.environ.copy(),
                shell=False,
            )
            processes.append(ManagedProcess(spec, process))
            print(f"Starting {spec.name} on http://127.0.0.1:{spec.port}")
    except BaseException:
        terminate_processes(processes)
        raise
    return processes


def wait_until_ready(
    processes: list[ManagedProcess],
    *,
    should_stop: Callable[[], bool],
    timeout: float = 30,
) -> bool:
    pending = {managed.spec.port: managed for managed in processes}
    deadline = time.monotonic() + timeout
    while pending:
        if should_stop():
            return False
        _raise_if_exited(processes)
        for port in tuple(pending):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    pending.pop(port)
            except OSError:
                pass
        if pending:
            if time.monotonic() >= deadline:
                names = ", ".join(managed.spec.name for managed in pending.values())
                raise RuntimeError(f"Timed out waiting for: {names}")
            time.sleep(0.1)
    _raise_if_exited(processes)
    return True


def monitor_processes(
    processes: list[ManagedProcess],
    *,
    should_stop: Callable[[], bool],
) -> int:
    while not should_stop():
        for managed in processes:
            result = managed.process.poll()
            if result is not None:
                print(
                    f"{managed.spec.name} exited unexpectedly with status {result}.",
                    file=sys.stderr,
                )
                return result or 1
        time.sleep(0.25)
    return 0


def terminate_processes(processes: list[ManagedProcess], *, timeout: float = 8) -> None:
    deadline = time.monotonic() + timeout
    for managed in reversed(processes):
        if managed.process.poll() is not None:
            continue
        # Stop dependants first and let them finish while their upstream
        # processes are still available (runner → gateway → providers).
        managed.process.terminate()
        remaining = max(0.0, deadline - time.monotonic())
        try:
            managed.process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            managed.process.kill()

    for managed in reversed(processes):
        if managed.process.poll() is None:
            managed.process.wait()


def _raise_if_exited(processes: list[ManagedProcess]) -> None:
    for managed in processes:
        result = managed.process.poll()
        if result is not None:
            raise RuntimeError(f"{managed.spec.name} exited during startup with status {result}.")
