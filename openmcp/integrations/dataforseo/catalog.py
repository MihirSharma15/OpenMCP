"""Reviewed service descriptions and limits, based on DataForSEO's MCP documentation.

See docs/dataforseo.md for source URLs and the inspected upstream revision.
The model chooses these services; it cannot choose an arbitrary upstream path.
"""

from copy import deepcopy

SEARCH = "dataforseo-google-search"
OVERVIEW = "dataforseo-keyword-metrics"
RELATED = "dataforseo-related-keywords"

LOCALE = {
    "location_code": {
        "type": "integer",
        "minimum": 1,
        "default": 2840,
        "description": "DataForSEO location code. Defaults to 2840 (United States).",
    },
    "language_code": {
        "type": "string",
        "pattern": "^[a-z]{2}(-[A-Za-z]{2,4})?$",
        "default": "en",
        "description": "Language code; defaults to English (en).",
    },
}
KEYWORD = {
    "type": "string",
    "minLength": 1,
    "maxLength": 80,
    "pattern": r"^\s*\S+(?:\s+\S+){0,9}\s*$",
}


def schema(properties, required):
    return {
        "type": "object",
        "properties": deepcopy(LOCALE) | properties,
        "required": required,
        "additionalProperties": False,
    }


SERVICES = {
    SEARCH: {
        "name": "DataForSEO Google search results",
        "description": (
            "Search Google for current organic search results, rankings, titles, URLs, and "
            "snippets for a keyword and location. Fetches the first results page (depth 10). "
            "Use plain text: search operators and paid enrichment options are not supported."
        ),
        "path": "/v3/serp/google/organic/live/advanced",
        "price_cents": 2,
        "input_schema": schema(
            {
                "keyword": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 700,
                    "pattern": r"^[^:%]+$",
                    "description": "Plain-text Google search query, without colon operators or percent escapes.",
                },
                "device": {"type": "string", "enum": ["desktop", "mobile"], "default": "desktop"},
            },
            ["keyword"],
        ),
    },
    OVERVIEW: {
        "name": "DataForSEO Google keyword metrics",
        "description": (
            "Research up to 100 Google keywords: search volume, monthly trends, cost per click "
            "(CPC), paid-search competition, organic ranking difficulty, and search intent. "
            "Metrics come from DataForSEO's keyword database, updated monthly; unknown keywords "
            "may be missing. Includes source update timestamps."
        ),
        "path": "/v3/dataforseo_labs/google/keyword_overview/live",
        "price_cents": 5,
        "input_schema": schema(
            {
                "keywords": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 100,
                    "uniqueItems": True,
                    "items": deepcopy(KEYWORD),
                    "description": "Keywords to research; each phrase has at most 80 characters and 10 words.",
                }
            },
            ["keywords"],
        ),
    },
    RELATED: {
        "name": "DataForSEO related Google keyword ideas",
        "description": (
            "Find up to 100 related keyword ideas from Google's related-search data for a seed "
            "keyword. Returns available search volume, CPC, competition, difficulty, intent, "
            "and monthly trends. Uses DataForSEO's SERP and keyword databases; fewer ideas "
            "may be available. Includes source update timestamps."
        ),
        "path": "/v3/dataforseo_labs/google/related_keywords/live",
        "price_cents": 5,
        "input_schema": schema(
            {
                "keyword": deepcopy(KEYWORD),
                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 100},
            },
            ["keyword"],
        ),
    },
}


def provider(mode="test"):
    if mode not in {"test", "live"}:
        raise ValueError("Choose test or live DataForSEO mode")
    origin = "https://sandbox.dataforseo.com" if mode == "test" else "https://api.dataforseo.com"
    return {
        "provider_id": "dataforseo",
        "name": "DataForSEO",
        "description": "Google search results and SEO keyword research: search volume, CPC, trends, difficulty, intent, and related keyword ideas.",
        "secret_ref": "DATAFORSEO_AUTH",
        "queries": [
            {
                "endpoint_id": endpoint_id,
                "name": service["name"],
                "description": service["description"],
                "url": origin + service["path"],
                "settlement": "api_key",
                "adapter": "dataforseo",
                "price_cents": service["price_cents"],
                "input_schema": deepcopy(service["input_schema"]),
                "output_schema": {
                    "type": "object",
                    "properties": {
                        "provider": {"const": "DataForSEO"},
                        "endpoint_id": {"const": endpoint_id},
                        "is_demo_data": {"type": "boolean"},
                        "query": {"type": "object"},
                        "items": {"type": "array", "items": {"type": "object"}},
                    },
                    "required": ["provider", "endpoint_id", "is_demo_data", "query", "items"],
                },
                "enabled": True,
                "mode": mode,
                # OpenMCP journals once and replays stored executions. This is not
                # a claim that DataForSEO implements an Idempotency-Key header.
                "supports_idempotency": True,
            }
            for endpoint_id, service in SERVICES.items()
        ],
    }
