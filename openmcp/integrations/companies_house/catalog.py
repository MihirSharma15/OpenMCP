"""Operator-approved, read-only UK company register queries."""

from copy import deepcopy

ORIGIN = "https://api.company-information.service.gov.uk"
SEARCH = "companies-house-search"
PROFILE = "companies-house-profile"
OFFICERS = "companies-house-officers"
FILINGS = "companies-house-filings"
COMPANY_NUMBER = {"type": "string", "minLength": 8, "maxLength": 8, "pattern": "^[A-Z0-9]{8}$"}
PAGE = {
    "items_per_page": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
    "start_index": {"type": "integer", "minimum": 0, "maximum": 100000, "default": 0},
}


def schema(properties, required):
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


SERVICES = {
    SEARCH: {
        "path": "/search/companies",
        "name": "Company search",
        "description": "Find UK registered companies by query (name or search term, 1–200 characters). Returns company numbers, names, statuses and available addresses/dates. items_per_page is 1–100, default 20; start_index defaults to 0. Follow pagination.next_start_index for another page, purchased separately. Use the returned company_number string for profile, officers and filing-history queries.",
        "input_schema": schema(
            {
                "query": {"type": "string", "minLength": 1, "maxLength": 200, "pattern": r"\S"},
                **PAGE,
            },
            ["query"],
        ),
    },
    PROFILE: {
        "path": "/company/{company_number}",
        "name": "Company profile",
        "description": "Look up one UK company by company_number: exactly eight uppercase letters/digits, preserving leading zeros. Returns available name, status, incorporation date, registered office, SIC codes, previous names, accounts filing status and confirmation-statement metadata. Accounts fields are filing information, not financial statements or audited revenue/profit figures.",
        "input_schema": schema({"company_number": COMPANY_NUMBER}, ["company_number"]),
    },
    OFFICERS: {
        "path": "/company/{company_number}/officers",
        "name": "Company officers",
        "description": "List one page of UK company officers by eight-character company_number (preserve leading zeros and uppercase prefixes). Returns available names, roles, appointment/resignation dates, nationality, occupation and addresses, plus active/resigned counts and pagination. items_per_page is 1–100, default 20; start_index defaults to 0. Follow next_start_index for additional pages, purchased separately; one page may not contain every officer.",
        "input_schema": schema({"company_number": COMPANY_NUMBER, **PAGE}, ["company_number"]),
    },
    FILINGS: {
        "path": "/company/{company_number}/filing-history",
        "name": "Filing history",
        "description": "List one page of UK company filing history by eight-character company_number (preserve leading zeros and uppercase prefixes). Returns filing dates, types, categories, description codes/parameters and available transaction IDs. items_per_page is 1–100, default 20; start_index defaults to 0. Follow pagination.next_start_index for another separately purchased page. Returns metadata, not PDFs, document contents or audited financial analysis.",
        "input_schema": schema({"company_number": COMPANY_NUMBER, **PAGE}, ["company_number"]),
    },
}


def provider(mode="test"):
    if mode not in {"test", "live"}:
        raise ValueError("Choose test or live account mode")
    return {
        "provider_id": "companies-house",
        "name": "Companies House",
        "description": "Read-only UK company-register access through company search, company profiles, paginated officers and paginated filing-history metadata. Profile accounts fields describe filing status; OpenMCP does not retrieve filing documents, extract audited financial statements or submit register changes.",
        "secret_ref": "COMPANIES_HOUSE_API_KEY",
        "queries": [
            {
                "endpoint_id": identifier,
                "name": "Companies House " + definition["name"],
                "description": definition["description"] + " Flat $0.02 per successful request.",
                "url": ORIGIN + definition["path"],
                "keywords": ["UK", "company", "business", "register", "officers", "filings"],
                "adapter": "companies_house",
                "settlement": "api_key",
                "price_cents": 2,
                "input_schema": deepcopy(definition["input_schema"]),
                "output_schema": {
                    "type": "object",
                    "properties": {
                        "provider": {"const": "Companies House"},
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
