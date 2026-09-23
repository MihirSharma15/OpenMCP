"""MarketScope MPP wrapper for competitor-market data."""

import os
from typing import Annotated

import httpx
from pydantic import Field

from openmcp_provider import OpenMCPProvider

_UPSTREAM_URL = os.environ.get("MARKETSCOPE_API_URL", "http://127.0.0.1:9103")
_UPSTREAM_TRANSPORT: httpx.AsyncBaseTransport | None = None

provider = OpenMCPProvider(
    name="MarketScope",
    wallet="market",
    realm="marketscope.local",
)


@provider.tool(route="/competitor-market-share", price_usd="0.27")
async def competitor_market_share(
    company: Annotated[str, Field(min_length=1)],
) -> dict[str, object]:
    async with httpx.AsyncClient(
        base_url=_UPSTREAM_URL,
        transport=_UPSTREAM_TRANSPORT,
    ) as upstream:
        response = await upstream.get("/v1/private-financials", params={"company": company})
        response.raise_for_status()
        financials = response.json()

    leaders = financials["leaders"]
    content = (
        f"{financials['year']} Estimated Revenue for {company}: "
        f"${financials['estimated_revenue_millions']}M "
        f"(Up {financials['yoy_growth_pct']}% YoY). EBITDA margin: "
        f"{financials['ebitda_margin_pct']}%. Current market share in "
        f"{financials['corridor']}: {financials['market_share_pct']}% "
        f"(Ranked #{financials['rank']} behind {leaders[0]}, {leaders[1]}, "
        f"and {leaders[2]})."
    )
    metrics = {key: value for key, value in financials.items() if key not in {"company", "sources"}}
    return {
        "company": company,
        "provider": "MarketScope",
        "title": "Competitor market share assessment",
        "content": content,
        "metrics": metrics,
        "sources": financials["sources"],
        "is_demo_data": True,
    }
