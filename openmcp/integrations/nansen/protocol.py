"""Fixed one-credit Nansen requests and bounded results; no automatic resubmission."""

import math
import re
from copy import deepcopy
from datetime import date

from jsonschema import Draft202012Validator

from .catalog import BALANCES, EVM_CHAINS, ORIGIN, SCREENER, SERVICES, TRANSACTIONS

DEFAULT_CREDIT_COST_MICROUSD = 1000  # $10 / 10,000 purchased credits; included credits first.


class Rejected(ValueError):
    """Vendor explicitly confirmed a failed request deducted zero credits."""


def validate_target(endpoint_id, url, mode):
    spec = SERVICES.get(endpoint_id)
    if not spec or url != ORIGIN + spec["path"] or mode not in {"test", "live"}:
        raise ValueError("Nansen must use an approved one-credit REST route")


def credit_rate(value):
    if (
        not isinstance(value, str)
        or not re.fullmatch(r"[0-9]{1,5}", value)
        or not 0 <= int(value) <= 20000
    ):
        raise ValueError("Nansen credit cost must be integer microUSD between 0 and 20000")
    return int(value)


def validate_address(address, chain):
    if chain in EVM_CHAINS:
        valid = (
            re.fullmatch(r"0x[0-9a-fA-F]{40}", address) is not None and int(address[2:], 16) != 0
        )
    else:
        alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
        valid = all(c in alphabet for c in address)
        if valid:
            number = 0
            for character in address:
                number = number * 58 + alphabet.index(character)
            valid = (number.bit_length() + 7) // 8 + len(address) - len(address.lstrip("1")) == 32
    if not valid:
        raise ValueError("Wallet address does not match its selected chain")


def prepare(endpoint_id, url, mode, payload, secret):
    validate_target(endpoint_id, url, mode)
    if next(Draft202012Validator(SERVICES[endpoint_id]["input_schema"]).iter_errors(payload), None):
        raise ValueError("Payload exceeds Nansen service limits")
    if not secret or not secret.isascii() or any(c.isspace() for c in secret):
        raise ValueError("Nansen API key is invalid")
    body = {"pagination": {"page": payload.get("page", 1), "per_page": payload.get("limit", 20)}}
    if endpoint_id == SCREENER:
        filters = deepcopy(payload.get("filters", {}))
        for value in filters.values():
            if isinstance(value, dict) and value.get("min", 0) > value.get("max", math.inf):
                raise ValueError("Nansen numeric filter minimum exceeds maximum")
            if isinstance(value, dict) and any(not math.isfinite(v) for v in value.values()):
                raise ValueError("Nansen numeric filter must be finite")
        filters["trader_type"] = "all"
        body.update(
            chains=payload["chains"],
            timeframe=payload["timeframe"],
            filters=filters,
            order_by=[
                {
                    "field": payload.get("sort_by", "volume"),
                    "direction": payload.get("direction", "DESC"),
                }
            ],
        )
    else:
        validate_address(payload["address"], payload["chain"])
        body.update(chain=payload["chain"], address=payload["address"], hide_spam_token=True)
        if endpoint_id == TRANSACTIONS:
            start, end = (date.fromisoformat(payload["date"][k]) for k in ("from", "to"))
            if not 0 <= (end - start).days <= 31:
                raise ValueError(
                    "Nansen transaction date range must be ordered and at most 31 days"
                )
            body.update(
                date=payload["date"], order_by=[{"field": "block_timestamp", "direction": "DESC"}]
            )
    return body, secret


def header_credits(headers, key):
    value = headers.get(key)
    if value is None:
        return None
    if not re.fullmatch(r"[0-9]{1,8}", value):
        raise ValueError("Nansen credit header is invalid")
    return int(value)


