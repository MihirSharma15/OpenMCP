"""Read Creator registrations without making the gateway depend on worker processes."""

import json
import sqlite3

from .config import Provider


def registered_providers(path):
    if not path.exists():
        return {}
    with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='creator_services'").fetchone():
            return {}
        providers = [
            Provider.model_validate(json.loads(row[0]))
            for row in db.execute("SELECT doc FROM creator_services")
        ]
    return {p.id: p for p in providers}
