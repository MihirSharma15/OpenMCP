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
        "Search up to 20 web pages with titles, source URLs, and excerpts. Supports news/finance, recency, and domain filters. Uses one Tavily credit.",
    ),
    ADVANCED: (
        "advanced",
        "/search",
        3,
        INPUT_SCHEMA,
        "Advanced web search",
        "Search up to 20 web pages with more relevant content chunks. Supports news/finance, recency, and domain filters. Uses two Tavily credits.",
    ),
    EXTRACT: (
        "basic",
        "/extract",
        2,
        EXTRACT_SCHEMA,
        "Extract webpage content",
        "Extract Markdown from one to five public HTTPS URLs. Optional query selects relevant chunks. Partial successes include failed URLs; the flat batch price applies if any URL succeeds.",
    ),
    EXTRACT_ADVANCED: (
        "advanced",
        "/extract",
        3,
        EXTRACT_SCHEMA,
        "Advanced webpage extraction",
        "Extract Markdown including tables and embedded content from one to five public HTTPS URLs. Higher extraction success; partial batches are billed at the flat batch price.",
    ),
    MAP: (
        "basic",
        "/map",
        5,
        MAP_SCHEMA,
        "Map website URLs",
        "Discover up to 50 URLs on a public HTTPS website, one link level deep. Returns links, not page content. No external links or paid natural-language instructions. Flat price per map.",
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
        "description": "Web search, news and financial research, webpage extraction, and website URL mapping.",
        "secret_ref": "TAVILY_API_KEY",
        "queries": queries,
    }
