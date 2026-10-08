"""Validate the approved request and return a link plus fractional-cent cost."""

from decimal import ROUND_CEILING, Decimal
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator

from .catalog import INPUT_SCHEMA, MARKDOWN, MAX_COST_MICROUSD, URL


def validate_target(endpoint_id, url, mode):
    if endpoint_id != MARKDOWN or url != URL or mode not in {"test", "live"}:
        raise ValueError("API2PDF must use its approved Markdown REST route")


def prepare(endpoint_id, url, mode, payload, secret):
    validate_target(endpoint_id, url, mode)
    if next(Draft202012Validator(INPUT_SCHEMA).iter_errors(payload), None):
        raise ValueError(
            "Payload exceeds API2PDF limits: self-contained Markdown without HTML or images"
        )
    if not secret or any(c.isspace() for c in secret):
        raise ValueError("API2PDF API key is invalid")
    return {
        "markdown": payload["markdown"],
        "fileName": payload.get("filename", "report.pdf"),
        "inline": False,
        "useCustomStorage": False,
        "options": {"landscape": False, "printBackground": False},
    }, secret


def parse(endpoint_id, payload, body):
    from openmcp.product.config import validate_service_url

    if endpoint_id != MARKDOWN or not isinstance(body, dict):
        raise ValueError("API2PDF returned an invalid result")
    # Current REST replies use PascalCase; SDKs also document camelCase.
    result = {k[0].lower() + k[1:]: v for k, v in body.items() if k}
    if result.get("success") is not True or result.get("error"):
        raise ValueError("API2PDF did not confirm successful conversion")
    reference, file_url = result.get("responseId"), result.get("fileUrl")
    if not isinstance(reference, str) or not 1 <= len(reference) <= 200:
        raise ValueError("API2PDF response ID is missing")
    if not isinstance(file_url, str) or not 1 <= len(file_url) <= 4096:
        raise ValueError("API2PDF file URL is missing")
    validate_service_url(file_url, "live")
    if urlsplit(file_url).port not in (None, 443):
        raise ValueError("API2PDF file URL must use HTTPS on port 443")
    for field, maximum in (("cost", Decimal("0.03")), ("mbOut", Decimal("5"))):
        value = result.get(field)
        if type(value) not in (int, float) or not Decimal(str(value)).is_finite():
            raise ValueError("API2PDF cost or output size is missing or invalid")
        if not 0 <= Decimal(str(value)) <= maximum:
            raise ValueError("API2PDF cost or output size exceeds review bounds")
    # Vendor Cost may have sub-microdollar precision; round upward, never drop it.
    cost = int((Decimal(str(result["cost"])) * 1_000_000).to_integral_value(rounding=ROUND_CEILING))
    if cost > MAX_COST_MICROUSD:
        raise ValueError("API2PDF cost exceeds review bounds")
    data = {
        "provider": "API2PDF",
        "endpoint_id": endpoint_id,
        "file_url": file_url,
        "filename": payload.get("filename", "report.pdf"),
        "retention_seconds": 86400,
        "vendor_reference": reference,
    }
    receipt = {
        "method": "api_key",
        "provider": "api2pdf",
        "status": "success",
        "vendor_reference": reference,
        "cost_microusd": cost,
        "cost_basis": "vendor_reported_rounded_up",
        "vendor_cost_usd": str(result["cost"]),
        "output_megabytes": result["mbOut"],
    }
    return data, receipt, cost
