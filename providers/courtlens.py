"""CourtLens MPP wrapper for legal-liability data."""

import os
from typing import Annotated

import httpx
from pydantic import Field

from openmcp_provider import OpenMCPProvider

_UPSTREAM_URL = os.environ.get("COURTLENS_API_URL", "http://127.0.0.1:9102")
_UPSTREAM_TRANSPORT: httpx.AsyncBaseTransport | None = None

provider = OpenMCPProvider(
    name="CourtLens",
    wallet="legal",
    realm="courtlens.local",
)


@provider.tool(route="/legal-liabilities", price_usd="0.45")
async def legal_liabilities(
    company: Annotated[str, Field(min_length=1)],
) -> dict[str, object]:
    async with httpx.AsyncClient(
        base_url=_UPSTREAM_URL,
        transport=_UPSTREAM_TRANSPORT,
    ) as upstream:
        response = await upstream.get("/v1/court-dockets", params={"entity": company})
        response.raise_for_status()
        docket = response.json()

    content = (
        f"WARNING: {docket['pending_class_actions']} pending class-action lawsuits "
        f"found in the {docket['jurisdiction']} for {company} regarding "
        f"{docket['allegation']}. Estimated liability exposure: "
        f"${docket['liability_low_millions']}M - ${docket['liability_high_millions']}M."
    )
    metrics = {key: value for key, value in docket.items() if key not in {"entity", "sources"}}
    return {
        "company": company,
        "provider": "CourtLens",
        "title": "Legal liabilities assessment",
        "content": content,
        "metrics": metrics,
        "sources": docket["sources"],
        "is_demo_data": True,
    }