def parse(endpoint_id, payload, body, headers, status=200, rate=DEFAULT_CREDIT_COST_MICROUSD):
    used = header_credits(headers, "x-nansen-credits-used")
    quoted = header_credits(headers, "x-nansen-credits-cost")
    if not 200 <= status < 300:
        if (
            status in {400, 401, 402, 403, 404, 422, 429}
            and used == 0
            and isinstance(body, dict)
            and body.get("error")
            and body.get("code")
            and type(body.get("status")) is int
            and body["status"] == status
        ):
            raise Rejected("Nansen rejected the request and confirmed zero credits deducted.")
        raise ValueError("Nansen request outcome needs review")
    if used not in {None, 0, 1} or quoted not in {None, 0, 1}:
        raise ValueError("Nansen request exceeded its approved one-credit cost")
    if not isinstance(body, dict) or body.get("error") or body.get("errors"):
        raise ValueError("Nansen returned an error instead of data")
    reference = headers.get("x-request-id")
    if not isinstance(reference, str) or not 1 <= len(reference) <= 200:
        raise ValueError("Nansen request reference is missing")
    rows, page = body.get("data"), body.get("pagination")
    if (
        not isinstance(rows, list)
        or len(rows) > payload.get("limit", 20)
        or not isinstance(page, dict)
        or type(page.get("page")) is not int
        or page["page"] != payload.get("page", 1)
        or type(page.get("per_page")) is not int
        or not len(rows) <= page["per_page"] <= payload.get("limit", 20)
        or type(page.get("is_last_page")) is not bool
    ):
        raise ValueError("Nansen pagination or result count is invalid")
    normalized = [normalize(endpoint_id, payload, row) for row in rows]
    count = 1 if used is None else used
    cost = count * rate
    data = {
        "provider": "Nansen",
        "endpoint_id": endpoint_id,
        "data": normalized,
        "pagination": {
            "page": page["page"],
            "per_page": page["per_page"],
            "returned": len(rows),
            "is_last_page": page["is_last_page"],
            "next_page": None if page["is_last_page"] else page["page"] + 1,
        },
        "attribution": {"name": "Powered by Nansen API", "url": "https://nansen.ai"},
    }
    receipt = {
        "method": "api_key",
        "provider": "nansen",
        "status": "success",
        "vendor_reference": reference,
        "credits_used": count,
        "credit_basis": "vendor_reported" if used is not None else "documented_tariff_estimate",
        "cost_microusd": cost,
        "cost_basis": "credit_replacement_cost_estimate",
        "credit_cost_microusd": rate,
    }
    return data, receipt, cost


def normalize(endpoint_id, payload, row):
    if not isinstance(row, dict):
        raise ValueError("Nansen result row is invalid")
    chains = payload["chains"] if endpoint_id == SCREENER else [payload["chain"]]
    if row.get("chain") not in chains:
        raise ValueError("Nansen returned an unexpected chain")
    required = (
        ("transaction_hash", "block_timestamp", "method", "source_type")
        if endpoint_id == TRANSACTIONS
        else ("token_address", "token_symbol")
    )
    if any(not isinstance(row.get(k), str) or not row[k] for k in required):
        raise ValueError("Nansen result identifiers are missing")
    if endpoint_id == BALANCES:
        if not isinstance(row.get("address"), str) or (
            row["address"].lower() != payload["address"].lower()
            if payload["chain"] in EVM_CHAINS
            else row["address"] != payload["address"]
        ):
            raise ValueError("Nansen balance belongs to a different wallet")
    fields = {
        BALANCES: (
            "chain",
            "address",
            "token_address",
            "token_symbol",
            "token_name",
            "token_amount",
            "price_usd",
            "value_usd",
        ),
        TRANSACTIONS: (
            "chain",
            "transaction_hash",
            "block_timestamp",
            "method",
            "source_type",
            "volume_usd",
        ),
        SCREENER: (
            "chain",
            "token_address",
            "token_symbol",
            "token_age_days",
            "token_age_hours",
            "token_deployment_date",
            "market_cap_usd",
            "liquidity",
            "price_usd",
            "price_change",
            "fdv",
            "fdv_mc_ratio",
            "buy_volume",
            "sell_volume",
            "volume",
            "netflow",
            "inflow_fdv_ratio",
            "outflow_fdv_ratio",
        ),
    }[endpoint_id]
    result = {k: row[k] for k in fields if k in row and row[k] is not None}
    strings = {
        "chain",
        "address",
        "token_address",
        "token_symbol",
        "token_name",
        "transaction_hash",
        "block_timestamp",
        "method",
        "source_type",
        "token_deployment_date",
    }
    for k, value in result.items():
        if (k in strings and not isinstance(value, str)) or (
            k not in strings and (type(value) not in {int, float} or not math.isfinite(value))
        ):
            raise ValueError("Nansen result fields have invalid types")
    if endpoint_id == TRANSACTIONS:
        for key in ("tokens_sent", "tokens_received"):
            transfers = row.get(key)
            if transfers is None:
                continue
            if not isinstance(transfers, list) or len(transfers) > 1000:
                raise ValueError("Nansen token transfers are invalid")
            result[key] = []
            for transfer in transfers:
                if (
                    not isinstance(transfer, dict)
                    or not isinstance(transfer.get("token_symbol"), str)
                    or type(transfer.get("token_amount")) not in {int, float}
                    or not math.isfinite(transfer["token_amount"])
                ):
                    raise ValueError("Nansen token transfer is malformed")
                # Keep transfer facts; omit wallet labels and unknown vendor additions.
                item = {
                    k: transfer[k]
                    for k in (
                        "token_symbol",
                        "token_amount",
                        "token_address",
                        "chain",
                        "from_address",
                        "to_address",
                        "price_usd",
                        "value_usd",
                    )
                    if k in transfer
                }
                for field, value in item.items():
                    if value is None and field in {"price_usd", "value_usd"}:
                        continue
                    if field in {"token_amount", "price_usd", "value_usd"}:
                        if type(value) not in {int, float} or not math.isfinite(value):
                            raise ValueError("Nansen transfer amounts are invalid")
                    elif not isinstance(value, str):
                        raise ValueError("Nansen transfer identifiers are invalid")
                result[key].append(item)
    return result
