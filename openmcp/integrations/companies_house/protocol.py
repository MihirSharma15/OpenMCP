"""Fixed GET routes and bounded public-register results; no filing writes."""

import base64

from jsonschema import Draft202012Validator

from .catalog import FILINGS, OFFICERS, ORIGIN, PROFILE, SEARCH, SERVICES


def validate_target(endpoint_id, url, mode):
    definition = SERVICES.get(endpoint_id)
    if not definition or url != ORIGIN + definition["path"] or mode not in {"test", "live"}:
        raise ValueError("Companies House must use an approved public-data route")


def request(endpoint_id, url, mode, payload):
    validate_target(endpoint_id, url, mode)
    if next(Draft202012Validator(SERVICES[endpoint_id]["input_schema"]).iter_errors(payload), None):
        raise ValueError("Payload exceeds Companies House service limits")
    params = {}
    if endpoint_id == SEARCH:
        params["q"] = payload["query"].strip()
    if endpoint_id != PROFILE:
        params.update(
            items_per_page=payload.get("items_per_page", 20),
            start_index=payload.get("start_index", 0),
        )
    # Only this validated company identifier can be substituted into the fixed route.
    target = url.replace("{company_number}", payload.get("company_number", ""))
    return target, params


def prepare(endpoint_id, url, mode, payload, secret):
    target, params = request(endpoint_id, url, mode, payload)
    if not secret or not secret.isascii() or any(c.isspace() for c in secret) or ":" in secret:
        raise ValueError("Companies House API key is invalid")
    authorization = "Basic " + base64.b64encode((secret + ":").encode()).decode()
    return target, params, authorization


def pick(value, fields):
    return {k: value[k] for k in fields if k in value}


def parse(endpoint_id, payload, body):
    if not isinstance(body, dict) or "errors" in body or "error" in body:
        raise ValueError("Companies House did not return public-register data")
    data = {
        "provider": "Companies House",
        "endpoint_id": endpoint_id,
        "attribution": {
            "name": "Companies House",
            "url": "https://find-and-update.company-information.service.gov.uk/",
        },
    }
    if endpoint_id == PROFILE:
        if (
            body.get("company_number") != payload["company_number"]
            or not isinstance(body.get("company_name"), str)
            or not body["company_name"]
            or not isinstance(body.get("company_status"), str)
        ):
            raise ValueError("Companies House profile is missing or mismatched")
        data["company"] = pick(
            body,
            (
                "company_number",
                "company_name",
                "company_status",
                "company_status_detail",
                "type",
                "jurisdiction",
                "date_of_creation",
                "date_of_cessation",
                "registered_office_address",
                "sic_codes",
                "accounts",
                "confirmation_statement",
                "annual_return",
                "previous_company_names",
                "has_charges",
                "has_insolvency_history",
                "registered_office_is_in_dispute",
                "undeliverable_registered_office_address",
                "can_file",
                "foreign_company_details",
                "branch_company_details",
            ),
        )
    else:
        rows = body.get("items")
        if (
            not isinstance(rows, list)
            or len(rows) > payload.get("items_per_page", 20)
            or type(body.get("total_results", body.get("total_count"))) is not int
            or body.get("total_results", body.get("total_count")) < len(rows)
            or type(body.get("start_index")) is not int
            or body["start_index"] != payload.get("start_index", 0)
            or type(body.get("items_per_page")) is not int
            or not 1 <= body["items_per_page"] <= payload.get("items_per_page", 20)
        ):
            raise ValueError("Companies House page metadata is invalid")
        required = {
            SEARCH: ("company_number", "title"),
            OFFICERS: ("name", "officer_role"),
            FILINGS: ("transaction_id", "type", "date", "description"),
        }[endpoint_id]
        fields = {
            SEARCH: (
                "company_number",
                "title",
                "company_status",
                "company_type",
                "date_of_creation",
                "date_of_cessation",
                "address",
                "address_snippet",
                "description",
                "description_identifier",
            ),
            OFFICERS: (
                "name",
                "officer_role",
                "appointed_on",
                "appointed_before",
                "resigned_on",
                "nationality",
                "occupation",
                "country_of_residence",
                "address",
            ),
            FILINGS: (
                "transaction_id",
                "type",
                "date",
                "category",
                "description",
                "description_values",
                "pages",
                "paper_filed",
                "annotations",
                "associated_filings",
                "resolutions",
            ),
        }[endpoint_id]
        if not all(
            isinstance(row, dict) and all(isinstance(row.get(k), str) and row[k] for k in required)
            for row in rows
        ):
            raise ValueError("Companies House page items are invalid")
        data["items"] = [pick(row, fields) for row in rows]
        total = body.get("total_results", body.get("total_count"))
        data["pagination"] = {
            "start_index": body["start_index"],
            "items_per_page": body["items_per_page"],
            "returned": len(rows),
            "total_results": total,
            "next_start_index": body["start_index"] + len(rows)
            if rows and body["start_index"] + len(rows) < total
            else None,
        }
        if endpoint_id == OFFICERS:
            data.update(pick(body, ("active_count", "resigned_count", "inactive_count")))
    if endpoint_id != SEARCH:
        data["company_number"] = payload["company_number"]
    return (
        data,
        {
            "method": "api_key",
            "provider": "companies-house",
            "status": "success",
            "cost_microusd": 0,
            "cost_basis": "free_public_data",
            "requests_accounted": 1,
        },
        0,
    )
