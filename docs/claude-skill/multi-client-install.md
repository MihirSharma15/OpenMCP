# Install OpenMCP for Codex, Claude Code, and Cursor

OpenMCP now includes a client installer. It registers the local MCP server and installs the same purchasing skill for **Codex, Claude Code, and Cursor**, either for one project or across your projects. The tools remain `balance`, `discover`, and `execute`.

This release connects to the existing local testnet runtime. Keep the OpenMCP checkout and Python environment available, and run the gateway/providers as described in [runtime setup](installation.md). Remote catalog discovery and consumer account onboarding remain roadmap items.

## Quick start

From the OpenMCP checkout, after the runtime has been initialized:

```bash
uv sync
uv run openmcp install all --scope user --dry-run
uv run openmcp install all --scope user
```

`all` installs the three named clients. Choose one if preferred:

```bash
uv run openmcp install codex --scope user
uv run openmcp install claude-code --scope user
uv run openmcp install cursor --scope user
```

Restart the client and enable/trust the OpenMCP server through its normal MCP controls. Installation registers tools and guidance; it does not automatically approve purchases or change client permissions. The tools require an explicit user budget for buying.

For a fresh runtime, first run `uv run openmcp init`, `uv run openmcp fund`, and `uv run openmcp doctor --chain`. Start `uv run openmcp serve` in one terminal and `uv run python -m scripts.run_providers` in another. Then `uv run openmcp check-mcp` verifies the free stdio/balance/discovery path.

Use the skill by name, or ask the agent to use OpenMCP:

```text
Use OpenMCP to investigate FreightFlow's operational health, legal liabilities,
and market share. My total service budget is 15.00 test pathUSD. Label fictional
demo data, attribute sources, and include costs, remaining budget, and both
payment receipt references for each completed purchase.
```

## Install into one project

Project scope is the default. The destination project can be different from the OpenMCP checkout:

```bash
uv run openmcp install all --project /absolute/path/to/my-project
```

The generated launch command uses the current Python executable and an absolute OpenMCP runtime directory. Its launcher changes directory before loading settings, so another project's `.env` or working directory does not accidentally replace the runtime files. Paths with spaces are passed as arguments without a shell.

To select an explicit runtime directory:

```bash
uv run openmcp install codex --scope user --runtime-dir /absolute/path/to/openmcp
```

When run from a source installation, the checkout is detected. With an installed wheel, supply `--runtime-dir` or run from the configured runtime directory. Generated entries are specific to this machine and interpreter; rerun installation if you move the checkout or recreate the environment at another path. Prefer user scope when you do not want machine-specific paths in project files.

## What gets installed

| Client | Project MCP configuration | User MCP configuration | Skill location |
| --- | --- | --- | --- |
| Codex | `.codex/config.toml` | `~/.codex/config.toml` | `.agents/skills/openmcp/SKILL.md` under the project or home |
| Claude Code | `.mcp.json` | `~/.claude.json` | `.claude/skills/openmcp/SKILL.md` under the project or home |
| Cursor | `.cursor/mcp.json` | `~/.cursor/mcp.json` | `.agents/skills/openmcp/SKILL.md` under the project or home |

