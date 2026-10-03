"""Encrypted job credentials, separate from model context and generated artifacts."""

import json
import os

from cryptography.fernet import Fernet

from .models import origin


class Vault:
    def __init__(self, state_dir):
        self.directory = state_dir / "vault"
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.directory, 0o700)
        path = self.directory / "key"
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "wb") as file:
                file.write(Fernet.generate_key())
        self.cipher = Fernet(path.read_bytes())

    def _path(self, job_id):
        import re

        if not re.fullmatch(r"created-[a-f0-9]{32}", job_id):
            raise ValueError("Invalid job ID")
        return self.directory / f"{job_id}.enc"

    def load(self, job_id):
        path = self._path(job_id)
        return json.loads(self.cipher.decrypt(path.read_bytes())) if path.exists() else {}

    def save(self, job_id, values):
        import tempfile

        path = self._path(job_id)
        fd, temporary = tempfile.mkstemp(dir=self.directory)
        with os.fdopen(fd, "wb") as file:
            file.write(self.cipher.encrypt(json.dumps(values).encode()))
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)

    def put(self, job_id, name, value, scope):
        values = self.load(job_id)
        values.setdefault("secrets", {})[name] = {"value": value, "origin": origin(scope)}
        self.save(job_id, values)

    def secret(self, job_id, name, scope):
        entry = self.load(job_id).get("secrets", {}).get(name)
        if not entry or entry["origin"] != origin(scope):
            raise ValueError("Missing credential scoped to this origin")
        return entry["value"]

    def redact(self, job_id, text):
        for entry in self.load(job_id).get("secrets", {}).values():
            if entry["value"]:
                text = text.replace(entry["value"], "[secret]")
        return text
