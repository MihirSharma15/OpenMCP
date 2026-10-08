"""Two bounded BuiltWith free routes approved by the operator."""

from copy import deepcopy

ORIGIN = "https://api.builtwith.com"
SUMMARY = "builtwith-domain-summary"
TRENDS = "builtwith-technology-trends"
SERVICES = {
    SUMMARY: {
        "path": "/free1/api.json",
        "name": "Domain technology summary",
        "description": "Get indexed technology category/group counts for one domain hostname (for example example.com, not a full URL). Returns live/historical counts and available first/last indexing timestamps. Does not identify individual technologies or perform a fresh website scan. Subdomains may resolve to their root domain.",
        "properties": {
            "domain": {
                "type": "string",
                "maxLength": 253,
                "pattern": r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}(?![\s\S])",
            }
        },
        "required": ["domain"],
    },
    TRENDS: {
        "path": "/trends/v6/api.json",
        "name": "Technology adoption trends",
        "description": "Get adoption coverage counts and metadata for one technology name, for example Shopify or Google-Analytics. Use hyphens instead of spaces. Returns available description, categories, coverage counts and BuiltWith reference links. Despite the trends name, this query does not return a historical time series or a list of websites using that technology.",
        "properties": {
            "technology": {
                "type": "string",
                "minLength": 1,
                "maxLength": 100,
                "pattern": r"^[A-Za-z0-9][A-Za-z0-9.-]*(?![\s\S])",
            }
        },
        "required": ["technology"],
    },
}


def provider(mode="test"):
    if mode not in {"test", "live"}:
        raise ValueError("Choose test or live account mode")
    return {
        "provider_id": "builtwith",
        "name": "BuiltWith",
        "description": "Two indexed technology-data queries: domain-level technology category/group counts, and adoption coverage counts plus metadata for a named technology. Does not expose individual website technology identification, lists of websites using a technology, historical time series or other paid BuiltWith products.",
        "secret_ref": "BUILTWITH_API_KEY",
        "queries": [
            {
                "endpoint_id": identifier,
                "name": "BuiltWith " + spec["name"],
                "description": spec["description"] + " Flat $0.02 per successful request.",
                "url": ORIGIN + spec["path"],
                "keywords": ["website", "technology", "adoption", "stack"],
                "adapter": "builtwith",
                "settlement": "api_key",
                "price_cents": 2,
                "input_schema": {
                    "type": "object",
                    "properties": deepcopy(spec["properties"]),
                    "required": spec["required"],
                    "additionalProperties": False,
                },
                "output_schema": {
                    "type": "object",
                    "properties": {
                        "provider": {"const": "BuiltWith"},
                        "endpoint_id": {"const": identifier},
                    },
                    "required": ["provider", "endpoint_id"],
                },
                "enabled": True,
                "mode": mode,
                "supports_idempotency": True,
            }
            for identifier, spec in SERVICES.items()
        ],
    }
