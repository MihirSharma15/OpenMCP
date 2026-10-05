"""Explicit account configuration; never inherits the demo signer or catalog."""

import json
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from eth_utils import is_address
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Service(BaseModel):
    model_config = ConfigDict(extra="forbid")
    endpoint_id: str = Field(pattern=r"^[a-z0-9-]{1,100}$")
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=1000)
    keywords: list[str] = []
    url: str
    recipient: str
    price_cents: int = Field(ge=2, le=1_000_000)
    input_schema: dict
    enabled: bool = False
    mode: Literal["test", "live"]
    # The provider must replay the same result for the same execution ID.
    supports_idempotency: Literal[True]

    @property
    def provider_price_cents(self):
        return self.price_cents - (self.price_cents * 1000 + 5000) // 10000

    @model_validator(mode="after")
    def validate_service(self):
        url = urlsplit(self.url)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.fragment:
            raise ValueError("Service URL must be an absolute HTTP(S) URL without user info")
        if self.mode == "live" and url.scheme != "https":
            raise ValueError("Live services require HTTPS")
        if not is_address(self.recipient):
            raise ValueError("Invalid provider recipient")
        Draft202012Validator.check_schema(self.input_schema)
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
        }


class ProductSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)
    mode: Literal["test", "live"] = Field(default="test", alias="OPENMCP_PRODUCT_MODE")
    database_url: str = Field(default="", alias="OPENMCP_PRODUCT_DATABASE_URL")
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

    def services(self):
        items = [] if self.catalog_path is None else json.loads(self.catalog_path.read_text())
        services = [Service.model_validate(item) for item in items]
        if len({item.endpoint_id for item in services}) != len(services):
            raise ValueError("Service IDs must be unique")
        return {
            item.endpoint_id: item for item in services if item.enabled and item.mode == self.mode
        }

    def validate_startup(self):
        if not self.database_url.startswith(("postgresql://", "postgres://")):
            raise ValueError("OPENMCP_PRODUCT_DATABASE_URL must point to persistent PostgreSQL")
        if not self.clerk_issuer.startswith("https://") or not self.clerk_authorized_parties:
            raise ValueError("CLERK_ISSUER_URL and CLERK_AUTHORIZED_PARTIES are required")
        key = self.stripe_key.get_secret_value()
        prefix = "sk_live_" if self.mode == "live" else "sk_test_"
        if not key.startswith(prefix):
            raise ValueError(f"Stripe secret must match explicit {self.mode} mode")
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
            if not self.treasury_key_file or not self.treasury_key_file.is_file():
                raise ValueError("Live mode needs a private treasury key file")
            if not self.services():
                raise ValueError("Live mode needs an explicitly enabled live provider")
