"""Persistent MPP execution ledger and SDK replay store; single server worker."""

import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .models import OpenMCPError


def uid(prefix):
    return f"{prefix}_{uuid.uuid4().hex}"


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        if not path.exists():
            path.touch(mode=0o600)
        os.chmod(path, 0o600)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()


class Store(Database):
    def __init__(self, path: Path, budget_cents: int):
        super().__init__(path)
        with self.connection() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS mpp_sessions (
                    id TEXT PRIMARY KEY, budget INTEGER NOT NULL, spent INTEGER NOT NULL DEFAULT 0,
                    reserved INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1
                );
                CREATE UNIQUE INDEX IF NOT EXISTS mpp_one_active ON mpp_sessions(active) WHERE active=1;
                CREATE TABLE IF NOT EXISTS mpp_executions (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL, key TEXT NOT NULL, doc TEXT NOT NULL,
                    UNIQUE(session_id,key)
                );
                CREATE TABLE IF NOT EXISTS mpp_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
                    execution_id TEXT, type TEXT NOT NULL, detail TEXT NOT NULL, created REAL NOT NULL
                );
            """)
            if not db.execute("SELECT id FROM mpp_sessions WHERE active=1").fetchone():
                db.execute(
                    "INSERT INTO mpp_sessions(id,budget) VALUES (?,?)",
                    (uid("session"), budget_cents),
                )

    def balance(self):
        with self.connection() as db:
            row = db.execute("SELECT * FROM mpp_sessions WHERE active=1").fetchone()
            return {
                "session_id": row["id"],
                "currency": "pathUSD",
                "source": "openmcp_spending_limit",
                "budget_cents": row["budget"],
                "spent_cents": row["spent"],
                "reserved_cents": row["reserved"],
                "remaining_cents": row["budget"] - row["spent"] - row["reserved"],
            }

    def existing(self, session_id, key):
        with self.connection() as db:
            row = db.execute(
                "SELECT doc FROM mpp_executions WHERE session_id=? AND key=?", (session_id, key)
            ).fetchone()
            return json.loads(row["doc"]) if row else None

    def create(self, request, fingerprint, provider, destination, fee):
        balance = self.balance()
        if request.session_id != balance["session_id"]:
            raise OpenMCPError("stale_session", "Session changed; call balance again.", 409)
        if balance["spent_cents"] + balance["reserved_cents"] + provider["price_cents"] > min(
            balance["budget_cents"], request.budget_cents
        ):
            raise OpenMCPError("insufficient_budget", "Purchase exceeds the session budget.", 409)
        row = {
            "id": uid("exec"),
            "session_id": request.session_id,
            "key": request.idempotency_key,
            "fingerprint": fingerprint,
            "state": "quoted",
            "price": provider["price_cents"],
            "fee": fee,
            "provider": provider,
            "destination": destination,
            "created": time.time(),
            "incoming_credential": None,
            "incoming_receipt": None,
            "outgoing_receipt": None,
            "data": None,
            "error": None,
        }
        with self.connection() as db:
            db.execute(
                "INSERT INTO mpp_executions VALUES(?,?,?,?)",
                (row["id"], row["session_id"], row["key"], json.dumps(row)),
            )
        return row

    @staticmethod
    def _save(db, row):
        db.execute("UPDATE mpp_executions SET doc=? WHERE id=?", (json.dumps(row), row["id"]))

    @staticmethod
    def _event(db, row, kind, detail):
        db.execute(
            "INSERT INTO mpp_events(session_id,execution_id,type,detail,created) VALUES(?,?,?,?,?)",
            (row["session_id"], row.get("id"), kind, json.dumps(detail), time.time()),
        )

    def event(self, row, kind, **detail):
        with self.connection() as db:
            self._event(db, row, kind, detail)

    def update(self, row, state, **values):
        row = {**row, **values, "state": state}
        with self.connection() as db:
            self._save(db, row)
        return row

    def reserve(self, row, budget, authorization):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            session = db.execute("SELECT * FROM mpp_sessions WHERE active=1").fetchone()
            ceiling = min(session["budget"], budget)
            if session["id"] != row["session_id"]:
                raise OpenMCPError("stale_session", "Session changed; rediscover.", 409)
            if session["spent"] + session["reserved"] + row["price"] > ceiling:
                raise OpenMCPError(
                    "insufficient_budget", "Purchase exceeds the session budget.", 409
                )
            row = {**row, "state": "payment_pending", "incoming_credential": authorization}
            db.execute(
                "UPDATE mpp_sessions SET reserved=reserved+?,budget=? WHERE id=?",
                (row["price"], ceiling, row["session_id"]),
            )
            self._save(db, row)
            self._event(db, row, "agent_payment_submitted", {"amount_cents": row["price"]})
        return row

    def paid(self, row, receipt):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "UPDATE mpp_sessions SET reserved=reserved-?,spent=spent+? WHERE id=?",
                (row["price"], row["price"], row["session_id"]),
            )
            row = {**row, "state": "provider_pending", "incoming_receipt": receipt}
            self._save(db, row)
            self._event(
                db,
                row,
                "agent_payment_confirmed",
                {"amount_cents": row["price"], "receipt": receipt},
            )
        return row

    def transactions(self):
        with self.connection() as db:
            return [
                json.loads(r["doc"])
                for r in db.execute(
                    "SELECT doc FROM mpp_executions WHERE session_id=? ORDER BY rowid",
                    (self.balance()["session_id"],),
                )
            ]

    def events(self, after=0):
        with self.connection() as db:
            rows = db.execute(
                "SELECT * FROM mpp_events WHERE session_id=? AND id>? ORDER BY id LIMIT 200",
                (self.balance()["session_id"], after),
            )
            return [{**dict(r), "detail": json.loads(r["detail"])} for r in rows]

    def reset(self, budget_cents):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT id FROM mpp_sessions WHERE active=1").fetchone()["id"]
            rows = db.execute("SELECT doc FROM mpp_executions WHERE session_id=?", (current,))
            if any(json.loads(r["doc"])["state"] not in ("quoted", "completed") for r in rows):
                raise OpenMCPError(
                    "pending_execution", "Resolve pending MPP payments before resetting.", 409
                )
            db.execute("UPDATE mpp_sessions SET active=0 WHERE active=1")
            session_id = uid("session")
            db.execute(
                "INSERT INTO mpp_sessions(id,budget) VALUES(?,?)", (session_id, budget_cents)
            )
            self._event(
                db, {"session_id": session_id}, "session_started", {"budget_cents": budget_cents}
            )
        return self.balance()


class ReplayStore(Database):
    """MPP Store protocol. No expiry: completed transaction hashes stay recorded."""

    def __init__(self, path):
        super().__init__(path)
        with self.connection() as db:
            db.execute("CREATE TABLE IF NOT EXISTS mpp_replay(key TEXT PRIMARY KEY,value TEXT)")

    async def get(self, key):
        with self.connection() as db:
            row = db.execute("SELECT value FROM mpp_replay WHERE key=?", (key,)).fetchone()
            return row["value"] if row else None

    async def put(self, key, value):
        with self.connection() as db:
            db.execute("INSERT OR REPLACE INTO mpp_replay VALUES(?,?)", (key, value))

    async def put_if_absent(self, key, value):
        with self.connection() as db:
            return (
                db.execute("INSERT OR IGNORE INTO mpp_replay VALUES(?,?)", (key, value)).rowcount
                == 1
            )

    async def delete(self, key):
        with self.connection() as db:
            db.execute("DELETE FROM mpp_replay WHERE key=?", (key,))


class PaymentJournal(Database):
    """Persist signed credentials BEFORE sending them, so retries cannot sign a second payment."""

    def __init__(self, path):
        super().__init__(path)
        with self.connection() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS payments(key TEXT PRIMARY KEY,scope TEXT,amount INTEGER,doc TEXT)"
            )

    def get(self, key):
        with self.connection() as db:
            row = db.execute("SELECT doc FROM payments WHERE key=?", (key,)).fetchone()
            return json.loads(row["doc"]) if row else None

    def save(self, key, scope, amount, doc, budget):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT key FROM payments WHERE key=?", (key,)).fetchone()
            if not existing:
                total = db.execute(
                    "SELECT COALESCE(SUM(amount),0) FROM payments WHERE scope=?", (scope,)
                ).fetchone()[0]
                if total + amount > budget:
                    raise OpenMCPError(
                        "wallet_budget_exceeded", "Local wallet signing budget exceeded.", 409
                    )
            db.execute(
                "INSERT OR REPLACE INTO payments VALUES(?,?,?,?)",
                (key, scope, amount, json.dumps(doc)),
            )
