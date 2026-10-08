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
        "description": "Read one public HTTPS webpage url as Markdown, with available title, description and source metadata. only_main_content defaults to true; set false to include surrounding page content. Does not follow linked pages, parse PDFs, access authenticated pages, perform browser actions or run AI extraction. Flat $0.02 per successful request.",
    },
    HTML: {
        "path": "/scrape",
        "format": "html",
        "price_cents": 2,
        "input_schema": SCRAPE_SCHEMA,
        "name": "Scrape webpage as HTML",
        "description": "Retrieve cleaned HTML from one public HTTPS webpage url for structured parsing, with available source metadata. only_main_content defaults to true; set false to include surrounding page content. Does not follow links, parse PDFs, access authenticated pages, capture screenshots or perform browser actions/AI extraction. Flat $0.02 per successful request.",
    },
    SEARCH: {
        "path": "/search",
        "price_cents": 2,
        "input_schema": SEARCH_SCHEMA,
        "name": "Search web or news",
        "description": "Find web or news sources for query (1–500 characters). Returns titles, URLs and available descriptions without scraping result pages. limit is 1–10, default 10; source is web (default) or news. Optional time_range day/week/month/year and uppercase two-letter country (default US). No image search or paid enrichment. Flat $0.02 per successful request.",
    },
    MAP: {
        "path": "/map",
        "price_cents": 2,
        "input_schema": MAP_SCHEMA,
        "name": "Map website URLs",
        "description": "Find links on a public HTTPS website url without fetching page contents. limit is 1–10, default 10; optional search (1–500 characters) filters links by phrase. Returns results as link objects containing URLs and available title/description metadata. Excludes subdomains and ignores URL query parameters. Use a scrape query separately to read selected pages. One vendor credit per call regardless of returned links; flat $0.02 per successful request.",
    },
}


def provider(mode="test"):
    if mode not in {"test", "live"}:
        raise ValueError("Choose test or live account mode")
    return {
        "provider_id": "firecrawl",
        "name": "Firecrawl",
        "description": "Four OpenMCP queries: scrape one public HTTPS page as Markdown or cleaned HTML, search web/news without scraping results, and map website URLs. Does not expose recursive crawl jobs, authenticated browser sessions, screenshots, browser actions or AI extraction.",
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
