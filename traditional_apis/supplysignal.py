"""SupplySignal's fictional fleet telematics API (port 9101)."""

from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="SupplySignal Traditional API")

    @app.get("/v1/fleet-telematics")
    async def fleet_telematics(company: str) -> dict[str, object]:
        return {
            "company": company,
            "utilization_pct": 88,
            "turnover_days": 4.2,
            "industry_turnover_days": 5.1,
            "window_days": 90,
            "sources": [
                {
                    "id": "supplysignal-fleet-2026-q3",
                    "title": "FreightFlow fleet operating summary",
                    "publisher": "SupplySignal Demo Research",
                    "fictional": True,
                }
            ],
        }

    return app


app = create_app()
