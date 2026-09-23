"""MarketScope's fictional private-market API (port 9103)."""

from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="MarketScope Traditional API")

    @app.get("/v1/private-financials")
    async def private_financials(company: str) -> dict[str, object]:
        return {
            "company": company,
            "year": 2025,
            "estimated_revenue_millions": 142,
            "yoy_growth_pct": 12,
            "ebitda_margin_pct": 14,
            "market_share_pct": 8.4,
            "corridor": "Midwest logistics corridor",
            "rank": 4,
            "leaders": ["XPO", "JB Hunt", "CH Robinson"],
            "sources": [
                {
                    "id": "marketscope-midwest-2025-demo",
                    "title": "Midwest logistics market estimate",
                    "publisher": "MarketScope Demo Research",
                    "fictional": True,
                }
            ],
        }

    return app


app = create_app()
