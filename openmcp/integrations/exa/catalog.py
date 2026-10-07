"""Bounded, fixed-price Exa REST services."""

from copy import deepcopy

SEARCH = "exa-search"
CONTENTS = "exa-contents"
ORIGIN = "https://api.exa.ai"
SERVICES = {
    SEARCH: {
        "path": "/search",
        "name": "Search the web",
        "max_cost_microusd": 7000,
        "description": "Search up to ten web results using Exa auto search. Returns titles, URLs and publication metadata. No deep research or content enrichment. Flat $0.02 per successful request.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 1, "maxLength": 500},
                "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 10},
                "category": {
                    "type": "string",
                    "enum": [
                        "company",
                        "publication",
                        "news",
                        "personal site",
                        "financial report",
                        "people",
                    ],
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    CONTENTS: {
        "path": "/contents",
        "name": "Retrieve webpage text",
        "max_cost_microusd": 1000,
        "description": "Retrieve text from one public HTTPS page, capped at 20,000 characters. No summaries, highlights, subpage crawling or paid enrichment. Flat $0.02 per successful request.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 2048,
                    "pattern": "^https://",
                },
                "max_characters": {
                    "type": "integer",
                    "minimum": 100,
                    "maximum": 20000,
                    "default": 10000,
                },
            },
            "required": ["url"],
            "additionalProperties": False,
        },
    },
}


def provider(mode="test"):
    if mode not in {"test", "live"}:
        raise ValueError("Choose test or live account mode")
    return {
        "provider_id": "exa",
        "name": "Exa",
        "description": "Web search and public webpage text for agent research.",
        "secret_ref": "EXA_API_KEY",
        "queries": [
            {
                "endpoint_id": identifier,
                "name": "Exa " + definition["name"],
                "description": definition["description"],
                "url": ORIGIN + definition["path"],
                "keywords": ["web", "research", "search" if identifier == SEARCH else "contents"],
                "settlement": "api_key",
                "adapter": "exa",
                "price_cents": 2,
                "input_schema": deepcopy(definition["input_schema"]),
                "output_schema": {
                    "type": "object",
                    "properties": {
                        "provider": {"const": "Exa"},
                        "endpoint_id": {"const": identifier},
                    },
                    "required": ["provider", "endpoint_id"],
                },
                "enabled": True,
                "mode": mode,
                "supports_idempotency": True,
            }
            for identifier, definition in SERVICES.items()
        ],
    }
