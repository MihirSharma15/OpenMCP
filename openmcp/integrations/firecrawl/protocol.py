"""One bounded v2 request. Cash costs are configured, not inferred from HTTP success."""

from urllib.parse import unquote, urlsplit

from jsonschema import Draft202012Validator

from .catalog import MAP, ORIGIN, SEARCH, SERVICES

# Published paid replacement rate, in microdollars per credit; override for your plan.
DEFAULT_CREDIT_COST_MICROUSD = 5000


def validate_target(endpoint_id, url, mode):
    definition = SERVICES.get(endpoint_id)
    if not definition or url != ORIGIN + definition["path"] or mode not in {"test", "live"}:
        raise ValueError("Firecrawl must use its approved v2 route")


def credit_rate(value):
    if not isinstance(value, str) or not value.isascii() or not value.isdecimal():
        raise ValueError("FIRECRAWL_CREDIT_COST_MICROUSD must be a nonnegative integer")
    rate = int(value)
    if rate > 1_000_000:
        raise ValueError("Firecrawl configured credit cost is too large")
    return rate


def prepare(endpoint_id, url, mode, payload, secret):
    from openmcp.product.config import validate_service_url

    validate_target(endpoint_id, url, mode)
    definition = SERVICES[endpoint_id]
    if next(Draft202012Validator(definition["input_schema"]).iter_errors(payload), None):
        raise ValueError("Payload exceeds Firecrawl service limits")
    for name in ("query", "search"):
        if name in payload and not payload[name].strip():
            raise ValueError("Firecrawl query must not be blank")
    if not secret or any(char.isspace() for char in secret):
        raise ValueError("Firecrawl API key is invalid")
    if endpoint_id == SEARCH:
        body = {
            "query": payload["query"],
            "limit": payload.get("limit", 10),
            "sources": [payload.get("source", "web")],
            "country": payload.get("country", "US"),
            "timeout": 20000,
        }
        if "time_range" in payload:
            body["tbs"] = (
                "qdr:" + {"day": "d", "week": "w", "month": "m", "year": "y"}[payload["time_range"]]
            )
    else:
        target = payload["url"]
        validate_service_url(target, "live")
        body = {"url": target, "timeout": 20000}
        if endpoint_id == MAP:
            body.update(
                limit=payload.get("limit", 10), includeSubdomains=False, ignoreQueryParameters=True
            )
            if "search" in payload:
                body["search"] = payload["search"]
        else:
            if unquote(urlsplit(target).path).lower().endswith(".pdf"):
                raise ValueError("PDFs are not supported by the single-page Firecrawl service")
            body.update(
                formats=[definition["format"]],
                onlyMainContent=payload.get("only_main_content", True),
                parsers=[],
                proxy="basic",
                skipTlsVerification=False,
            )
    return body, "Bearer " + secret


def parse(endpoint_id, payload, body, rate):
    if not isinstance(body, dict) or body.get("success") is not True or body.get("error"):
        raise ValueError("Firecrawl did not confirm a successful result")
    data = {"provider": "Firecrawl", "endpoint_id": endpoint_id}
    reported = body.get("creditsUsed")
    reference = body.get("id")
    if endpoint_id == SEARCH:
        results = body.get("data")
        source = payload.get("source", "web")
        results = results.get(source) if isinstance(results, dict) else None
        if not isinstance(results, list) or len(results) > payload.get("limit", 10):
            raise ValueError("Firecrawl returned malformed or excessive search results")
        normalized = []
        for result in results:
            if not isinstance(result, dict) or not all(
                isinstance(result.get(field), str) for field in ("url", "title")
            ):
                raise ValueError("Firecrawl returned malformed search results")
            entry = {"url": result["url"], "title": result["title"]}
            if isinstance(result.get("description"), str):
                entry["description"] = result["description"]
            normalized.append(entry)
        if type(reported) is not int or not 0 <= reported <= 2:
            raise ValueError("Firecrawl search credit usage is missing or exceeds its limit")
        credits, basis = reported, "vendor_reported"
        data.update(query=payload["query"], source=source, results=normalized)
    elif endpoint_id == MAP:
        links = body.get("links")
        if not isinstance(links, list) or len(links) > payload.get("limit", 10):
            raise ValueError("Firecrawl returned malformed or excessive map results")
        for link in links:
            if not isinstance(link, dict) or not isinstance(link.get("url"), str):
                raise ValueError("Firecrawl returned malformed map links")
        credits, basis = 1, "documented_per_call_estimate"
        data.update(url=payload["url"], results=links)
    else:
        result = body.get("data")
        field = SERVICES[endpoint_id]["format"]
        metadata = result.get("metadata") if isinstance(result, dict) else None
        content = result.get(field) if isinstance(result, dict) else None
        if not isinstance(content, str) or not content.strip() or not isinstance(metadata, dict):
            raise ValueError("Firecrawl returned unusable page content")
        status = metadata.get("statusCode")
        if type(status) is not int or not 200 <= status < 300 or metadata.get("error"):
            # A target 403/404 page can still cost credits. Never infer a free refund.
            raise ValueError("Firecrawl returned an unsuccessful target page")
        if metadata.get("numPages", 1) != 1 or metadata.get("totalPages", 1) != 1:
            raise ValueError("Firecrawl returned more than one parsed page")
        credits, basis = 1, "documented_single_page_estimate"
        safe_metadata = {
            key: metadata[key]
            for key in (
                "title",
                "description",
                "language",
                "sourceURL",
                "statusCode",
                "contentType",
            )
            if key in metadata and isinstance(metadata[key], (str, int))
        }
        data.update(url=payload["url"], format=field, content=content, metadata=safe_metadata)
        reference = metadata.get("scrapeId") or reference
    if reported is not None:
        maximum = 2 if endpoint_id == SEARCH else 1
        if type(reported) is not int or not 0 <= reported <= maximum:
            raise ValueError("Firecrawl reported unexpected credit usage")
        credits, basis = reported, "vendor_reported"
    cost = credits * rate
    receipt = {
        "method": "api_key",
        "provider": "firecrawl",
        "status": "success",
        "credits_accounted": credits,
        "credit_count_basis": basis,
        "cash_cost_basis": "configured_credit_rate",
        "credit_cost_microusd": rate,
        "cost_microusd": cost,
    }
    if reported is not None:
        receipt["credits_consumed"] = reported
    if isinstance(reference, str) and reference:
        receipt["vendor_reference"] = reference
    return data, receipt, cost
