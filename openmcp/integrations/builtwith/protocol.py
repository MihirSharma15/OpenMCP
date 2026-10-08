"""Fixed free GET routes; keys never come from agent inputs."""

from jsonschema import Draft202012Validator

from .catalog import ORIGIN, SERVICES, SUMMARY


def validate_target(endpoint_id, url, mode):
    if (
        endpoint_id not in SERVICES
        or url != ORIGIN + SERVICES[endpoint_id]["path"]
        or mode not in {"test", "live"}
    ):
        raise ValueError("BuiltWith must use an approved free route")


def prepare(endpoint_id, url, mode, payload, secret):
    validate_target(endpoint_id, url, mode)
    schema = {
        "type": "object",
        "properties": SERVICES[endpoint_id]["properties"],
        "required": SERVICES[endpoint_id]["required"],
        "additionalProperties": False,
    }
    if next(Draft202012Validator(schema).iter_errors(payload), None):
        raise ValueError("Payload exceeds BuiltWith service limits")
    if not secret or not secret.isascii() or any(c.isspace() for c in secret):
        raise ValueError("BuiltWith API key is invalid")
    return (
        {"LOOKUP": payload["domain"]} if endpoint_id == SUMMARY else {"TECH": payload["technology"]}
    )


def counts(row, fields):
    if not isinstance(row, dict) or any(type(row.get(k)) is not int or row[k] < 0 for k in fields):
        raise ValueError("BuiltWith counts are invalid")
    return {k: row[k] for k in fields}


def named_counts(row):
    if not isinstance(row, dict) or not isinstance(row.get("name"), str) or not row["name"]:
        raise ValueError("BuiltWith category name is missing")
    return {"name": row["name"], **counts(row, ("live", "dead", "latest", "oldest"))}


def parse(endpoint_id, payload, body):
    if not isinstance(body, dict) or any(
        k.lower() in {"error", "errors"} and v for k, v in body.items()
    ):
        raise ValueError("BuiltWith returned an error")
    data = {
        "provider": "BuiltWith",
        "endpoint_id": endpoint_id,
        "attribution": {"name": "BuiltWith", "url": "https://builtwith.com"},
    }
    if endpoint_id == SUMMARY:
        domain, groups = body.get("domain"), body.get("groups")
        requested = payload["domain"]
        if (
            not isinstance(domain, str)
            or not (requested == domain or requested.endswith("." + domain))
            or not isinstance(groups, list)
            or len(groups) > 500
        ):
            raise ValueError("BuiltWith domain summary is missing or mismatched")
        data.update(domain=domain, **counts(body, ("first", "last")), timestamp_unit="milliseconds")
        data["groups"] = []
        for group in groups:
            normalized = named_counts(group)
            categories = group.get("categories")
            if not isinstance(categories, list) or len(categories) > 1000:
                raise ValueError("BuiltWith categories are invalid")
            normalized["categories"] = [named_counts(c) for c in categories]
            data["groups"].append(normalized)
    else:
        tech = body.get("Tech")
        if (
            not isinstance(tech, dict)
            or not isinstance(tech.get("name"), str)
            or not tech["name"]
            or tech["name"].replace(" ", "-").lower() != payload["technology"].lower()
        ):
            raise ValueError("BuiltWith technology result is missing or mismatched")
        coverage = tech.get("coverage")
        if not isinstance(coverage, dict) or not coverage:
            raise ValueError("BuiltWith technology coverage is missing")
        categories = tech.get("categories")
        if not isinstance(categories, list) or not all(isinstance(c, str) for c in categories):
            raise ValueError("BuiltWith technology categories are invalid")
        data["technology"] = {
            k: tech[k]
            for k in (
                "name",
                "description",
                "tag",
                "categories",
                "is_premium",
                "link",
                "trends_link",
            )
            if k in tech
        }
        data["technology"]["coverage"] = counts(coverage, tuple(coverage))
    return (
        data,
        {
            "method": "api_key",
            "provider": "builtwith",
            "status": "success",
            "cost_microusd": 0,
            "cost_basis": "free_api",
            "requests_accounted": 1,
        },
        0,
    )
