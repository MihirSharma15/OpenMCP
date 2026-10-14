"""Operator tools for DataForSEO. Secrets are read from the environment or ignored .env."""

import argparse
import asyncio
import json
import os
from decimal import Decimal

import httpx
from dotenv import load_dotenv

from .catalog import OVERVIEW, RELATED, SEARCH, provider
from .protocol import parse, prepare

SAMPLES = {
    SEARCH: {"keyword": "DataForSEO", "location_code": 2840, "language_code": "en"},
    OVERVIEW: {"keywords": ["keyword research"], "location_code": 2840, "language_code": "en"},
    RELATED: {
        "keyword": "keyword research",
        "limit": 3,
        "location_code": 2840,
        "language_code": "en",
    },
}


async def check_api(*, live=False, max_cost_usd=None):
    mode = "live" if live else "test"
    # Published prices for these specific small samples; no optional paid extras.
    estimates = {
        SEARCH: Decimal("0.002"),
        OVERVIEW: Decimal("0.01212"),
        RELATED: Decimal("0.01236"),
    }
    if live and (
        max_cost_usd is None
        or not max_cost_usd.is_finite()
        or max_cost_usd < sum(estimates.values())
    ):
        raise ValueError(
            "Live validation requires --max-cost-usd covering the $0.02648 estimated sample cost"
        )
    spent = Decimal(0)
    secret = os.environ.get("DATAFORSEO_AUTH", "")
    async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
        for service in provider(mode)["queries"]:
            endpoint_id = service["endpoint_id"]
            if live and spent + estimates[endpoint_id] > max_cost_usd:
                raise ValueError("Remaining validation budget cannot cover the next sample")
            payload = SAMPLES[endpoint_id]
            body, authorization = prepare(endpoint_id, service["url"], mode, payload, secret)
            response = await client.post(
                service["url"], json=body, headers={"Authorization": authorization}
            )
            if not response.is_success:
                try:
                    status = response.json().get("status_code")
                except (ValueError, AttributeError):
                    status = None
                status = status if type(status) is int else "unknown"
                hint = (
                    " Complete account verification in the DataForSEO dashboard."
                    if status == 40104
                    else ""
                )
                raise ValueError(
                    f"DataForSEO HTTP {response.status_code}, API status {status}.{hint}"
                )
            response.raise_for_status()
            data, receipt, cost = parse(endpoint_id, mode, payload, response.json())
            # Sandbox may return illustrative cost fields; it never bills this account.
            if live:
                spent += Decimal(cost) / 1_000_000
            print(
                json.dumps(
                    {
                        "endpoint_id": endpoint_id,
                        "items": len(data["items"]),
                        "sandbox": not live,
                        "reported_cost_usd": receipt["reported_cost_usd"],
                        "validation_spend_usd": str(spent),
                    }
                )
            )
            if live and spent > max_cost_usd:
                raise ValueError("Reported vendor cost exceeded the validation budget; stopping")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="Test three small samples; free sandbox by default")
    check.add_argument("--live", action="store_true", help="Use billable production APIs")
    check.add_argument("--max-cost-usd", type=Decimal)
    args = parser.parse_args(argv)
    load_dotenv(".env")
    try:
        asyncio.run(check_api(live=args.live, max_cost_usd=args.max_cost_usd))
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
    except Exception as exc:
        # Do not print HTTP objects or arbitrary upstream exception text.
        parser.exit(
            1, f"DataForSEO check failed ({type(exc).__name__}); credentials were not printed.\n"
        )
