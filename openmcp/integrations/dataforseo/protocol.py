"""Translate a bounded OpenMCP purchase into DataForSEO's documented task protocol."""

import base64
import binascii
from decimal import Decimal, InvalidOperation

from jsonschema import Draft202012Validator

from .catalog import OVERVIEW, RELATED, SEARCH, SERVICES


class Rejected(ValueError):
    """The vendor explicitly rejected a task and reported zero cost."""


def validate_target(endpoint_id, url, mode):
    service = SERVICES.get(endpoint_id)
    origin = "https://sandbox.dataforseo.com" if mode == "test" else "https://api.dataforseo.com"
    if not service or url != origin + service["path"]:
        raise ValueError("DataForSEO endpoint must use its approved route and mode-specific origin")


def prepare(endpoint_id, url, mode, payload, secret):
    validate_target(endpoint_id, url, mode)
    errors = Draft202012Validator(SERVICES[endpoint_id]["input_schema"]).iter_errors(payload)
    if next(errors, None) or any(
        isinstance(value, str) and not value.strip() for value in payload.values()
    ):
        raise ValueError("Payload exceeds the supported DataForSEO service limits")
    try:
        login, password = base64.b64decode(secret, validate=True).decode().split(":", 1)
        if not login or not password or any(c.isspace() for c in login + password):
            raise ValueError()
    except (ValueError, UnicodeError, binascii.Error) as exc:
        raise ValueError("DataForSEO credential must encode API login:password") from exc
    task = {"location_code": 2840, "language_code": "en", **payload}
    if endpoint_id == SEARCH:
        # DataForSEO decodes '+' as space; preserve a literal plus in plain queries.
        task["keyword"] = task["keyword"].replace("+", "%2B")
        task.update(depth=10, max_crawl_pages=1)
        task.setdefault("device", "desktop")
    else:
        task.update(include_clickstream_data=False, include_serp_info=False)
        if endpoint_id == RELATED:
            task.setdefault("limit", 100)
            task.update(depth=3, include_seed_keyword=False)
    return [task], "Basic " + secret


def cost_microusd(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise ValueError("Missing DataForSEO cost")
    try:
        cost = Decimal(str(value)) * 1_000_000
        if not cost.is_finite() or cost < 0 or cost > 1_000_000_000_000:
            raise ValueError("Invalid DataForSEO cost")
        if cost != cost.to_integral_value():
            raise ValueError("DataForSEO cost needs more than six decimal places")
        return int(cost)
    except InvalidOperation as exc:
        raise ValueError("Invalid DataForSEO cost") from exc


def _rejection(code, cost):
    if type(code) is int and 40000 <= code < 50000 and cost == 0:
        raise Rejected(f"DataForSEO rejected the request (status {code}); credits returned.")


def parse(endpoint_id, mode, payload, body):
    """Require explicit completed-task status, preserve cost, and return bounded data."""
    total_cost = cost_microusd(body.get("cost"))
    tasks = body.get("tasks")
    # A top-level rejection may have no task. Contradictory task/cost fields
    # are ambiguous and must not trigger an automatic credit refund.
    if tasks is None or tasks == []:
        _rejection(body.get("status_code"), total_cost)
    if body.get("status_code") != 20000 or not isinstance(tasks, list) or len(tasks) != 1:
        raise ValueError("DataForSEO did not return one completed task")
    task = tasks[0]
    if not isinstance(task, dict):
        raise ValueError("Malformed DataForSEO task")
    cost = cost_microusd(task.get("cost"))
    if cost != total_cost:
        raise ValueError("DataForSEO task and total costs disagree")
    _rejection(task.get("status_code"), cost)
    task_id = task.get("id")
    if task.get("status_code") != 20000 or not isinstance(task_id, str) or not task_id:
        raise ValueError("DataForSEO task is not completed")
    results = task.get("result")
    if not isinstance(results, list) or len(results) != 1 or not isinstance(results[0], dict):
        raise ValueError("DataForSEO returned an unusable result")
    result = results[0]
    items = result.get("items")
    if items is None and result.get("items_count") == 0:
        items = []
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise ValueError("DataForSEO returned malformed items")
    limit = (
        10
        if endpoint_id == SEARCH
        else (len(payload["keywords"]) if endpoint_id == OVERVIEW else payload.get("limit", 100))
    )
    if endpoint_id == SEARCH:
        normalized = [
            _fields(item, "title", "url", "domain", "description", "rank_absolute", "rank_group")
            for item in items
            if item.get("type") == "organic"
        ][:limit]
    else:
        normalized = []
        for item in items[:limit]:
            item = item.get("keyword_data", {}) if endpoint_id == RELATED else item
            if not isinstance(item, dict):
                raise ValueError("Malformed DataForSEO keyword data")
            info = item.get("keyword_info") or {}
            properties = item.get("keyword_properties") or {}
            intent = item.get("search_intent_info") or {}
            if not all(isinstance(value, dict) for value in (info, properties, intent)):
                raise ValueError("Malformed DataForSEO keyword metrics")
            normalized.append(
                _fields(item, "keyword")
                | _fields(
                    info,
                    "search_volume",
                    "cpc",
                    "competition",
                    "competition_level",
                    "monthly_searches",
                    "last_updated_time",
                )
                | _fields(properties, "keyword_difficulty")
                | {"search_intent": intent.get("main_intent")}
            )
    data = {
        "provider": "DataForSEO",
        "endpoint_id": endpoint_id,
        "is_demo_data": mode == "test",
        "query": {"location_code": 2840, "language_code": "en", **payload},
        "items": normalized,
    }
    if endpoint_id == SEARCH:
        data["serp_features"] = sorted(
            {item["type"] for item in items if isinstance(item.get("type"), str)}
        )
        data.update(_fields(result, "datetime", "check_url"))
    actual_cost = 0 if mode == "test" else cost
    receipt = {
        "method": "api_key",
        "provider": "dataforseo",
        "status": "success",
        "task_id": task_id,
        "reported_cost_usd": str(Decimal(cost) / 1_000_000),
        "cost_usd": str(Decimal(actual_cost) / 1_000_000),
        "cost_microusd": actual_cost,
        "sandbox": mode == "test",
    }
    return data, receipt, actual_cost


def _fields(value, *names):
    return {name: value[name] for name in names if name in value}
