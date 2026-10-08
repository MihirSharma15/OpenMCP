"""Reviewed Tavily search, extraction, and mapping services with fixed retail prices."""

from copy import deepcopy

SEARCH = "tavily-web-search"
ADVANCED = "tavily-advanced-search"
EXTRACT = "tavily-extract"
EXTRACT_ADVANCED = "tavily-advanced-extract"
MAP = "tavily-map"
URL = "https://api.tavily.com/search"
TEXT = {"type": "string", "minLength": 1, "maxLength": 400}
PUBLIC_URL = {"type": "string", "minLength": 1, "maxLength": 2048, "pattern": "^https://"}
DOMAIN_LIST = {
    "type": "array",
    "maxItems": 10,
    "uniqueItems": True,
    "items": {
        "type": "string",
        "maxLength": 253,
        "pattern": r"^[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?$",
    },
}


def schema(properties, required):
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


INPUT_SCHEMA = schema(
    {
        "query": TEXT,
        "max_results": {"type": "integer", "minimum": 1, "maximum": 20, "default": 10},
        "topic": {"type": "string", "enum": ["general", "news", "finance"], "default": "general"},
        "time_range": {"type": "string", "enum": ["day", "week", "month", "year"]},
        "include_domains": DOMAIN_LIST,
        "exclude_domains": DOMAIN_LIST,
    },
    ["query"],
)
EXTRACT_SCHEMA = schema(
    {
        "urls": {
            "type": "array",
            "minItems": 1,
            "maxItems": 5,
            "uniqueItems": True,
            "items": PUBLIC_URL,
        },
        "query": TEXT,
    },
    ["urls"],
)
MAP_SCHEMA = schema(
    {
        "url": PUBLIC_URL,
        "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
    },
    ["url"],
)
SERVICES = {
    SEARCH: (
        "basic",
        "/search",
        2,
        INPUT_SCHEMA,
        "Basic web search",
        "Find web sources for query (1–400 characters) using basic search. Returns titles, URLs and content excerpts, not full pages or a generated answer. max_results is 1–20, default 10. Optional topic general/news/finance (default general), time_range day/week/month/year, and include_domains/exclude_domains (up to ten each). Uses one Tavily search credit.",
    ),
    ADVANCED: (
        "advanced",
        "/search",
        3,
        INPUT_SCHEMA,
        "Advanced web search",
        "Find web sources for query (1–400 characters) using advanced search depth and content chunks. Returns titles, URLs and excerpts, not full pages or a generated answer. max_results is 1–20, default 10. Optional topic general/news/finance (default general), time_range day/week/month/year, and include_domains/exclude_domains (up to ten each). Uses two Tavily search credits.",
    ),
    EXTRACT: (
        "basic",
        "/extract",
        2,
        EXTRACT_SCHEMA,
        "Extract webpage content",
        "Read one to five unique public HTTPS urls using basic extraction. Returns Markdown content per successful URL and failed_results for failures. Optional query (1–400 characters) selects relevant content chunks instead of unfocused page content. A partial batch is returned with partial_success; the flat batch price applies if any URL succeeds. Does not crawl linked pages.",
    ),
    EXTRACT_ADVANCED: (
        "advanced",
        "/extract",
        3,
        EXTRACT_SCHEMA,
        "Advanced webpage extraction",
        "Read one to five unique public HTTPS urls using advanced extraction depth. Returns Markdown content per successful URL and failed_results for failures. Optional query (1–400 characters) selects relevant chunks. Choose this when advanced extraction is needed; success is not guaranteed. A partial batch is returned with partial_success; the flat batch price applies if any URL succeeds. Does not crawl linked pages.",
    ),
    MAP: (
        "basic",
        "/map",
        5,
        MAP_SCHEMA,
        "Map website URLs",
        "Discover links from a public HTTPS website url, one link level deep. limit is 1–50, default 20. Returns results as URL strings, not page contents. External links are excluded. Use extraction separately to read selected pages. No recursive crawling or natural-language mapping instructions. Flat price per map request.",
    ),
}


def provider(mode="test"):
    if mode not in {"test", "live"}:
        raise ValueError("Choose test or live account mode")
    queries = []
    for endpoint_id, (_, path, price, inputs, name, description) in SERVICES.items():
        result_type = "string" if endpoint_id == MAP else "object"
        queries.append(
            {
                "endpoint_id": endpoint_id,
                "name": "Tavily " + name,
                "description": description,
                "keywords": ["web", "search", "news", "research"]
                if path == "/search"
                else ["web", "website", "extract", "content", "map"],
                "url": "https://api.tavily.com" + path,
                "settlement": "api_key",
                "adapter": "tavily",
                "price_cents": price,
                "input_schema": deepcopy(inputs),
                "output_schema": {
                    "type": "object",
                    "properties": {
                        "provider": {"const": "Tavily"},
                        "endpoint_id": {"const": endpoint_id},
                        "results": {"type": "array", "items": {"type": result_type}},
                    },
                    "required": ["provider", "endpoint_id", "results"],
                },
                "enabled": True,
                "mode": mode,
                # Account mode is not a Tavily sandbox. Replay is provided by our journal.
                "supports_idempotency": True,
            }
        )
    return {
        "provider_id": "tavily",
        "name": "Tavily",
        "description": "Basic and advanced web search with general/news/finance topic filters, Markdown extraction from batches of up to five public HTTPS pages, and one-level website URL mapping. Finance means web search about finance, not a financial database. OpenMCP does not expose Tavily answer generation or recursive crawling.",
        "secret_ref": "TAVILY_API_KEY",
        "queries": queries,
    }
