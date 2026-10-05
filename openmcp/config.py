import json
from pathlib import Path
from typing import Literal

from eth_utils import is_address
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

CHAIN_ID = 42431
TOKEN = "0x20c0000000000000000000000000000000000000"
EXPLORER = "https://explore.moderato.tempo.xyz"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)
    api_token: SecretStr = Field(default=SecretStr(""), alias="OPENMCP_API_TOKEN")
    payment_secret: SecretStr = Field(default=SecretStr(""), alias="OPENMCP_MPP_SECRET")
    budget_cents: int = Field(default=1500, ge=1, alias="OPENMCP_BUDGET_CENTS")
    fee_bps: int = Field(default=1000, ge=0, lt=10000, alias="OPENMCP_FEE_BPS")
    database: Path = Field(default=Path(".openmcp/mpp.sqlite3"), alias="OPENMCP_DATABASE")
    # Product credit ledger. Empty does not connect. A URL is migrated when the app is created.
    product_database_url: str = Field(default="", alias="OPENMCP_LEGACY_DATABASE_URL")
    catalog: Path = Field(default=Path("catalog/providers.json"), alias="OPENMCP_CATALOG")
    wallets: Path = Field(default=Path(".openmcp/wallets"), alias="OPENMCP_WALLETS")
    base_url: str = Field(default="http://127.0.0.1:8000", alias="OPENMCP_BASE_URL")
    rpc_url: str = Field(default="https://rpc.moderato.tempo.xyz", alias="TEMPO_RPC_URL")
    chain_id: Literal[42431] = Field(default=42431, alias="TEMPO_CHAIN_ID")

    @field_validator("chain_id", mode="before")
    @classmethod
    def parse_chain_id(cls, value):
        return int(value)

    cors_origins: list[str] = Field(
        default=["http://localhost:3000", "http://127.0.0.1:3000"], alias="OPENMCP_CORS_ORIGINS"
    )
    provider_timeout_seconds: float = Field(default=60, gt=0, le=180)

    @property
    def creator_database(self) -> Path:
        return self.database.parent / "creator.sqlite3"

    def addresses(self) -> dict[str, str]:
        path = self.wallets / "public.json"
        if not path.exists():
            raise ValueError("Run `uv run openmcp init` to create the five demo wallets")
        result = json.loads(path.read_text())
        if not all(isinstance(v, str) and is_address(v) for v in result.values()):
            raise ValueError("Invalid address in wallet public.json")
        return result


class Provider(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    name: str
    description: str
    keywords: list[str]
    url: HttpUrl
    price_cents: int = Field(ge=1)
    wallet: str
    input_schema: dict


def load_catalog(path: Path) -> dict[str, Provider]:
    providers = [Provider.model_validate(item) for item in json.loads(path.read_text())]
    if len({p.id for p in providers}) != len(providers):
        raise ValueError("Provider IDs must be unique")
    for provider in providers:
        Draft202012Validator.check_schema(provider.input_schema)
    return {p.id: p for p in providers}
