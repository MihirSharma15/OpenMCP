"""Merge client configuration without reading or copying wallet/connection secrets."""

import json
import os
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from uuid import uuid4

import tomlkit

CLIENTS = ("codex", "claude-code", "cursor")
# Replacing a connection must preserve host settings such as enabled/disabled,
# tool allowlists, and per-tool approval rules on that same server.
TRANSPORT_FIELDS = {
    "type",
    "command",
    "args",
    "cwd",
    "url",
    "env",
    "env_vars",
    "envFile",
    "headers",
    "http_headers",
    "http_headers_helper",
    "bearer_token_env_var",
    "env_http_headers",
    "oauth",
    "auth",
    "experimental_environment",
}


class InstallError(Exception):
    """An actionable configuration error whose message contains no file contents."""


@dataclass(frozen=True)
class Change:
    path: Path
    before: str | None
    after: str

    @property
    def action(self):
        if self.before == self.after:
            return "unchanged"
        return "create" if self.before is None else "update"


def skill_text():
    return files("openmcp.client_setup").joinpath("skills/openmcp/SKILL.md").read_text("utf-8")


def runtime_directory(value: Path | None = None):
    if value is not None:
        root = value.expanduser().resolve()
    else:
        checkout = Path(__file__).resolve().parents[2]
        root = checkout if (checkout / "catalog/providers.json").is_file() else Path.cwd()
        root = root.resolve()
    if not root.is_dir():
        raise InstallError(f"Runtime directory does not exist: {root}")
    return root


def server_entry(runtime_dir: Path):
    # Do not resolve this symlink: resolving venv/bin/python can discard the venv.
    return {
        "command": str(Path(sys.executable).absolute()),
        "args": ["-m", "openmcp.client_setup.launch", "--runtime-dir", str(runtime_dir)],
    }


def export_config(runtime_dir: Path, format: str):
    entry = server_entry(runtime_dir)
    if format == "toml":
        return tomlkit.dumps({"mcp_servers": {"openmcp": {**entry, "tool_timeout_sec": 180}}})
    if format == "vscode":
        return json.dumps({"servers": {"openmcp": {"type": "stdio", **entry}}}, indent=2) + "\n"
    if format == "json":
        return json.dumps({"mcpServers": {"openmcp": {"type": "stdio", **entry}}}, indent=2) + "\n"
    raise InstallError(f"Unsupported config format: {format}")


