from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class CreatorSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="OPENMCP_CREATOR_", extra="ignore"
    )
    base_url: str = "http://127.0.0.1:9002"
    inference_base_url: str = "https://api.openai.com/v1"
    inference_api_key: SecretStr = SecretStr("")
    model: str = ""
    max_output_tokens: int = Field(default=6000, ge=256, le=32000)
    headless: bool = True
    # Explicit local-development exception; never accept this from a job or model.
    allow_loopback: bool = False
    browser_executable: Path | None = None
    poll_seconds: float = Field(default=2, ge=0.1, le=60)
    job_timeout_seconds: int = Field(default=600, ge=10, le=3600)
