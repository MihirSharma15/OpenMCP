"""Persistent payment and fulfillment state for provider requests."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiosqlite


def canonical(value: object) -> bytes:
    """Return the canonical JSON representation used by OpenMCP."""

    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def memo_for(execution_id: str) -> str:
    return "0x" + hashlib.sha256(execution_id.encode()).hexdigest()


def fingerprint_for(route_id: str, body: dict[str, Any]) -> str:
    return hashlib.sha256(canonical({"endpoint": route_id, "body": body})).hexdigest()


def hash_credential(authorization: str) -> str:
    return hashlib.sha256(authorization.encode()).hexdigest()


def prepare_private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)


def load_or_create_secrets(path: Path, realms: set[str]) -> dict[str, str]:
    """Load stable challenge secrets and generate any missing realm entries."""

    prepare_private_directory(path.parent)
    saved: dict[str, str] = {}
    if path.exists():
        if not stat.S_ISREG(path.stat().st_mode):
            raise ValueError(f"Provider secrets path is not a regular file: {path}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("Provider secrets file must contain a JSON object")
        if not all(isinstance(key, str) and isinstance(value, str) for key, value in raw.items()):
            raise ValueError("Provider secrets file contains an invalid entry")
        saved = raw

    changed = False
    for realm in sorted(realms):
        if len(saved.get(realm, "")) < 32:
            saved[realm] = secrets.token_urlsafe(48)
            changed = True

    if changed or not path.exists():
        temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(saved, file, indent=2, sort_keys=True)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()
    os.chmod(path, 0o600)
    return {realm: saved[realm] for realm in realms}


@dataclass(frozen=True, slots=True)
class Fulfillment:
    execution_id: str
    route: str
    fingerprint: str
    credential_hash: str
    receipt: str
    response_json: str | None


class FulfillmentStore:
    """Durable receipt-first fulfillment records."""

    def __init__(self, database: aiosqlite.Connection, path: Path) -> None:
        self._database = database
        self.path = path

    @classmethod
    async def create(cls, path: Path) -> FulfillmentStore:
        prepare_private_directory(path.parent)
        database = await aiosqlite.connect(path)
        os.chmod(path, 0o600)
        await database.execute("PRAGMA journal_mode=WAL")
        await database.execute("PRAGMA busy_timeout=10000")
        await database.execute(
            """
            CREATE TABLE IF NOT EXISTS fulfillments (
                execution_id TEXT PRIMARY KEY,
                route TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                credential_hash TEXT NOT NULL,
                receipt TEXT NOT NULL,
                response_json TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        await database.commit()
        return cls(database, path)

    async def close(self) -> None:
        await self._database.close()

    async def get(self, execution_id: str) -> Fulfillment | None:
        cursor = await self._database.execute(
            """
            SELECT execution_id, route, fingerprint, credential_hash, receipt, response_json
            FROM fulfillments
            WHERE execution_id = ?
            """,
            (execution_id,),
        )
        row = await cursor.fetchone()
        await cursor.close()
        return Fulfillment(*row) if row else None

    async def save_payment(
        self,
        *,
        execution_id: str,
        route: str,
        fingerprint: str,
        credential_hash: str,
        receipt: str,
    ) -> None:
        now = time.time()
        await self._database.execute(
            """
            INSERT INTO fulfillments(
                execution_id, route, fingerprint, credential_hash, receipt,
                response_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?)
            """,
            (execution_id, route, fingerprint, credential_hash, receipt, now, now),
        )
        await self._database.commit()

    async def save_response(self, execution_id: str, response_json: str) -> None:
        cursor = await self._database.execute(
            """
            UPDATE fulfillments
            SET response_json = ?, updated_at = ?
            WHERE execution_id = ? AND response_json IS NULL
            """,
            (response_json, time.time(), execution_id),
        )
        await self._database.commit()
        if cursor.rowcount != 1:
            raise RuntimeError("Fulfillment record was not pending")
        await cursor.close()
