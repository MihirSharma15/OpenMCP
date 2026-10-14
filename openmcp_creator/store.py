"""Local Creator checkpoints and a durable journal for generated-service calls."""

import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager

from openmcp.errors import OpenMCPError
from openmcp.product.models import fingerprint

from .models import CreateRequest


class Database:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
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


class CreatorStore(Database):
    def __init__(self, path):
        super().__init__(path)
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS creator_jobs (
                    id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL,
                    state TEXT NOT NULL, lease TEXT, lease_until REAL,
                    doc TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS creator_calls (
                    execution_id TEXT PRIMARY KEY, job_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, data TEXT
                );
            """)

    def submit(self, request: CreateRequest):
        request_doc = request.model_dump(mode="json")
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT doc FROM creator_jobs WHERE request_key=?", (request.idempotency_key,)
            ).fetchone()
            if existing:
                doc = json.loads(existing["doc"])
                if doc["request"] != request_doc:
                    raise OpenMCPError("creator_conflict", "Job key has different inputs", 409)
                return doc
            job = {
                "id": "created-" + uuid.uuid4().hex,
                "request": request_doc,
                "state": "queued",
                "steps": 0,
                "observations": [],
                "adapter": None,
                "pending_action": None,
                "approved_action": None,
                "action_started": False,
                "message": "Queued for research",
                "events": [],
            }
            db.execute(
                "INSERT INTO creator_jobs(id,request_key,state,doc) VALUES (?,?,?,?)",
                (job["id"], request.idempotency_key, "queued", json.dumps(job)),
            )
            return job

    def get(self, job_id):
        with self.connection() as db:
            row = db.execute("SELECT doc FROM creator_jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise OpenMCPError("creator_not_found", "Creator job not found", 404)
        return json.loads(row["doc"])

    def list(self):
        with self.connection() as db:
            return [
                json.loads(r[0])
                for r in db.execute("SELECT doc FROM creator_jobs ORDER BY rowid DESC LIMIT 100")
            ]

    def claim(self, ttl=660):
        now, lease = time.time(), uuid.uuid4().hex
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM creator_jobs WHERE state='queued' OR "
                "(state='running' AND lease_until < ?) ORDER BY rowid LIMIT 1",
                (now,),
            ).fetchone()
            if row is None:
                return None
            job = json.loads(row["doc"])
            # External actions are never repeated after an uncertain response/crash.
            if job["action_started"]:
                job.update(
                    state="needs_input",
                    message="Browser action outcome uncertain; inspect the account before resuming",
                    approved_action=None,
                    action_started=False,
                )
                db.execute(
                    "UPDATE creator_jobs SET state=?,lease=NULL,lease_until=NULL,doc=? WHERE id=?",
                    (job["state"], json.dumps(job), job["id"]),
                )
                return None
            job["state"] = "running"
            db.execute(
                "UPDATE creator_jobs SET state='running',lease=?,lease_until=?,doc=? WHERE id=?",
                (lease, now + ttl, json.dumps(job), job["id"]),
            )
            return job, lease

    def save(self, job, lease, state="running", message=None):
        job["state"] = state
        if message is not None:
            job["message"] = message
            job["events"].append({"state": state, "message": message, "at": time.time()})
        with self.connection() as db:
            updated = db.execute(
                "UPDATE creator_jobs SET state=?,doc=? WHERE id=? AND lease=? AND lease_until>?",
                (state, json.dumps(job), job["id"], lease, time.time()),
            )
            if updated.rowcount != 1:
                raise RuntimeError("Creator lease lost")

    def resume(self, job_id, *, approve_action=False, regenerate=False, note=""):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT doc FROM creator_jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise OpenMCPError("creator_not_found", "Creator job not found", 404)
            job = json.loads(row[0])
            if job["state"] not in {"needs_input", "failed"}:
                raise OpenMCPError("creator_state", "Only paused or failed jobs can resume", 409)
            if job["pending_action"] and not approve_action:
                raise OpenMCPError(
                    "creator_approval",
                    "Review and explicitly approve the pending browser action",
                    409,
                )
            job.update(
                state="queued",
                approved_action=job["pending_action"] if approve_action else None,
                pending_action=None,
                action_started=False,
            )
            if regenerate:
                job["adapter"] = None
            if note:
                job["operator_note"] = note
            db.execute(
                "UPDATE creator_jobs SET state='queued',lease=NULL,lease_until=NULL,doc=? WHERE id=?",
                (json.dumps(job), job_id),
            )
            return job

    def ready(self, job, lease):
        self.save(
            job, lease, "ready", "Sample validated; ready for explicit account-catalog publication"
        )

    def begin_call(self, job_id, execution_id, payload):
        digest = fingerprint({"job_id": job_id, "payload": payload})
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM creator_calls WHERE execution_id=?", (execution_id,)
            ).fetchone()
            if row:
                if row["fingerprint"] != digest:
                    raise OpenMCPError(
                        "idempotency_conflict", "This key belongs to a different request", 409
                    )
                if row["data"] is None:
                    raise OpenMCPError(
                        "call_pending", "An earlier call needs review; it was not repeated", 409
                    )
                return json.loads(row["data"])
            db.execute(
                "INSERT INTO creator_calls(execution_id,job_id,fingerprint) VALUES(?,?,?)",
                (execution_id, job_id, digest),
            )
        return None

    def finish_call(self, execution_id, result):
        with self.connection() as db:
            db.execute(
                "UPDATE creator_calls SET data=? WHERE execution_id=? AND data IS NULL",
                (json.dumps(result, allow_nan=False), execution_id),
            )
