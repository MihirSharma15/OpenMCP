# MPP testnet verification

Verified on **2026-09-23 at 03:59 UTC**, using `pympp==0.11.0`, Tempo Moderato testnet (chain `42431`), and valueless test pathUSD. The integration test used the actual SDK signer, verifier, and public testnet RPC. HTTP requests ran against the middleware and a **test-only provider contract fixture** in-process; the teammate's provider application was not part of this check.

Each purchase completed two separate MPP challenge/credential/receipt exchanges and two confirmed token transfers:

| Source | Claude → OpenMCP | OpenMCP → provider | Gross fee |
| --- | --- | --- | --- |
| Operational health | [0.40 transfer](https://explore.moderato.tempo.xyz/tx/0x9c0335a9066917f4a5b70cbfbddcfd52c75a8ae0c804539c0ac1bbcba6a02f57) | [0.36 transfer](https://explore.moderato.tempo.xyz/tx/0x213dc4094345f8cf5ecd22bee4f0378958b6ec622e649096eb73fa645fc92a30) | 0.04 |
| Legal liabilities | [0.50 transfer](https://explore.moderato.tempo.xyz/tx/0x303ea9732017e84f2423b6f2bee1fec259cd7dcce53210caefe4fd1f7f4c8930) | [0.45 transfer](https://explore.moderato.tempo.xyz/tx/0x4320f7612ffde68e55ac4002597ca82337d7c8ef967dd873db54d04ea1684bdc) | 0.05 |
| Competitor market share | [0.30 transfer](https://explore.moderato.tempo.xyz/tx/0x7d83122cc1eb96e5dd2582d8e67111651af6ba829d074e47ffd427daa692c352) | [0.27 transfer](https://explore.moderato.tempo.xyz/tx/0x528d6c3033388c77e5e3a926ad01f42c8c6ca05245e9a98d4206400b93e294ea) | 0.03 |

The test checked exact increases of **0.36 / 0.45 / 0.27** in the three provider wallets. It replayed each purchase with the same key, received the same two receipts, and observed no additional provider payments. Service spending was **1.20**, leaving **13.80** of the 15.00 allowance. Sender network fees are separate.

The run passed with `OPENMCP_LIVE_TEST=1 .venv/bin/pytest -q -s tests/test_live_mpp.py`. Machine-readable receipts and before/after balances are saved locally in `.openmcp/live-proof.json`. The test uses an isolated spending ledger; its wallet transfers remain visible on-chain.

The offline suite also passes **15 tests**, covering budget enforcement, concurrent retries, incorrect payment terms, a lost provider response, recovery after restarting both wallet clients and the middleware, provider cache authorization, and MCP tool execution. A separate free stdio check listed `balance`, `discover`, and `execute` and discovered all three endpoints through the running local server. That check exercises the MCP transport without running an interactive Claude Code conversation.

To verify the actual provider application, complete the acceptance steps in [provider-contract.md](provider-contract.md). These are two independent payments; this POC does not provide atomic settlement across both hops or automatic refunds.