def _read(path):
    if path.is_symlink():
        raise InstallError(f"Refusing to replace a symlink: {path}")
    try:
        return path.read_text("utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError) as exc:
        raise InstallError(f"Cannot read configuration: {path}") from exc


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate key")
        result[key] = value
    return result


def _config_change(path, entry, *, toml=False, replace=False):
    original = _read(path)
    try:
        document = (
            tomlkit.parse(original or "")
            if toml
            else json.loads(original or "{}", object_pairs_hook=_json_object)
        )
    except (ValueError, tomlkit.exceptions.ParseError) as exc:
        raise InstallError(
            f"Invalid {'TOML' if toml else 'JSON'} in {path}; file left intact."
        ) from exc
    key = "mcp_servers" if toml else "mcpServers"
    if not isinstance(document, Mapping) or (
        key in document and not isinstance(document[key], Mapping)
    ):
        raise InstallError(f"Expected an object/table for {key} in {path}.")
    existing = document.get(key, {}).get("openmcp")
    replacement = (
        {k: v for k, v in existing.items() if k not in TRANSPORT_FIELDS}
        if isinstance(existing, Mapping)
        else {}
    )
    replacement.update(entry)
    if "openmcp" in document.get(key, {}) and existing != replacement and not replace:
        raise InstallError(
            f"A different openmcp server exists in {path}; review it and rerun with --replace."
        )
    if existing == replacement:
        return Change(path, original, original)
    if key not in document:
        document[key] = tomlkit.table() if toml else {}
    document[key]["openmcp"] = replacement
    content = tomlkit.dumps(document) if toml else json.dumps(document, indent=2) + "\n"
    return Change(path, original, content)


def _skill_change(path, *, replace):
    original, content = _read(path), skill_text()
    if original is not None and original != content and not replace:
        raise InstallError(
            f"A different openmcp skill exists in {path}; review it and rerun with --replace."
        )
    return Change(path, original, content)


def plan_install(client, scope, project, runtime_dir, *, replace=False, home=None, environ=None):
    """Preflight every destination before changing any configuration."""
    if client not in (*CLIENTS, "all") or scope not in ("project", "user"):
        raise InstallError("Choose codex, claude-code, cursor, or all and project/user scope.")
    home = (home or Path.home()).expanduser().resolve()
    environ = os.environ if environ is None else environ
    project = project.expanduser().resolve()
    if scope == "project" and not project.is_dir():
        raise InstallError(f"Project directory does not exist: {project}")
    root = project if scope == "project" else home
    selected = CLIENTS if client == "all" else (client,)
    entry = server_entry(runtime_dir)
    changes = {}
    for name in selected:
        if name == "codex":
            codex_dir = root / ".codex"
            if scope == "user" and environ.get("CODEX_HOME"):
                codex_dir = Path(environ["CODEX_HOME"]).expanduser().resolve()
            config, skill = codex_dir / "config.toml", root / ".agents/skills/openmcp/SKILL.md"
        elif name == "claude-code":
            claude_dir = root / ".claude"
            config = root / ".mcp.json" if scope == "project" else home / ".claude.json"
            if scope == "user" and environ.get("CLAUDE_CONFIG_DIR"):
                claude_dir = Path(environ["CLAUDE_CONFIG_DIR"]).expanduser().resolve()
                config = claude_dir / ".claude.json"
            skill = claude_dir / "skills/openmcp/SKILL.md"
        else:
            config = root / ".cursor/mcp.json"
            # Codex and Cursor both discover this standard location. Installing
            # all clients produces one shared skill rather than duplicate copies.
            skill = root / ".agents/skills/openmcp/SKILL.md"
        changes[config] = _config_change(
            config,
            {**entry, "tool_timeout_sec": 180} if name == "codex" else {"type": "stdio", **entry},
            toml=name == "codex",
            replace=replace,
        )
        changes[skill] = _skill_change(skill, replace=replace)
    return list(changes.values())


def _atomic_write(path, content, mode):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".openmcp-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            os.fchmod(file.fileno(), mode)
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def apply_plan(changes):
    # Refuse stale plans before any writes, including a destination replaced by
    # a symlink. Backups are private because other server entries may hold secrets.
    for change in changes:
        if _read(change.path) != change.before:
            raise InstallError(f"Configuration changed during installation: {change.path}; retry.")
    results = []
    for change in changes:
        backup = None
        if change.action != "unchanged":
            mode = 0o600
            if change.before is not None:
                mode = change.path.stat().st_mode & 0o777
                backup = change.path.with_name(f"{change.path.name}.openmcp-backup-{uuid4().hex}")
                _atomic_write(backup, change.before, 0o600)
            _atomic_write(change.path, change.after, mode)
        results.append(
            {
                "path": str(change.path),
                "action": change.action,
                "backup": str(backup) if backup else None,
            }
        )
    return results


def register_commands(commands):
    parser = commands.add_parser("install", help="Install MCP tools and skill for an AI client")
    parser.add_argument("client", choices=(*CLIENTS, "all"))
    parser.add_argument("--scope", choices=("project", "user"), default="project")
    parser.add_argument("--project", type=Path, default=Path.cwd(), help="Destination project")
    parser.add_argument("--runtime-dir", type=Path, help="OpenMCP checkout/configuration directory")
    parser.add_argument("--dry-run", action="store_true", help="List changes without writing files")
    parser.add_argument(
        "--replace", action="store_true", help="Replace conflicting OpenMCP entries"
    )
    export = commands.add_parser(
        "mcp-config", help="Print a config fragment for another MCP client"
    )
    export.add_argument("--format", choices=("json", "toml", "vscode"), default="json")
    export.add_argument("--runtime-dir", type=Path)


def run(args):
    root = runtime_directory(args.runtime_dir)
    if args.command == "mcp-config":
        print(export_config(root, args.format), end="")
        return
    changes = plan_install(args.client, args.scope, args.project, root, replace=args.replace)
    results = (
        [{"path": str(c.path), "action": c.action} for c in changes]
        if args.dry_run
        else apply_plan(changes)
    )
    print(
        json.dumps({"dry_run": args.dry_run, "runtime_dir": str(root), "files": results}, indent=2)
    )
    if args.dry_run:
        print("No files changed. Rerun without --dry-run to apply this configuration.")
        return
    print(
        "Restart your client and enable/trust the OpenMCP server to load balance, discover, execute."
    )
    print(
        "The local gateway/provider stack must be running; run openmcp check-mcp from the runtime directory."
    )
    print("This setup shares one demo agent wallet. Use only one purchasing client at a time.")