Codex supports project MCP configuration in trusted projects and user configuration shared by its local clients. The installer sets a 180-second Codex tool timeout to allow for payment settlement. See [OpenAI's MCP documentation](https://developers.openai.com/codex/mcp). The shared `.agents/skills` location is documented for [Codex skills](https://developers.openai.com/codex/skills) and [Cursor skills](https://cursor.com/docs/skills). Claude uses its own skill directory; see [Claude skills](https://code.claude.com/docs/en/skills).

For user installs, `CODEX_HOME` changes the Codex config destination. `CLAUDE_CONFIG_DIR` changes the Claude skill directory and puts its `.claude.json` there, matching [Claude's configuration rules](https://code.claude.com/docs/en/mcp-quickstart#find-your-configuration-on-disk). The shared user skill stays under `~/.agents/skills`.

Codex and Cursor share one installed skill file. Claude receives a copy of the same packaged instructions. The source artifact is [the bundled skill](../../openmcp/client_setup/skills/openmcp/SKILL.md); the checked-in Claude skill is retained for the original repo workflow.

## Existing settings and updates

- Unrelated servers and client settings are preserved. Codex TOML comments/formatting are preserved; JSON is parsed and formatted with two-space indentation.
- Identical installations are a no-op. A different existing `openmcp` server or skill stops installation before any destination is written. After reviewing the conflict, use `--replace` to update only the OpenMCP entry/skill.
- An updated file gets a uniquely named `.openmcp-backup-...` sibling containing its previous contents. Backups have private file permissions because existing client configuration may contain other services' credentials. New files use private permissions too.
- Writes are atomic per file. All destination contents are validated before writing; filesystem failures can still interrupt an installation between files. Fix the reported filesystem issue and rerun to finish.
- Malformed or duplicate-key JSON, malformed TOML, and symlinked destination files are rejected. JSON-with-comments is not rewritten; use the exported fragment to merge it manually.
- Runtime tokens, wallet keys, and signed credentials are not copied into client entries. Wallet funds and client approval settings are unchanged; existing OpenMCP disable flags and tool restrictions survive `--replace`. Replacing a connection clears its old transport/environment overrides so the runtime reads its existing private configuration.

Example for upgrading an existing OpenMCP registration:

```bash
uv run openmcp install all --scope user --replace --dry-run
uv run openmcp install all --scope user --replace
```

The repo already contains a different `.mcp.json` launch entry, so a project-scope install directly into this checkout requires `--replace` to switch to the generated launcher. User-scope setup does not rewrite that project entry; project settings may take precedence when working in this repo.

To disconnect, remove only the `openmcp` server entry from the appropriate client config and remove the installed skill when no other client needs it. Codex and Cursor share that skill. Keep `.openmcp` wallet/payment state for purchase recovery; uninstalling client configuration does not refund or reset purchases. A full-file backup restore should be used only after checking for subsequent unrelated configuration edits.

## Other MCP clients, including VS Code

Print a configuration fragment without changing files:

```bash
uv run openmcp mcp-config --format json
uv run openmcp mcp-config --format toml
uv run openmcp mcp-config --format vscode
```

Merge the JSON `mcpServers.openmcp` entry into a compatible client's MCP configuration, or use the TOML `mcp_servers.openmcp` table. Clients accepting separate command/arguments can use those fields directly. The VS Code export uses `servers.openmcp`, for `.vscode/mcp.json` or a user profile opened through MCP: Open User Configuration. [VS Code MCP configuration](https://code.visualstudio.com/docs/agent-customization/mcp-servers#configure-the-mcpjson-file).

Export is a manual integration path, not automatic installation or certification for every MCP client. For hosts without skill support, the MCP initialization instructions still describe budgets, idempotency, testnet payments, and evidence attribution. Cursor's native config locations and stdio options follow [its MCP documentation](https://cursor.com/docs/mcp).

## Current limits and validation

All installed clients currently share the configured demo agent wallet and global service session. **Use only one purchasing client at a time**, including the browser runner. Multi-process wallet coordination and account-specific authority are still backend/client roadmap work. Installation neither starts services nor performs purchases.

Automated coverage verifies project/user destinations, config merging, conflict handling, backups, repeat installs, dry runs, config-directory overrides, exported formats, and a generated stdio launch from an unrelated directory. The existing payment suite checks that the MCP purchase contract still works. Wheel inspection confirms the launcher, installer, and skill are packaged. This does not constitute a live purchase test inside each editor.

Implementation is contained in [openmcp/client_setup](../../openmcp/client_setup), with CLI registration in [openmcp/cli.py](../../openmcp/cli.py) and regression tests in [tests/test_client_setup.py](../../tests/test_client_setup.py).
