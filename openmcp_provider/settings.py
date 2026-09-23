"""Configuration for the local MPP provider service."""

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProviderSettings(BaseSettings):
    """Provider-only settings; no wallet private keys or OpenMCP secrets."""

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
    )

    state_dir: Path = Field(
        default=Path(".openmcp/provider"),
        alias="OPENMCP_PROVIDER_STATE",
    )
    wallets: Path = Field(
        default=Path(".openmcp/wallets"),
        alias="OPENMCP_WALLETS",
    )
    catalog: Path = Field(
        default=Path("catalog/providers.json"),
        alias="OPENMCP_CATALOG",
    )
    fee_bps: int = Field(default=1000, ge=0, lt=10_000, alias="OPENMCP_FEE_BPS")
    rpc_url: str = Field(
        default="https://rpc.moderato.tempo.xyz",
        alias="TEMPO_RPC_URL",
    )
    chain_id: Literal[42431] = Field(default=42431, alias="TEMPO_CHAIN_ID")

    @field_validator("chain_id", mode="before")
    @classmethod
    def parse_chain_id(cls, value: object) -> int:
        return int(value)


def resolve_provider_settings(settings: object | None = None) -> ProviderSettings:
    """Accept provider settings or the main application's test settings."""

    if settings is None:
        return ProviderSettings()
    if isinstance(settings, ProviderSettings):
        return settings

    database = Path(getattr(settings, "database"))
    return ProviderSettings(
        _env_file=None,
        state_dir=getattr(settings, "provider_state_dir", database.parent / "provider"),
        wallets=getattr(settings, "wallets"),
        catalog=getattr(settings, "catalog"),
        fee_bps=getattr(settings, "fee_bps"),
        rpc_url=getattr(settings, "rpc_url"),
        chain_id=getattr(settings, "chain_id"),
    )
