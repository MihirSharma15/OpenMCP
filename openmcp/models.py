from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DiscoverRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=4000)
    budget_cents: int = Field(ge=0, strict=True)


class ExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str
    endpoint_id: str
    payload: dict[str, Any]
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")
    max_price_cents: int = Field(ge=0, strict=True)
    budget_cents: int = Field(ge=0, strict=True)


class ResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    budget_cents: int | None = Field(default=None, ge=1, strict=True)


class OpenMCPError(Exception):
    def __init__(self, code: str, message: str, status: int = 400, retryable: bool = False):
        self.code = code
        self.message = message
        self.status = status
        self.retryable = retryable
        super().__init__(message)

    def as_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "retryable": self.retryable}
