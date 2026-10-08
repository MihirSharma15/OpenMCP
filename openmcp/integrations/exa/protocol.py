"""One bounded Exa request; response cost estimates are not invoices."""

from decimal import Decimal, InvalidOperation

from jsonschema import Draft202012Validator

from .catalog import CONTENTS, ORIGIN, SEARCH, SERVICES


def validate_target(endpoint_id, url, mode):
    definition = SERVICES.get(endpoint_id)
    if not definition or url != ORIGIN + definition["path"] or mode not in {"test", "live"}:
        raise ValueError("Exa must use its approved REST route")


def prepare(endpoint_id, url, mode, payload, secret):
    from openmcp.product.config import validate_service_url

    validate_target(endpoint_id, url, mode)
    if next(Draft202012Validator(SERVICES[endpoint_id]["input_schema"]).iter_errors(payload), None):
        raise ValueError("Payload exceeds Exa service limits")
    if not secret or any(c.isspace() for c in secret):
        raise ValueError("Exa API key is invalid")
    if endpoint_id == SEARCH:
        if not payload["query"].strip():
            raise ValueError("Exa query must not be blank")
        body = {"query": payload["query"], "type": "auto", "numResults": payload.get("limit", 10)}
        if "category" in payload:
            body["category"] = payload["category"]
    else:
        validate_service_url(payload["url"], "live")
        body = {
            "ids": [payload["url"]],
            "text": {"maxCharacters": payload.get("max_characters", 10000)},
            "highlights": False,
            "summary": False,
            "subpages": 0,
            "livecrawlTimeout": 10000,
        }
    return body, secret


def parse(endpoint_id, payload, body):
    if not isinstance(body, dict) or body.get("error"):
        raise ValueError("Exa returned an error")
    reference = body.get("requestId")
    if not isinstance(reference, str) or not reference:
        raise ValueError("Exa request ID is missing")
    reported = body.get("costDollars")
    total = reported.get("total") if isinstance(reported, dict) else None
    if type(total) not in (int, float):
        raise ValueError("Exa cost estimate is missing")
    try:
        units = Decimal(str(total)) * 1_000_000
        if (
            not units.is_finite()
            or units < 0
            or units != units.to_integral_value()
            or units > SERVICES[endpoint_id]["max_cost_microusd"]
        ):
            raise ValueError("Exa cost estimate exceeds the approved bounds")
        cost = int(units)
    except InvalidOperation as exc:
        raise ValueError("Exa cost estimate is invalid") from exc
    results = body.get("results")
    limit = payload.get("limit", 10) if endpoint_id == SEARCH else 1
    if not isinstance(results, list) or len(results) > limit:
        raise ValueError("Exa result count is invalid")
    if endpoint_id == CONTENTS:
        statuses = body.get("statuses")
        if (
            not isinstance(statuses, list)
            or len(statuses) != 1
            or not isinstance(statuses[0], dict)
            or statuses[0].get("status") != "success"
            or statuses[0].get("error")
        ):
            raise ValueError("Exa did not confirm successful page retrieval")
        if len(results) != 1:
            raise ValueError("Exa page content is missing")
    normalized = []
    for result in results:
        if not isinstance(result, dict) or not isinstance(result.get("url"), str):
            raise ValueError("Exa returned malformed results")
        entry = {
            k: result[k]
            for k in ("url", "title", "id", "publishedDate", "author")
            if isinstance(result.get(k), str)
        }
        if endpoint_id == CONTENTS:
            text = result.get("text")
            if (
                not isinstance(text, str)
                or not text.strip()
                or len(text) > payload.get("max_characters", 10000)
            ):
                raise ValueError("Exa page text is missing or exceeds its limit")
            entry["text"] = text
        normalized.append(entry)
    data = {"provider": "Exa", "endpoint_id": endpoint_id, "results": normalized}
    receipt = {
        "method": "api_key",
        "status": "success",
        "provider": "exa",
        "vendor_reference": reference,
        "cost_microusd": cost,
        "cost_basis": "vendor_reported_estimate",
    }
    return data, receipt, cost
