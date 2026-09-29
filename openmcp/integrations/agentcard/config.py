from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentCardSettings(BaseSettings):
    """Opt-in configuration. Loading the existing demo never requires these secrets."""

    model_config = SettingsConfigDict(env_prefix="AGENTCARD_", env_file=".env", extra="ignore")
    client_id: str = Field(min_length=1)
    client_secret: SecretStr
    test_mode: bool = True
    timeout_seconds: float = Field(default=30, gt=0, le=120)

    @field_validator("client_secret")
    @classmethod
    def nonempty_secret(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("AgentCard client secret is required")
        return value
