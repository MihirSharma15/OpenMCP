# Install and use the current Claude skill

This is the repository-based **Claude Code** runtime setup. For the implemented Codex, Claude Code, and Cursor installer, use [multi-client installation](multi-client-install.md). The application uses real transactions involving valueless Tempo testnet pathUSD. A hosted gateway and consumer account flow remain roadmap work.

## Prerequisites

- A checkout of this repository and a terminal at its root.
- Python 3.11+, `uv`, and Claude Code available on the command path.
- Network access for dependencies, the Tempo testnet RPC, and initial faucet funding.
- Available local ports `8000`, `9001`, and `9101`–`9103`.

Next.js and the browser demo are optional for using Claude. Run one gateway worker and one active process that purchases with the agent wallet. In particular, avoid simultaneous purchases from Claude and the browser runner with the shared demo wallet.

## 1. Initialize the demo

From the repository root:

```bash
uv sync
uv run openmcp init
uv run openmcp fund
uv run openmcp doctor --chain
```

`init` creates `.env` connection/challenge secrets and five named wallets: `agent`, `openmcp`, `operations`, `legal`, and `market`. Repeating it preserves existing wallet keys. `fund` requests faucet tokens for the two paying wallets. `doctor --chain` checks the network and reports public wallet information and balances.

The default service allowance is `1500` cents, or `15.00` test pathUSD. Wallet funds and service allowance are separate. Keep `.env` and `.openmcp/` private, including payment journals containing signed credentials. Claude's tool handles the agent key; no key needs to be pasted into a prompt.

## 2. Start the services

Terminal A, at the repository root:

```bash
uv run python -m scripts.run_providers
```

This starts the paid provider wrapper on `9001` and the three fictional upstream APIs on `9101`–`9103`.

Terminal B, at the repository root:

```bash
uv run openmcp serve
```

This starts the gateway at `http://127.0.0.1:8000`. Its REST documentation is at `http://127.0.0.1:8000/docs`.

## 3. Connect Claude Code

