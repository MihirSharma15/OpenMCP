"""Operator catalog: three one-credit, read-only Nansen services."""

from copy import deepcopy

ORIGIN = "https://api.nansen.ai"
BALANCES = "nansen-wallet-balances"
TRANSACTIONS = "nansen-wallet-transactions"
SCREENER = "nansen-token-screener"
EVM_CHAINS = ["ethereum", "base", "arbitrum", "optimism", "polygon", "bnb", "avalanche"]
CHAINS = EVM_CHAINS + ["solana"]
PAGE = {"type": "integer", "minimum": 1, "maximum": 10000, "default": 1}
LIMIT = {"type": "integer", "minimum": 1, "maximum": 100, "default": 20}
ADDRESS = {
    "type": "string",
    "minLength": 32,
    "maxLength": 44,
    "not": {"const": "0x0000000000000000000000000000000000000000"},
    "description": "EVM: 0x followed by 40 hex characters; the zero/burn address is unsupported. Solana: a base58-encoded 32-byte public key.",
}
DATE = {"type": "string", "pattern": r"^[0-9]{4}-[0-9]{2}-[0-9]{2}(?![\s\S])"}


def schema(properties, required=()):
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


WALLET = {"chain": {"enum": CHAINS}, "address": ADDRESS, "page": PAGE, "limit": LIMIT}
RANGE = schema({"min": {"type": "number", "minimum": 0}, "max": {"type": "number", "minimum": 0}})
SERVICES = {
    BALANCES: {
        "path": "/api/v1/profiler/address/current-balance",
        "name": "Wallet token balances",
        "description": "Read one page of token balances for address on one supported chain. EVM addresses use 0x plus 40 hex characters; Solana uses a base58 32-byte public key. Returns token amounts and available prices/USD values; spam tokens are hidden. page defaults to 1; limit is 1–100, default 20. Follow pagination.next_page for more records; each additional page is a separate purchase, and one page is not the wallet's entire portfolio.",
        "input_schema": schema(WALLET, ["chain", "address"]),
    },
    TRANSACTIONS: {
        "path": "/api/v1/profiler/address/transactions",
        "name": "Wallet transactions",
        "description": "Read one page of indexed wallet transactions for chain and address, newest first. Requires date.from and date.to as YYYY-MM-DD, ordered and at most 31 days apart. Returns hashes, timestamps and available token transfers/transaction metadata; spam tokens are hidden. page defaults to 1; limit is 1–100, default 20. Follow pagination.next_page for another separately purchased page. Results are not guaranteed to be a complete wallet history.",
        "input_schema": schema(
            {**WALLET, "date": schema({"from": DATE, "to": DATE}, ["from", "to"])},
            ["chain", "address", "date"],
        ),
    },
    SCREENER: {
        "path": "/api/v1/token-screener",
        "name": "Token screener",
        "description": "Screen current token metrics for chains (1–5 supported chains) and timeframe (5m, 10m, 1h, 6h, 24h, 7d or 30d). Returns available price, volume, liquidity and market metrics. Optional filters: liquidity, market_cap_usd, volume min/max ranges, include_stablecoins and include_native_tokens. sort_by defaults to volume and direction to DESC; page defaults to 1; limit is 1–100, default 20. Follow pagination.next_page for another separately purchased page. Current general-market snapshot only; no historical backtesting or proprietary Smart Money feed.",
        "input_schema": schema(
            {
                "chains": {
                    "type": "array",
                    "items": {"enum": CHAINS},
                    "minItems": 1,
                    "maxItems": 5,
                    "uniqueItems": True,
                },
                "timeframe": {"enum": ["5m", "10m", "1h", "6h", "24h", "7d", "30d"]},
                "page": PAGE,
                "limit": LIMIT,
                "filters": schema(
                    {
                        "liquidity": RANGE,
                        "market_cap_usd": RANGE,
                        "volume": RANGE,
                        "include_stablecoins": {"type": "boolean"},
                        "include_native_tokens": {"type": "boolean"},
                    }
                ),
                "sort_by": {
                    "enum": [
                        "volume",
                        "liquidity",
                        "market_cap_usd",
                        "price_change",
                        "netflow",
                        "token_age_days",
                    ],
                    "default": "volume",
                },
                "direction": {"enum": ["ASC", "DESC"], "default": "DESC"},
            },
            ["chains", "timeframe"],
        ),
    },
}


def provider(mode="test"):
    if mode not in {"test", "live"}:
        raise ValueError("Choose test or live account mode")
    return {
        "provider_id": "nansen",
        "name": "Nansen",
        "description": "Read-only indexed blockchain data through wallet token balances, dated wallet transaction history and current token market screening. Supported chains: ethereum, base, arbitrum, optimism, polygon, bnb, avalanche and solana. No proprietary Smart Money feed. This OpenMCP integration cannot place trades, submit orders, sign transactions or transfer funds.",
        "secret_ref": "NANSEN_API_KEY",
        "queries": [
            {
                "endpoint_id": identifier,
                "name": "Nansen " + spec["name"],
                "description": spec["description"]
                + " Read-only data query: cannot place trades, submit orders, sign transactions or transfer funds."
                + " Flat $0.02 per successful request. Attribute returned data to Nansen (https://nansen.ai).",
                "url": ORIGIN + spec["path"],
                "keywords": ["blockchain", "crypto", "wallet", "tokens", "transactions"],
                "adapter": "nansen",
                "settlement": "api_key",
                "price_cents": 2,
                "input_schema": deepcopy(spec["input_schema"]),
                "output_schema": {
                    "type": "object",
                    "properties": {
                        "provider": {"const": "Nansen"},
                        "endpoint_id": {"const": identifier},
                        "data": {"type": "array", "maxItems": 100, "items": {"type": "object"}},
                        "pagination": {"type": "object"},
                        "attribution": {"type": "object"},
                    },
                    "required": ["provider", "endpoint_id", "data", "pagination", "attribution"],
                },
                "enabled": True,
                "mode": mode,
                "supports_idempotency": True,
            }
            for identifier, spec in SERVICES.items()
        ],
    }
