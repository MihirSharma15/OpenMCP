import json
from textwrap import dedent

import pytest
from mcp.client.stdio import stdio_client

from openmcp.cli import check_mcp


@pytest.mark.parametrize(
    ("mode", "discovery", "count"),
    [
        (
            "account",
            {
                "providers": [
                    {"provider_id": "one", "queries": [{"endpoint_id": "a"}]},
                    {
                        "provider_id": "two",
                        "queries": [{"endpoint_id": "b"}, {"endpoint_id": "c"}],
                    },
                ],
                "discovery_is_free": True,
            },
            3,
        ),
        ("account", {"providers": [], "discovery_is_free": True}, 0),
        ("demo", {"endpoints": [{"endpoint_id": "a"}, {"endpoint_id": "b"}]}, 2),
        ("demo", {"endpoints": []}, 0),
    ],
)
async def test_check_mcp_counts_discovery_results_without_purchasing(
    monkeypatch, capsys, mode, discovery, count
):
    # Exercise the real stdio handshake and structured tool responses, with a
    # subprocess that provides only free tools and never contacts a gateway.
    program = dedent(
        f"""
        from typing import Any
        from mcp.server.fastmcp import FastMCP

        server = FastMCP("Connection check fixture")

        @server.tool()
        async def balance() -> dict[str, Any]:
            return {{"available_cents": 1000, "agent": {{}}, "address": "demo-wallet"}}

        @server.tool()
        async def discover(query: str, budget_cents: int) -> dict[str, Any]:
            assert query == {('services' if mode == 'account' else 'FreightFlow due diligence')!r}
            assert budget_cents == {0 if mode == 'account' else 1500}
            return {discovery!r}

        server.run(transport="stdio")
        """
    )

    def fixture_stdio(parameters):
        assert parameters.args[-2:] == ["--mode", mode]
        return stdio_client(parameters.model_copy(update={"args": ["-c", program]}))

    monkeypatch.setattr("mcp.client.stdio.stdio_client", fixture_stdio)

    await check_mcp(mode)

    summary = json.loads(capsys.readouterr().out)
    assert summary["stdio"] == "ok"
    assert set(summary["tools"]) == {"balance", "discover"}
    assert summary["mode"] == mode
    assert summary["discovered_endpoints"] == count
    assert summary["spent_by_check_cents"] == 0
    if mode == "account":
        assert summary["available_cents"] == 1000
        assert summary["agent"] == {}
    else:
        assert summary["agent_wallet"] == "demo-wallet"
