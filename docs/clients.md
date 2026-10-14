# MCP client setup

Sign into the account dashboard, create an agent with a lifetime allowance, and
issue its credential. Save it through the hidden prompt:

```sh
uv run openmcp connect --base-url https://YOUR_ACCOUNT_API
uv run openmcp install all --scope user --dry-run
uv run openmcp install all --scope user
uv run openmcp check-mcp
```

Use `codex`, `claude-code`, or `cursor` instead of `all`. Project scope is the
default; use `--project /path/to/project` to choose it explicitly. The installer
preserves unrelated client settings, reports conflicts, and creates private
backups when `--replace` is explicitly used. Restart the client after installation.

Other MCP clients can use `openmcp mcp-config --format json`, `toml`, or `vscode`.
The generated launcher uses the OpenMCP runtime directory regardless of the
client's working directory. Keep that checkout/environment available.

The client exposes `balance`, `discover`, `execute`, and `execution_status`.
Connection checks and discovery are free. Agent credentials cannot add funds,
create allowances or authorize refunds. A task budget is an additional instruction
to the agent; the server enforces the owner's allowance and available account funds.
Retries must reuse identical purchase arguments and the original idempotency key.

The client stores its private credential and request journal under its account
state directory. No crypto key, vendor key or human session is required by the
client. Do not embed credentials into client configuration examples or prompts.
