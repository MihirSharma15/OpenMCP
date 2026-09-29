import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from openmcp.client_setup.installer import (
    InstallError,
    apply_plan,
    export_config,
    plan_install,
    server_entry,
    skill_text,
)
from openmcp.wallets import create_wallets

ROOT = Path(__file__).resolve().parents[1]


def install_plan(tmp_path, client="all", scope="project", **kwargs):
    project = tmp_path / "project with spaces"
    project.mkdir(exist_ok=True)
    return plan_install(client, scope, project, ROOT, home=tmp_path / "home", environ={}, **kwargs)


@pytest.mark.parametrize("scope", ["project", "user"])
def test_all_clients_install_and_reinstall_without_changes(tmp_path, scope):
    plan = install_plan(tmp_path, scope=scope)
    assert len(plan) == 5  # Three MCP configs and two skill locations.
    result = apply_plan(plan)
    assert all(item["action"] == "create" and item["backup"] is None for item in result)
    root = tmp_path / ("project with spaces" if scope == "project" else "home")
    codex = tomllib.loads((root / ".codex/config.toml").read_text())
    claude = json.loads(
        (root / (".mcp.json" if scope == "project" else ".claude.json")).read_text()
    )
    cursor = json.loads((root / ".cursor/mcp.json").read_text())
    for entry in (
        codex["mcp_servers"]["openmcp"],
        claude["mcpServers"]["openmcp"],
        cursor["mcpServers"]["openmcp"],
    ):
        assert entry["args"][-1] == str(ROOT)
        assert entry["command"] == sys.executable
        assert "env" not in entry
    assert (root / ".agents/skills/openmcp/SKILL.md").read_text() == skill_text()
    assert (root / ".claude/skills/openmcp/SKILL.md").read_text() == skill_text()
    again = apply_plan(install_plan(tmp_path, scope=scope))
    assert all(item["action"] == "unchanged" and item["backup"] is None for item in again)


def test_merge_preserves_other_servers_settings_comments_and_private_backups(tmp_path):
    plan = install_plan(tmp_path)
    project = tmp_path / "project with spaces"
    codex = project / ".codex/config.toml"
    codex.parent.mkdir()
    toml = '# Keep this comment\nmodel = "existing"\n[mcp_servers.other]\ncommand = "other-tool"\n'
    codex.write_text(toml)
    claude = project / ".mcp.json"
    original = '{"mcpServers":{"other":{"command":"other-tool"}},"otherSetting":42}\n'
    claude.write_text(original)
    plan = install_plan(tmp_path)
    results = apply_plan(plan)
    assert "# Keep this comment" in codex.read_text()
    assert tomllib.loads(codex.read_text())["model"] == "existing"
    assert tomllib.loads(codex.read_text())["mcp_servers"]["other"]["command"] == "other-tool"
    assert json.loads(claude.read_text())["otherSetting"] == 42
    assert json.loads(claude.read_text())["mcpServers"]["other"]["command"] == "other-tool"
    backups = [Path(item["backup"]) for item in results if item["backup"]]
    assert {path.read_text() for path in backups} == {toml, original}
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in backups)


@pytest.mark.parametrize("kind", ["server", "skill", "invalid", "duplicate", "wrong-shape"])
def test_conflicts_abort_the_whole_plan_before_writes(tmp_path, kind):
    install_plan(tmp_path)
    project = tmp_path / "project with spaces"
    target = project / ".cursor/mcp.json"
    if kind == "skill":
        target = project / ".claude/skills/openmcp/SKILL.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    text = {
        "server": '{"mcpServers":{"openmcp":{"command":"custom"}}}',
        "skill": "User customized instructions",
        "invalid": "{not-json secret-value",
        "duplicate": '{"mcpServers":{},"mcpServers":{}}',
        "wrong-shape": '{"mcpServers":[]}',
    }[kind]
    target.write_text(text)
    with pytest.raises(InstallError) as error:
        install_plan(tmp_path)
    assert "secret-value" not in str(error.value)
    assert target.read_text() == text
    assert not (project / ".codex/config.toml").exists()
    if kind in ("server", "skill"):
        apply_plan(install_plan(tmp_path, replace=True))
        assert target.read_text() != text


def test_detects_edit_after_planning(tmp_path):
    plan = install_plan(tmp_path)
    target = plan[-1].path
    target.parent.mkdir(parents=True)
    target.write_text("changed while planning")
    with pytest.raises(InstallError, match="changed during"):
        apply_plan(plan)
    assert not plan[0].path.exists()


