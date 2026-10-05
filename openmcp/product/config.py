"""Explicit account configuration; never inherits the demo signer or catalog."""

import ipaddress
import json
import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from eth_utils import is_address
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_SECRET_REF = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}")
_LOCALHOST_NAMES = {"localhost", "localhost.localdomain"}


def validate_service_url(url, mode):
    """Reject private, link-local, and localhost targets written into the URL.

    DNS rebinding is out of scope: hostnames are not resolved. Only IP literals
    and localhost names are classified. Test mode may use loopback
    (127.0.0.0/8, ::1, and localhost) so a local adapter can run. Live mode
    still requires a public HTTPS URL.
    """
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise ValueError("Service URL must be an absolute HTTP(S) URL without user info")
    if mode == "live" and parsed.scheme != "https":
        raise ValueError("Live services require HTTPS")
    if _blocked_service_host(parsed.hostname, mode):
        raise ValueError("Service URL must not target a private, link-local, or localhost address")
    return url


def _blocked_service_host(hostname, mode):
    name = hostname.lower().rstrip(".")
    if name in _LOCALHOST_NAMES or name.endswith(".localhost"):
        return mode != "test"
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    if address.is_loopback:
        return mode != "test"
    return (
        address.is_private
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
        or not address.is_global
    )


class Service(BaseModel):
    model_config = ConfigDict(extra="forbid")
    endpoint_id: str = Field(pattern=r"^[a-z0-9-]{1,100}$")
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=1000)
    keywords: list[str] = []
    url: str
    recipient: str = ""
    settlement: Literal["mpp", "api_key"] = "mpp"
    price_cents: int = Field(ge=2, le=1_000_000)
    input_schema: dict
    output_schema: dict = Field(default_factory=lambda: {"type": "object"})
    enabled: bool = False
    mode: Literal["test", "live"]
    # The provider must replay the same result for the same execution ID.
    supports_idempotency: Literal[True]

    @property
    def provider_price_cents(self):
        return self.price_cents - (self.price_cents * 1000 + 5000) // 10000

    @model_validator(mode="after")
    def validate_service(self):
        validate_service_url(self.url, self.mode)
        if self.settlement == "mpp":
            if not is_address(self.recipient):
                raise ValueError("Invalid provider recipient")
        elif self.recipient and not is_address(self.recipient):
            raise ValueError("Invalid provider recipient")
        Draft202012Validator.check_schema(self.input_schema)
        Draft202012Validator.check_schema(self.output_schema)
        return self

    def public(self):
        return {
            "endpoint_id": self.endpoint_id,
            "name": self.name,
            "description": self.description,
            "price_cents": self.price_cents,
            "provider_price_cents": self.provider_price_cents,
            "platform_fee_cents": self.price_cents - self.provider_price_cents,
            "currency": "usd_credits",
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
        }


class Provider(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider_id: str = Field(pattern=r"^[a-z0-9-]{1,100}$")
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=1000)
    secret_ref: str | None = None
    queries: list[Service]

    @model_validator(mode="after")
    def validate_provider(self):
        ref = None if self.secret_ref is None else self.secret_ref.strip()
        if ref == "":
            ref = None
        elif ref is not None and not _SECRET_REF.fullmatch(ref):
            raise ValueError("secret_ref must be an environment variable name, not the API key")
        self.secret_ref = ref
        for query in self.queries:
            if query.settlement == "api_key" and not ref:
                raise ValueError("API-key queries require a provider secret_ref")
            if query.settlement == "mpp" and not is_address(query.recipient):
                raise ValueError("Invalid provider recipient")
        return self


class ProductSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)
    mode: Literal["test", "live"] = Field(default="test", alias="OPENMCP_PRODUCT_MODE")
    database_url: str = Field(default="", alias="OPENMCP_PRODUCT_DATABASE_URL", repr=False)
    database_provider: Literal["postgres", "supabase"] = Field(
        default="postgres", alias="OPENMCP_DATABASE_PROVIDER"
    )
    database_pool_max: int = Field(default=4, ge=1, le=20, alias="OPENMCP_DATABASE_POOL_MAX")
    database_schema: str = Field(default="openmcp_product", alias="OPENMCP_PRODUCT_DATABASE_SCHEMA")
    frontend_url: str = Field(default="http://localhost:3000", alias="OPENMCP_PRODUCT_FRONTEND_URL")
    clerk_issuer: str = Field(default="", alias="CLERK_ISSUER_URL")
    clerk_audience: str | None = Field(default=None, alias="CLERK_AUDIENCE")
    clerk_authorized_parties: list[str] = Field(
        default=["http://localhost:3000"], alias="CLERK_AUTHORIZED_PARTIES"
    )
    clerk_public_key: str = Field(default="", alias="CLERK_JWT_KEY")
    stripe_key: SecretStr = Field(default=SecretStr(""), alias="STRIPE_SECRET_KEY")
    stripe_webhook_secret: SecretStr = Field(default=SecretStr(""), alias="STRIPE_WEBHOOK_SECRET")
    stripe_api_version: str = Field(default="2025-02-24.acacia", alias="STRIPE_API_VERSION")
    catalog_path: Path | None = Field(default=None, alias="OPENMCP_PRODUCT_CATALOG")
    rpc_url: str = Field(default="https://rpc.moderato.tempo.xyz", alias="OPENMCP_TREASURY_RPC_URL")
    chain_id: int = Field(default=42431, alias="OPENMCP_TREASURY_CHAIN_ID")
    token: str = Field(
        default="0x20c0000000000000000000000000000000000000", alias="OPENMCP_TREASURY_TOKEN"
    )
    treasury_key_file: Path | None = Field(default=None, alias="OPENMCP_TREASURY_KEY_FILE")
    explorer_url: str = Field(
        default="https://explore.moderato.tempo.xyz", alias="OPENMCP_TREASURY_EXPLORER_URL"
    )
    fee_reserve_cents: int = Field(default=10, ge=1, alias="OPENMCP_TREASURY_FEE_RESERVE_CENTS")
    provider_timeout: float = Field(
        default=30, gt=0, le=60, alias="OPENMCP_PRODUCT_PROVIDER_TIMEOUT"
    )
    worker_interval: float = Field(default=2, gt=0, le=30, alias="OPENMCP_PRODUCT_WORKER_INTERVAL")
    retry_seconds: int = Field(default=15, ge=1, le=300, alias="OPENMCP_PRODUCT_RETRY_SECONDS")
    max_attempts: int = Field(default=5, ge=1, le=20, alias="OPENMCP_PRODUCT_MAX_ATTEMPTS")
    top_up_presets_cents: tuple[int, ...] = (500, 1000, 2500, 5000)

    def catalog(self):
        """Operator catalog file. None means startup must leave stored rows alone."""
        if self.catalog_path is None:
            return None
        items = json.loads(self.catalog_path.read_text())
        if not isinstance(items, list):
            raise ValueError("Catalog must be a JSON array")
        flat = bool(items) and all(
            isinstance(item, dict) and "endpoint_id" in item and "queries" not in item
            for item in items
        )
        if flat:
            services = [Service.model_validate(item) for item in items]
            providers = [
                Provider(
                    provider_id=service.endpoint_id,
                    name=service.name,
                    description=service.description,
                    queries=[service],
                )
                for service in services
            ]
        else:
            providers = [Provider.model_validate(item) for item in items]
        provider_ids = [provider.provider_id for provider in providers]
        endpoint_ids = [query.endpoint_id for provider in providers for query in provider.queries]
        if len(set(provider_ids)) != len(provider_ids):
            raise ValueError("Provider IDs must be unique")
        if len(set(endpoint_ids)) != len(endpoint_ids):
            raise ValueError("Service IDs must be unique")
        return providers

    def services(self):
        providers = self.catalog() or []
        return {
            query.endpoint_id: query
            for provider in providers
            for query in provider.queries
            if query.enabled and query.mode == self.mode
        }

    def validate_startup(self, *, require_treasury_key=True):
        self.validate_database()
        if not self.clerk_issuer.startswith("https://") or not self.clerk_authorized_parties:
            raise ValueError("CLERK_ISSUER_URL and CLERK_AUTHORIZED_PARTIES are required")
        key = self.stripe_key.get_secret_value()
        prefixes = (f"sk_{self.mode}_", f"rk_{self.mode}_")
        if not key.startswith(prefixes):
            raise ValueError(f"Stripe server key must match explicit {self.mode} mode")
        if not self.stripe_webhook_secret.get_secret_value().startswith("whsec_"):
            raise ValueError("STRIPE_WEBHOOK_SECRET is required")
        if self.chain_id != (4217 if self.mode == "live" else 42431):
            raise ValueError("Treasury chain must match explicit product mode")
        if not is_address(self.token):
            raise ValueError("Treasury token must be an approved six-decimal USD token address")
        if self.mode == "live":
            if self.token.lower() != "0x20c000000000000000000000b9537d11c60e8b50":
                raise ValueError("The live pilot settles only in Tempo mainnet USDC")
            if "moderato" in self.rpc_url or self.explorer_url != "https://explore.tempo.xyz":
                raise ValueError("Live treasury URLs must identify Tempo mainnet")
            urls = [
                self.frontend_url,
                self.rpc_url,
                self.explorer_url,
                *self.clerk_authorized_parties,
            ]
            if not all(url.startswith("https://") for url in urls):
                raise ValueError("Live origins, explorer and RPC must use HTTPS")
            if require_treasury_key and (
                not self.treasury_key_file or not self.treasury_key_file.is_file()
            ):
                raise ValueError("Live mode needs a private treasury key file")
            if not self.services():
                raise ValueError("Live mode needs an explicitly enabled live provider")

    def validate_database(self):
        from openmcp.database import DatabaseManager

        if not self.database_url.startswith(("postgresql://", "postgres://")):
            raise ValueError("OPENMCP_PRODUCT_DATABASE_URL must point to persistent PostgreSQL")
        DatabaseManager.validate_dsn(self.database_url, self.database_provider)
