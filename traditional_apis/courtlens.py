"""CourtLens's fictional court-docket API (port 9102)."""

from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="CourtLens Traditional API")

    @app.get("/v1/court-dockets")
    async def court_dockets(entity: str) -> dict[str, object]:
        return {
            "entity": entity,
            "pending_class_actions": 2,
            "jurisdiction": "Southern District of New York",
            "allegation": "independent contractor misclassification",
            "liability_low_millions": 4.2,
            "liability_high_millions": 7,
            "sources": [
                {
                    "id": "courtlens-sdny-2026-demo",
                    "title": "FreightFlow class-action docket summary",
                    "publisher": "CourtLens Demo Research",
                    "fictional": True,
                }
            ],
        }

    return app


app = create_app()
