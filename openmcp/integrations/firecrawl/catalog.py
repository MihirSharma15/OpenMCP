"""Fixed-price, operator-reviewed Firecrawl services."""

from copy import deepcopy

SCRAPE = "firecrawl-scrape"
HTML = "firecrawl-scrape-html"
SEARCH = "firecrawl-search"
MAP = "firecrawl-map"
ORIGIN = "https://api.firecrawl.dev/v2"
PUBLIC_URL = {"type": "string", "minLength": 1, "maxLength": 2048, "pattern": "^https://"}
TEXT = {"type": "string", "minLength": 1, "maxLength": 500}


def schema(properties, required):
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


SCRAPE_SCHEMA = schema(
    {
        "url": PUBLIC_URL,
        "only_main_content": {"type": "boolean", "default": True},
    },
    ["url"],
)
SEARCH_SCHEMA = schema(
    {
        "query": TEXT,
        "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 10},
        "source": {"type": "string", "enum": ["web", "news"], "default": "web"},
        "time_range": {"type": "string", "enum": ["day", "week", "month", "year"]},
        "country": {"type": "string", "pattern": "^[A-Z]{2}$", "default": "US"},
    },
    ["query"],
)
MAP_SCHEMA = schema(
    {
        "url": PUBLIC_URL,
        "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 10},
        "search": TEXT,
    },
    ["url"],
)
SERVICES = {
    SCRAPE: {
        "path": "/scrape",
        "format": "markdown",
        "price_cents": 2,
        "input_schema": SCRAPE_SCHEMA,
        "name": "Scrape webpage as Markdown",
        "description": "Retrieve a public HTTPS webpage as Markdown with title, description, and source metadata. One page only, no PDF parsing, authenticated pages, browser actions, or AI extraction. Flat $0.02 per successful request.",
    },
    HTML: {
        "path": "/scrape",
        "format": "html",
        "price_cents": 2,
        "input_schema": SCRAPE_SCHEMA,
        "name": "Scrape webpage as HTML",
        "description": "Retrieve cleaned HTML from a public HTTPS webpage for structured parsing, with source metadata. One page only; no PDF parsing, screenshots, actions, or AI extraction. Flat $0.02 per successful request.",
    },
    SEARCH: {
        "path": "/search",
        "price_cents": 2,
        "input_schema": SEARCH_SCHEMA,
        "name": "Search web or news",
        "description": "Search up to ten web or news results with titles, URLs, and descriptions. Optional recency and country filters. Does not scrape result pages. Flat $0.02 per successful request; no images or paid enrichment.",
    },
    MAP: {
        "path": "/map",
        "price_cents": 2,
        "input_schema": MAP_SCHEMA,
        "name": "Map website URLs",
        "description": "Find up to ten URLs on a public HTTPS website, optionally matching a search phrase, without fetching page content. One vendor credit per call regardless of returned links. Flat $0.02 per successful request.",
    },
}


def provider(mode="test"):
    if mode not in {"test", "live"}:
        raise ValueError("Choose test or live account mode")
    return {
        "provider_id": "firecrawl",
        "name": "Firecrawl",
        "description": "Webpage Markdown/HTML scraping and web/news search for agent research.",
        "secret_ref": "FIRECRAWL_API_KEY",
        "queries": [
            {
                "endpoint_id": endpoint_id,
                "name": "Firecrawl " + definition["name"],
                "description": definition["description"],
                "url": ORIGIN + definition["path"],
                "keywords": ["web", "scrape", "extract", "html", "markdown"]
                if definition["path"] == "/scrape"
                else ["web", "search", "news", "map"],
                "settlement": "api_key",
                "adapter": "firecrawl",
                "price_cents": definition["price_cents"],
                "input_schema": deepcopy(definition["input_schema"]),
                "output_schema": {
                    "type": "object",
                    "properties": {
                        "provider": {"const": "Firecrawl"},
                        "endpoint_id": {"const": endpoint_id},
                    },
                    "required": ["provider", "endpoint_id"],
                },
                "enabled": True,
                "mode": mode,
                # Replay comes from OpenMCP's durable journal, not a vendor promise.
                "supports_idempotency": True,
            }
            for endpoint_id, definition in SERVICES.items()
        ],
    }
