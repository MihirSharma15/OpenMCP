"""Explicit provider publication. PostgreSQL is the runtime catalog; imports never prune it."""

import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from .database import DatabaseManager
from .integrations.registry import BUILTINS
from .integrations.registry import provider as builtin_provider
from .product.config import ProductSettings, Provider
from .product.models import ProductError
from .product.store import Store


def load_catalog(path):
    """Read an explicit import file. Missing, malformed and duplicate entries are errors."""
    items = json.loads(Path(path).read_text())
    if not isinstance(items, list):
        raise ValueError("Catalog must be a JSON array of providers")
    providers = [Provider.model_validate(item) for item in items]
    ids = [p.provider_id for p in providers]
    endpoints = [q.endpoint_id for p in providers for q in p.queries]
    if len(ids) != len(set(ids)) or len(endpoints) != len(set(endpoints)):
        raise ValueError("Provider and endpoint IDs must be unique")
    return providers


def publish(store, definitions, mode, *, enable=False):
    """Shared entry point for built-ins, imports, and Creator. Never calls a vendor."""
    providers = [Provider.model_validate(p).model_copy(deep=True) for p in definitions]
    ids = [p.provider_id for p in providers]
    endpoints = [q.endpoint_id for p in providers for q in p.queries]
    if len(ids) != len(set(ids)) or len(endpoints) != len(set(endpoints)):
        raise ValueError("Provider and endpoint IDs must be unique")
    for provider in providers:
        for query in provider.queries:
            if query.mode != mode:
                raise ValueError("Provider mode must match the account deployment")
            query.enabled = enable
    # SQL ownership checks prevent one provider from taking another's endpoint IDs.
    store.sync_catalog(providers, prune=False)
    return providers


def open_store(settings):
    settings.validate_database()
    store = Store(DatabaseManager.from_settings(settings))
    try:
        store.database.check_schema_version()
        store.bind_runtime(settings)
    except Exception:
        store.close()
        raise
    return store


def main(argv=None):
    load_dotenv(".env")
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list", help="List registered services")
    listing.add_argument("--builtins", action="store_true", help="List available built-in adapters")
    validate = commands.add_parser(
        "validate", help="Validate a built-in definition and credential setup; no vendor call"
    )
    validate.add_argument("provider")
    register = commands.add_parser(
        "register", help="Publish a built-in provider, disabled by default"
    )
    register.add_argument("provider")
    register.add_argument("--enable", action="store_true")
    importing = commands.add_parser(
        "import", help="Publish a JSON export without deleting other providers"
    )
    importing.add_argument("path", type=Path)
    importing.add_argument("--enable", action="store_true")
    exporting = commands.add_parser("export", help="Export the published database catalog")
    exporting.add_argument("--output", type=Path, required=True)
    for action in ("enable", "disable"):
        command = commands.add_parser(
            action, help=f"{action.title()} new purchases for an endpoint"
        )
        command.add_argument("endpoint_id")
    check = commands.add_parser(
        "check", help="Run a provider-specific diagnostic; some checks are billable"
    )
    check.add_argument("provider", choices=("tavily", "dataforseo"))
    check.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.command == "list" and args.builtins:
        print(json.dumps(list(BUILTINS)))
        return
    if args.command == "check":
        from importlib import import_module

        import_module(f"openmcp.integrations.{args.provider}.diagnostics").main(
            ["check", *args.arguments]
        )
        return
    settings = ProductSettings()
    try:
        if args.command == "validate":
            definition = Provider.model_validate(builtin_provider(args.provider, settings.mode))
            configured = bool(definition.secret_ref and os.environ.get(definition.secret_ref))
            print(
                json.dumps(
                    {
                        "provider_id": definition.provider_id,
                        "services": len(definition.queries),
                        "credential_configured": configured,
                        "vendor_called": False,
                    }
                )
            )
            if not configured:
                parser.exit(1, "Configure the provider credential in the worker environment.\n")
            return
        store = open_store(settings)
        try:
            if args.command in {"register", "import"}:
                definitions = (
                    [builtin_provider(args.provider, settings.mode)]
                    if args.command == "register"
                    else load_catalog(args.path)
                )
                published = publish(store, definitions, settings.mode, enable=args.enable)
                print(
                    json.dumps(
                        {"providers": [p.provider_id for p in published], "enabled": args.enable}
                    )
                )
            elif args.command in {"enable", "disable"}:
                store.set_service_enabled(args.endpoint_id, args.command == "enable", settings.mode)
                print(
                    json.dumps(
                        {"endpoint_id": args.endpoint_id, "enabled": args.command == "enable"}
                    )
                )
            else:
                catalog = store.catalog()
                if args.command == "export":
                    if args.output.is_symlink():
                        raise ValueError("Catalog must not be a symlink")
                    args.output.write_text(json.dumps(catalog, indent=2) + "\n")
                else:
                    print(json.dumps(catalog, indent=2))
        finally:
            store.close()
    except (ProductError, ValueError, OSError) as exc:
        # Do not echo file contents, DSNs or provider credentials.
        parser.exit(
            1,
            f"Provider setup failed ({type(exc).__name__}); check definition, mode and database configuration.\n",
        )


if __name__ == "__main__":
    main()
