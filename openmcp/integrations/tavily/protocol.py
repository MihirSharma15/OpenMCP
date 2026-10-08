"""Bound requests and preserve vendor-reported credits separately from cash cost."""

from jsonschema import Draft202012Validator

from .catalog import ADVANCED, EXTRACT_ADVANCED, MAP, SEARCH, SERVICES

# Published paid replacement rate, in microdollars per credit; override for your plan.
DEFAULT_CREDIT_COST_MICROUSD = 8000


class Rejected(ValueError):
    """All requested extraction targets failed, with explicit zero vendor usage."""


def validate_target(endpoint_id, url, mode):
    service = SERVICES.get(endpoint_id)
    if not service or url != "https://api.tavily.com" + service[1] or mode not in {"test", "live"}:
        raise ValueError("Tavily must use its approved service route")


def credit_rate(value):
    if not isinstance(value, str) or not value.isascii() or not value.isdecimal():
        raise ValueError("TAVILY_CREDIT_COST_MICROUSD must be a nonnegative integer")
    rate = int(value)
    if rate > 1_000_000:
        raise ValueError("Tavily configured credit cost is too large")
    return rate


def prepare(endpoint_id, url, mode, payload, secret):
    from openmcp.product.config import validate_service_url

    validate_target(endpoint_id, url, mode)
    depth, path, _, inputs, *_ = SERVICES[endpoint_id]
    if next(Draft202012Validator(inputs).iter_errors(payload), None):
        raise ValueError("Payload exceeds Tavily service limits")
    if "query" in payload and not payload["query"].strip():
        raise ValueError("Tavily query must not be blank")
    if not secret or any(char.isspace() for char in secret):
        raise ValueError("Tavily API key is invalid")
    body = {**payload, "include_usage": True}
    if path == "/search":
        body.update(
            max_results=payload.get("max_results", 10),
            search_depth=depth,
            topic=payload.get("topic", "general"),
            auto_parameters=False,
            include_answer=False,
            include_raw_content=False,
            include_images=False,
            chunks_per_source=3,
        )
    else:
        urls = payload["urls"] if path == "/extract" else [payload["url"]]
        for target in urls:
            # The worker only calls Tavily. This also rejects obvious private target literals;
            # DNS resolution and fetched-page redirects remain Tavily's responsibility.
            validate_service_url(target, "live")
        if path == "/extract":
            body.update(extract_depth=depth, format="markdown", include_images=False, timeout=10)
            if "query" in body:
                body["chunks_per_source"] = 3
        else:
            body.update(
                limit=payload.get("limit", 20),
                max_depth=1,
                max_breadth=20,
                allow_external=False,
                timeout=20,
            )
    return body, "Bearer " + secret


def parse(payload, body, rate, endpoint_id=SEARCH):
    if not isinstance(body, dict) or body.get("error") or body.get("detail"):
        raise ValueError("Tavily returned an error")
    usage, request_id, results = body.get("usage"), body.get("request_id"), body.get("results")
    if (
        not isinstance(usage, dict)
        or type(usage.get("credits")) is not int
        or not isinstance(request_id, str)
        or not request_id
        or not isinstance(results, list)
    ):
        raise ValueError("Tavily returned malformed results or missing usage")
    credits = usage["credits"]
    depth, path, *_ = SERVICES[endpoint_id]
    data = {"provider": "Tavily", "endpoint_id": endpoint_id}
    if path == "/search":
        expected = 2 if endpoint_id == ADVANCED else 1
        if credits != expected or len(results) > payload.get("max_results", 10):
            raise ValueError("Tavily search exceeded its result or credit limit")
        normalized = []
        for result in results:
            if not isinstance(result, dict) or not all(
                isinstance(result.get(field), str) for field in ("title", "url", "content")
            ):
                raise ValueError("Tavily returned malformed search results")
            normalized.append({field: result[field] for field in ("title", "url", "content")})
        data.update(query=payload["query"], results=normalized)
    elif path == "/extract":
        failed = body.get("failed_results")
        maximum = 2 if endpoint_id == EXTRACT_ADVANCED else 1
        if not isinstance(failed, list) or not 0 <= credits <= maximum:
            raise ValueError("Tavily extraction exceeded its credit limit")
        returned = []
        for result in results:
            if (
                not isinstance(result, dict)
                or not all(isinstance(result.get(field), str) for field in ("url", "raw_content"))
                or not result["raw_content"].strip()
            ):
                raise ValueError("Tavily returned malformed extracted content")
            returned.append(result["url"])
        for result in failed:
            if not isinstance(result, dict) or not all(
                isinstance(result.get(field), str) for field in ("url", "error")
            ):
                raise ValueError("Tavily returned malformed extraction failures")
            returned.append(result["url"])
        if len(returned) != len(set(returned)) or set(returned) != set(payload["urls"]):
            raise ValueError("Tavily extraction did not account for every requested URL")
        if not results:
            if credits == 0:
                raise Rejected("Tavily could not extract any requested URL; zero usage reported.")
            raise ValueError("Tavily charged for an unusable extraction")
        data.update(
            results=[{"url": r["url"], "content": r["raw_content"]} for r in results],
            failed_results=[{"url": r["url"], "error": r["error"]} for r in failed],
            partial_success=bool(failed),
        )
    elif endpoint_id == MAP:
        limit = payload.get("limit", 20)
        if (
            not 0 <= credits <= (limit + 9) // 10
            or len(results) > limit
            or not all(
                isinstance(url, str) and url.startswith(("https://", "http://")) for url in results
            )
        ):
            raise ValueError("Tavily map exceeded its result or credit limit")
        data.update(url=payload["url"], results=results)
    cost = credits * rate
    return (
        data,
        {
            "method": "api_key",
            "provider": "tavily",
            "status": "success",
            "request_id": request_id,
            "credits_consumed": credits,
            "cost_basis": "configured_credit_rate",
            "credit_cost_microusd": rate,
            "cost_microusd": cost,
        },
        cost,
    )