Start `claude` from the repository root. Enable the checked-in project MCP server when Claude Code requests project-server approval, and inspect its connection using `/mcp`. Project `.mcp.json` configuration and stdio registration are described in [the official MCP documentation](https://code.claude.com/docs/en/mcp).

The checked-in [configuration](../../.mcp.json) is:

```json
{
  "mcpServers": {
    "openmcp": {
      "command": "uv",
      "args": ["run", "--directory", "${CLAUDE_PROJECT_DIR:-.}", "openmcp", "mcp"]
    }
  }
}
```

The separate [skill file](../../.claude/skills/openmcp/SKILL.md) supplies `/openmcp`. Claude Code supports project skills in `.claude/skills/<name>/SKILL.md` and personal skills in `~/.claude/skills/<name>/SKILL.md`. [Official skill documentation](https://code.claude.com/docs/en/skills).

Alternatively, the repository README supplies this manual stdio registration command. Replace the path with your checkout, and use this as an alternative to the project MCP entry:

```bash
claude mcp add --transport stdio openmcp -- uv run --directory /absolute/path/to/openmcp openmcp mcp
```

That command registers the tools; it does not copy or install the skill file. For manual cross-project use, register the server with `--scope user` and separately place the skill in the personal skill directory. User-scope MCP entries apply across projects. [MCP installation scopes](https://code.claude.com/docs/en/mcp#user-scope).

Both manual approaches still depend on this checkout, its `.env`, local catalog, wallet files, and running services. They are not the proposed packaged installation.

## 4. Verify without buying

In another terminal at the repository root:

```bash
uv run openmcp check-mcp
```

It launches a temporary stdio MCP client, initializes the connection, lists tools, and calls `balance` and `discover`. Expect `stdio: "ok"`, the three tool names, three discovered endpoints, and `spent_by_check_cents: 0`.

This check confirms the local MCP-to-gateway path. It does not execute a purchase, verify provider fulfillment, check RPC funding, or confirm Claude loaded the skill. `/mcp` in Claude and `doctor --chain` cover different parts of setup.

## 5. Invoke the skill

In Claude Code:

```text
/openmcp Investigate FreightFlow's operational health, hidden legal liabilities,
and competitor market share. My total budget is 15.00 test pathUSD. Label the
fictional demo evidence and include source costs, remaining service budget,
and both payment receipt references for every completed purchase.
```

With a fresh session and one purchase from each service, the service total is **1.20** and the remaining allowance is **13.80** test pathUSD. Each purchase makes two payments; the full set makes six. Network fees are extra and wallet balance changes differ from service spend.

These totals assume no prior session spending. A new intended purchase uses a new idempotency key and may charge again. Repeating a research prompt is not itself an idempotent operation.

## Configuration and operator commands

Defaults come from [settings](../../openmcp/config.py) and [`.env.example`](../../.env.example). Paths are relative to the process working directory, which is why the stdio launch points at the checkout.

| Setting | Current purpose/default |
| --- | --- |
| `OPENMCP_BASE_URL` | Gateway URL; `http://127.0.0.1:8000` |
| `OPENMCP_API_TOKEN` | One local Bearer connection token, generated by `init` |
| `OPENMCP_BUDGET_CENTS` | Maximum configured service allowance; `1500` |
| `OPENMCP_CATALOG` | Local catalog; `catalog/providers.json`, required by agent and gateway |
| `OPENMCP_WALLETS` | `.openmcp/wallets`; agent loads `agent.json`, approvals use public addresses |
| `OPENMCP_DATABASE` | Gateway ledger `.openmcp/mpp.sqlite3`; its parent also locates the agent payment journal |
| `TEMPO_RPC_URL` / `TEMPO_CHAIN_ID` | Moderato RPC / `42431`; runtime pins testnet |
| `OPENMCP_MPP_SECRET` / `OPENMCP_FEE_BPS` | Gateway challenge secret / `1000` (10%); shared demo configuration |

Changing `OPENMCP_BASE_URL` alone does not make a hosted installation: the agent still requires local catalog/address state, and the current gateway binds to loopback with a localhost host allowlist.

| Command | Effect |
| --- | --- |
| `uv run openmcp mcp` | Runs the stdio server; normally launched by Claude |
| `uv run openmcp balance` | Reads `/dashboard`: service budget, receipts, and all five on-chain balances; richer than the MCP `balance` tool |
| `uv run openmcp demo` | Scripted purchase of all three sources; makes testnet payments |
| `uv run openmcp reset` | Operator action: creates a new allowance/session, preserves payment journals and chain history; refuses pending payments/fulfillment |

## Troubleshooting

| Symptom | Check/action |
| --- | --- |
| `/openmcp` is unavailable | Confirm the skill file is loaded from this repo or the personal skill directory; tool registration alone does not install it |
| No OpenMCP tools | Check `/mcp`, project-server approval, `uv` on the launch path, and the checkout path |
| `401 unauthorized` | Ensure gateway and local client use the same `.env` connection token; restart after configuration changes |
| Missing wallet/catalog | Run setup from the checkout; check configured paths without displaying secret files |
| Discovery works but purchase fails | Confirm provider services are running and paying wallets are funded using `doctor --chain` |
| `unapproved_price` after adding a service | The client also reads the local catalog at startup; a server-only addition is insufficient today |
| Insufficient service allowance | Inspect `balance`; extra wallet tokens do not raise the authorized budget |
| Timeout or pending payment | Preserve the original arguments/key. Retry only as directed by the skill; stop new purchases if unresolved |
| Need receipt details after an error | Operator can inspect `uv run openmcp balance` or authenticated `/transactions`; MCP currently lacks a status tool |

The skill must not edit payment settings or reset the demo to expand its spending authority. Pending execution recovery should preserve the original payment history.