def test_replace_preserves_existing_tool_restrictions(tmp_path):
    install_plan(tmp_path)
    path = tmp_path / "project with spaces/.codex/config.toml"
    path.parent.mkdir()
    path.write_text(
        '[mcp_servers.openmcp]\ncommand = "old-tool"\nenabled = false\n'
        'disabled_tools = ["execute"]\ndefault_tools_approval_mode = "prompt"\n'
        '[mcp_servers.openmcp.tools.execute]\napproval_mode = "approve"\n'
    )
    apply_plan(install_plan(tmp_path, replace=True))
    entry = tomllib.loads(path.read_text())["mcp_servers"]["openmcp"]
    assert entry["command"] == sys.executable
    assert entry["enabled"] is False
    assert entry["disabled_tools"] == ["execute"]
    assert entry["default_tools_approval_mode"] == "prompt"
    assert entry["tools"]["execute"]["approval_mode"] == "approve"
    assert all(c.action == "unchanged" for c in install_plan(tmp_path))


def test_refuses_symlink_destination(tmp_path):
    install_plan(tmp_path)
    real = tmp_path / "other-config"
    real.write_text("{}")
    (tmp_path / "project with spaces/.mcp.json").symlink_to(real)
    with pytest.raises(InstallError, match="symlink"):
        install_plan(tmp_path, replace=True)
    assert real.read_text() == "{}"


def test_honors_client_config_directory_overrides(tmp_path):
    plan = plan_install(
        "all",
        "user",
        tmp_path,
        ROOT,
        home=tmp_path / "home",
        environ={
            "CODEX_HOME": str(tmp_path / "custom-codex"),
            "CLAUDE_CONFIG_DIR": str(tmp_path / "custom-claude"),
        },
    )
    destinations = {change.path for change in plan}
    assert tmp_path / "custom-codex/config.toml" in destinations
    assert tmp_path / "custom-claude/.claude.json" in destinations
    assert tmp_path / "custom-claude/skills/openmcp/SKILL.md" in destinations
    assert tmp_path / "home/.agents/skills/openmcp/SKILL.md" in destinations


@pytest.mark.parametrize("format", ["json", "toml", "vscode"])
def test_exports_preserve_paths_without_shell_interpolation(tmp_path, format):
    runtime = tmp_path / 'runtime spaces $dollar `literal` "quote"'
    text = export_config(runtime, format)
    data = tomllib.loads(text) if format == "toml" else json.loads(text)
    group = {"toml": "mcp_servers", "json": "mcpServers", "vscode": "servers"}[format]
    entry = data[group]["openmcp"]
    assert entry["args"][-1] == str(runtime)
    assert Path(entry["command"]).is_absolute()


def test_cli_dry_run_needs_no_wallet_and_writes_no_files(tmp_path):
    project = tmp_path / "empty-project"
    project.mkdir()
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "openmcp.cli",
            "install",
            "all",
            "--project",
            str(project),
            "--runtime-dir",
            str(tmp_path),
            "--dry-run",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert '"dry_run": true' in result.stdout
    assert list(project.iterdir()) == []
    assert not (tmp_path / ".openmcp").exists()


async def test_generated_launch_connects_over_stdio_from_an_unrelated_project(tmp_path):
    runtime = tmp_path / "runtime with spaces"
    runtime.mkdir()
    create_wallets(runtime / ".openmcp/wallets")
    (runtime / "catalog").mkdir()
    (runtime / "catalog/providers.json").write_text((ROOT / "catalog/providers.json").read_text())
    (runtime / ".env").write_text("OPENMCP_API_TOKEN=isolated-test-token\n")
    project = tmp_path / "unrelated-project"
    project.mkdir()
    entry = server_entry(runtime)
    params = StdioServerParameters(
        command=entry["command"],
        args=entry["args"],
        cwd=str(project),
        env={"PYTHONDONTWRITEBYTECODE": "1"},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            initialized = await session.initialize()
            assert "explicit total user budget" in initialized.instructions
            listed = await session.list_tools()
            assert {tool.name for tool in listed.tools} == {"balance", "discover", "execute"}
    assert (runtime / ".openmcp/agent-payments.sqlite3").exists()
    assert not (project / ".openmcp").exists()


def test_python_executable_keeps_virtual_environment_symlink(tmp_path, monkeypatch):
    executable = tmp_path / "venv/bin/python"
    executable.parent.mkdir(parents=True)
    executable.symlink_to(sys.executable)
    monkeypatch.setattr(sys, "executable", str(executable))
    assert server_entry(ROOT)["command"] == str(executable)
