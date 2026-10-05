"""Account-backed MCP client. Holds an API credential, never a crypto signing key."""

import hashlib
import hmac
import json
import os
import re
import sqlite3
import stat
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .models import OpenMCPError

IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def validate_origin(value: str) -> str:
    parsed = urlsplit(value)
    if (
        not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
        or (
            parsed.scheme != "https"
            and not (
                parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
            )
        )
    ):
        raise ValueError("Use an HTTPS API origin (HTTP is allowed only for local development).")
    # Accessing port also rejects malformed port specifications.
    _ = parsed.port
    return value.rstrip("/")


def private_directory(path: Path) -> None:
    if path.is_symlink():
        raise ValueError("The account state directory must not be a symlink.")
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(path, 0o700)


def write_private(path: Path, text: str) -> None:
    """Replace an owned file atomically; never follow a credential symlink."""
    import tempfile

    if path.is_symlink():
        raise ValueError("Private account files must not be symlinks.")
    descriptor, temporary = tempfile.mkstemp(prefix=".account-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class AccountSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)
    base_url: str | None = Field(default=None, alias="OPENMCP_ACCOUNT_BASE_URL")
    token_file: Path | None = Field(default=None, alias="OPENMCP_AGENT_TOKEN_FILE")
    state: Path = Field(default=Path(".openmcp/account-client"), alias="OPENMCP_ACCOUNT_STATE")
    timeout_seconds: float = Field(default=90, gt=0, le=180)

    def connection(self) -> tuple[str, str]:
        config_path = self.state.expanduser() / "connection.json"
        config = {}
        if config_path.is_symlink():
            raise ValueError("Account connection configuration must not be a symlink.")
        if config_path.exists():
            config = json.loads(config_path.read_text())
            if not isinstance(config, dict):
                raise ValueError("Invalid account connection configuration.")
        url = validate_origin(self.base_url or config.get("base_url", "http://127.0.0.1:8000"))
        path = (self.token_file or self.state.expanduser() / "agent-token").expanduser()
        # Opening without following a symlink prevents accidental reads of unrelated files.
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
                raise ValueError("Agent credential must be a private file (chmod 600).")
            with os.fdopen(descriptor, "r", closefd=False) as stream:
                token = stream.read(4097).strip()
        finally:
            os.close(descriptor)
        if not token or len(token) > 4096 or any(c.isspace() for c in token):
            raise ValueError("Invalid agent credential file; run openmcp connect.")
        if config and not self.token_file:
            digest = config.get("token_sha256", "")
            if not isinstance(digest, str) or not hmac.compare_digest(
                digest, hashlib.sha256(token.encode()).hexdigest()
            ):
                raise ValueError("Account connection update was interrupted; run openmcp connect.")
            if self.base_url and url != config.get("base_url"):
                raise ValueError("Run openmcp connect before changing the credential's API origin.")
        return url, token


def configure_account(settings: AccountSettings, base_url: str, token: str) -> None:
    """Called by the hidden CLI prompt; does not contact the API or make purchases."""
    origin = validate_origin(base_url)
    token = token.strip()
    if not token or len(token) > 4096 or any(c.isspace() for c in token):
        raise ValueError("Provide the agent credential issued by your dashboard.")
    directory = settings.state.expanduser()
    private_directory(directory)
    target = (settings.token_file or directory / "agent-token").expanduser()
    if target.parent != directory:
        # An explicitly configured token location may have its own private parent.
        # Do not change permissions on an arbitrary existing parent directory.
        if not target.parent.is_dir():
            raise ValueError("Create the configured credential directory first.")
    write_private(target, token + "\n")
    write_private(
        directory / "connection.json",
        json.dumps({"base_url": origin, "token_sha256": hashlib.sha256(token.encode()).hexdigest()})
        + "\n",
    )


class RequestJournal:
    """Remember the original body before a request leaves the machine."""

    def __init__(self, directory: Path, scope: str):
        private_directory(directory)
        self.path, self.scope = directory / "requests.sqlite3", scope
        if self.path.is_symlink():
            raise ValueError("Account request journal must not be a symlink.")
        self.path.touch(mode=0o600, exist_ok=True)
        os.chmod(self.path, 0o600)
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS requests ("
                "scope TEXT NOT NULL, key TEXT NOT NULL, body TEXT NOT NULL, "
                "execution_id TEXT, PRIMARY KEY(scope, key))"
            )

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def prepare(self, key: str, body: dict) -> None:
        encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT body FROM requests WHERE scope=? AND key=?", (self.scope, key)
            ).fetchone()
            if row and row[0] != encoded:
                raise OpenMCPError(
                    "idempotency_conflict", "This key belongs to different purchase arguments.", 409
                )
            db.execute(
                "INSERT OR IGNORE INTO requests(scope,key,body) VALUES (?,?,?)",
                (self.scope, key, encoded),
            )

    def save_execution(self, key: str, execution_id: str) -> None:
        with self.connect() as db:
            row = db.execute(
                "SELECT execution_id FROM requests WHERE scope=? AND key=?", (self.scope, key)
            ).fetchone()
            if row and row[0] is not None and row[0] != execution_id:
                raise OpenMCPError(
                    "invalid_response", "The gateway changed the execution for this key.", 502
                )
            db.execute(
                "UPDATE requests SET execution_id=? WHERE scope=? AND key=?",
                (execution_id, self.scope, key),
            )

    def execution_id(self, key: str) -> str | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT execution_id FROM requests WHERE scope=? AND key=?", (self.scope, key)
            ).fetchone()
        return row[0] if row else None


