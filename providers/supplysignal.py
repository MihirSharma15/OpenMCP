"""SupplySignal MPP wrapper for operational-health data."""

import os
from typing import Annotated

import httpx
from pydantic import Field

from openmcp_provider import OpenMCPProvider

_UPSTREAM_URL = os.environ.get("SUPPLYSIGNAL_API_URL", "http://127.0.0.1:9101")
_UPSTREAM_TRANSPORT: httpx.AsyncBaseTransport | None = None

provider = OpenMCPProvider(
    name="SupplySignal",
    wallet="operations",
    realm="supplysignal.local",
)


@provider.tool(route="/operational-health", price_usd="0.36")
async def operational_health(
    company: Annotated[str, Field(min_length=1)],
) -> dict[str, object]:
    async with httpx.AsyncClient(
        base_url=_UPSTREAM_URL,
        transport=_UPSTREAM_TRANSPORT,
    ) as upstream:
        response = await upstream.get("/v1/fleet-telematics", params={"company": company})
        response.raise_for_status()
        fleet = response.json()

    content = (
        f"Fleet utilization for {company} is at {fleet['utilization_pct']}%. "
        f"Warehouse turnover is {fleet['turnover_days']} days "
        f"(industry avg {fleet['industry_turnover_days']}). "
        "No major supply chain disruptions detected in the last "
        f"{fleet['window_days']} days."
    )
    metrics = {key: value for key, value in fleet.items() if key not in {"company", "sources"}}
    return {
        "company": company,
        "provider": "SupplySignal",
        "title": "Operational health assessment",
        "content": content,
        "metrics": metrics,
        "sources": fleet["sources"],
        "is_demo_data": True,
    }
