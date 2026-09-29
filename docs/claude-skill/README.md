# Claude skill workstream

OpenMCP lets Claude discover priced data services, buy relevant evidence within an authorized budget, and synthesize an attributed answer. The intended product is an install-once client for a growing remote service registry. Provider SDK integrations and API Creator adapters should enter that same registry and be usable through the same skill.

This folder owns the agent skill **documentation and roadmap**. The initial audit made no runtime changes. A subsequent implementation adds multi-client registration and skill distribution in `openmcp/client_setup/`; it does not change wallet state or payment execution.

Reviewed on **2026-09-29**, against repository revision **`0860b96`**. The working tree was clean before these documents were added. Statements labeled current describe the code at that revision; roadmap interfaces are proposals.

| Document | Contents |
| --- | --- |
| [Multi-client installation](multi-client-install.md) | Implemented installer for Codex, Claude Code, and Cursor, plus exports for other clients |
| [Installation](installation.md) | Run the current demo, connect Claude Code, verify the connection, and troubleshoot |
| [Current tools and endpoints](current-contract.md) | MCP arguments/results, REST routes, purchasable services, payment and retry behavior |
| [Roadmap](roadmap.md) | Delivery sequence, ownership, backend contracts, dependencies, and completion criteria |

## What exists today

```text
Claude Code
  loads .claude/skills/openmcp/SKILL.md
  calls balance / discover / execute over local stdio
    ↓
Local MCP process: openmcp mcp
  Agent + agent wallet + persisted payment journal
    ↓ HTTP + incoming MPP payment
OpenMCP gateway: 127.0.0.1:8000
  local catalog + session ledger + platform wallet
    ↓ HTTP + independent outgoing MPP payment
Provider wrappers: 127.0.0.1:9001
    ↓
Fictional upstream APIs: ports 9101–9103
```

The instruction file directs source selection, explicit budget handling, retries, attribution, and reporting. Python implements discovery calls, signing, payment validation, persistence, and execution. Claude writes the final report. The browser demo uses a separate scripted Python runner and is not the Claude skill.

| Capability | Current state |
| --- | --- |
| Claude entry point | Project skill `/openmcp` plus checked-in `.mcp.json` |
| MCP transport | Local stdio; three tools, no MCP resources or prompts declared by this server |
| Services | Three fixed FreightFlow demo endpoints; all evidence is fictional |
| Purchase | Two independent MPP `tempo` / `charge` payments on chain `42431` |
| Spending controls | Explicit budget instruction, integer-cent limits, gateway reservations, local credential journal |
| Recovery | Same-request/key replay, persisted credentials, completed-result replay, pending execution state |
| Report | Claude synthesizes purchased evidence and includes source costs and both receipt references |
| Distribution | Client registration/skill installer for three hosts; still depends on a configured local runtime |
| Account model | Single operator token, one active global session, fixed named wallets |

## Source map and ownership

| Source | Responsibility | Workstream relationship |
| --- | --- | --- |
| [Skill instructions](../../.claude/skills/openmcp/SKILL.md) | Claude workflow and reporting rules | Claude skill owns |
| [MCP registration](../../.mcp.json) | Starts the local server through `uv` | Claude skill owns consumer distribution changes |
| [Client setup](../../openmcp/client_setup) | Multi-client installer, launcher, packaged skill | Agent skill workstream owns |
| [MCP server](../../openmcp/mcp_server.py) | Tool definitions, annotations, error conversion | Claude skill owns |
| [Agent client](../../openmcp/agent.py) | Gateway calls and local purchase approval | Claude skill owns, coordinated with gateway contract |
| [CLI](../../openmcp/cli.py), [settings](../../openmcp/config.py) | Setup, commands, shared configuration | Shared; consumer onboarding needs separation |
| [Payments](../../openmcp/payments.py), [wallets](../../openmcp/wallets.py), [store](../../openmcp/store.py) | Signing, policy checks, journals, session state | Shared payment infrastructure; preserve existing guarantees |
| [Gateway](../../openmcp/app.py), [engine](../../openmcp/engine.py), [models](../../openmcp/models.py) | REST contract, discovery, budgets, execution | Backend dependency |
| [Catalog](../../catalog/providers.json) | Current endpoint descriptions, schemas and prices | Replace with backend registry contract |
| [Packaging](../../pyproject.toml) | `openmcp-demo` package and `openmcp` CLI | Distribution dependency |
| [MCP/payment tests](../../tests/test_mpp.py) | Existing transport and payment regression coverage | Shared acceptance baseline |

## Audit verification

Executed against isolated test fixtures:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_mpp.py -q
```

Result: **15 passed**. These tests use the real MPP parsing/protocol machinery with a settlement double. They cover both hops, concurrent retries, lost responses, restart recovery, budget ceilings, changed requests, several mutated payment terms, authentication, and a purchase through MCP. They do not prove Claude follows the instruction file or validate a packaged installation.

The audit did not start services, invoke Claude, fund wallets, or make live purchases. Live-chain coverage already exists in [the opt-in integration test](../../tests/test_live_mpp.py); this pass did not rerun it. Installation instructions were checked against source and the linked official Claude Code documentation.