class AccountClient:
    def __init__(self, settings: AccountSettings | None = None, *, transport=None):
        self.settings = settings or AccountSettings()
        url, token = self.settings.connection()
        scope = hashlib.sha256((url + "\0" + token).encode()).hexdigest()
        self.journal = RequestJournal(self.settings.state.expanduser(), scope)
        self.http = httpx.AsyncClient(
            base_url=url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=self.settings.timeout_seconds,
            follow_redirects=False,
            transport=transport,
        )

    async def close(self):
        await self.http.aclose()

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        async with self.http.stream(method, path, **kwargs) as response:
            content = bytearray()
            async for part in response.aiter_bytes():
                content.extend(part)
                if len(content) > 2_000_000:
                    raise OpenMCPError(
                        "invalid_response", "Gateway response too large; keep the same key.", 502
                    )
            try:
                result = json.loads(content)
            except (ValueError, UnicodeError):
                result = None
            if response.is_error:
                error = result.get("error") if isinstance(result, dict) else None
                if isinstance(error, dict) and isinstance(error.get("code"), str):
                    raise OpenMCPError(
                        error["code"],
                        str(error.get("message", "Account request failed.")),
                        response.status_code,
                        error.get("retryable") is True,
                    )
                raise OpenMCPError(
                    "http_error",
                    f"Account gateway returned HTTP {response.status_code}.",
                    response.status_code,
                    response.status_code >= 500,
                )
            if not response.is_success or not isinstance(result, dict):
                raise OpenMCPError(
                    "invalid_response", "Invalid gateway response; keep the same key.", 502, True
                )
            return result

    async def balance(self) -> dict:
        return await self._request("GET", "/v1/wallet")

    async def discover(self, query: str, budget_cents: int | None = None) -> dict:
        if not isinstance(query, str) or not 1 <= len(query) <= 4000:
            raise OpenMCPError("invalid_request", "Provide a query of 1 to 4000 characters.", 422)
        body: dict = {"query": query}
        if budget_cents is not None:
            if type(budget_cents) is not int or budget_cents < 0:
                raise OpenMCPError(
                    "invalid_amount", "Budget must be nonnegative integer cents.", 422
                )
            body["budget_cents"] = budget_cents
        return await self._request("POST", "/v1/discover", json=body)

    async def execute(
        self, endpoint_id: str, payload: dict, max_price_cents: int, idempotency_key: str
    ) -> dict:
        if not IDENTIFIER.fullmatch(endpoint_id) or not IDENTIFIER.fullmatch(idempotency_key):
            raise OpenMCPError("invalid_request", "Invalid endpoint or idempotency key.", 422)
        if len(idempotency_key) < 8:
            raise OpenMCPError(
                "invalid_request", "Idempotency key needs at least 8 characters.", 422
            )
        if (
            type(max_price_cents) is not int
            or not 1 <= max_price_cents <= 1_000_000
            or not isinstance(payload, dict)
        ):
            raise OpenMCPError(
                "invalid_request", "Provide a payload and a price ceiling of 1–1,000,000 cents.", 422
            )
        body = {"endpoint_id": endpoint_id, "payload": payload, "max_price_cents": max_price_cents}
        self.journal.prepare(idempotency_key, body)
        result = await self._request(
            "POST", "/v1/execute", json=body, headers={"Idempotency-Key": idempotency_key}
        )
        execution_id = result.get("execution_id")
        if not isinstance(execution_id, str) or not IDENTIFIER.fullmatch(execution_id):
            raise OpenMCPError(
                "invalid_response",
                "Gateway omitted the execution ID; keep the same key.",
                502,
                True,
            )
        self.journal.save_execution(idempotency_key, execution_id)
        return result

    async def execution_status(
        self, execution_id: str | None = None, idempotency_key: str | None = None
    ) -> dict:
        if (execution_id is None) == (idempotency_key is None):
            raise OpenMCPError("invalid_request", "Provide an execution ID or a saved key.", 422)
        if idempotency_key is not None:
            if not IDENTIFIER.fullmatch(idempotency_key):
                raise OpenMCPError("invalid_request", "Invalid idempotency key.", 422)
            execution_id = self.journal.execution_id(idempotency_key)
            if execution_id is None:
                return {
                    "status": "submission_unknown",
                    "message": "Retry execute with the IDENTICAL arguments and key to recover.",
                }
        if not isinstance(execution_id, str) or not IDENTIFIER.fullmatch(execution_id):
            raise OpenMCPError("invalid_request", "Invalid execution ID.", 422)
        # Construct the path locally, never follow a status_url supplied by a service.
        return await self._request("GET", f"/v1/executions/{execution_id}")
