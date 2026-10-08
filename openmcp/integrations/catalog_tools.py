"""Shared operator-only catalog setup. Provider factories contain no secret values."""

import json
import os
from pathlib import Path


def write_provider(path, definition):
    from openmcp.product.config import ProductSettings, Provider

    path = Path(path)
    if path.is_symlink():
        raise ValueError("Catalog must not be a symlink")
    existing = ProductSettings(_env_file=None, catalog_path=path).catalog() if path.exists() else []
    new = Provider.model_validate(definition)
    entries = [p for p in existing if p.provider_id != new.provider_id] + [new]
    ids = [q.endpoint_id for p in entries for q in p.queries]
    if len(ids) != len(set(ids)):
        raise ValueError("An existing provider owns one of these endpoint IDs")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("x") as output:
        output.write(json.dumps([p.model_dump(mode="json") for p in entries], indent=2) + "\n")
    os.replace(temporary, path)


def register_provider(factory):
    from openmcp.database import DatabaseManager
    from openmcp.product.config import ProductSettings, Provider
    from openmcp.product.store import Store

    settings = ProductSettings()
    if settings.catalog_path is not None:
        raise ValueError("Merge into the configured catalog file instead of database registration")
    settings.validate_database()
    new = Provider.model_validate(factory(settings.mode))
    store = Store(DatabaseManager.from_settings(settings))
    try:
        store.database.check_schema_version()
        store.sync_catalog([new], prune=False)
        print(f"Registered {new.name}; other database providers preserved.")
    finally:
        store.close()
