"""Request and response bodies for the v1 API."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from openmcp.domain.credits import ChargeStatus, DebitOutcome, DepositOutcome


class DepositRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount_cents: int = Field(strict=True, gt=0)
    charge_id: str = Field(min_length=1)
    status: ChargeStatus


class DebitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    price_cents: int = Field(strict=True, gt=0)
    idempotency_key: str = Field(min_length=1)


class CreditsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    available_cents: int
    currency: Literal["usd_credits"] = "usd_credits"


class DepositResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    available_cents: int
    amount_cents: int
    charge_id: str
    outcome: DepositOutcome


class DebitResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    available_cents: int
    price_cents: int
    idempotency_key: str
    outcome: DebitOutcome


class AccountCreatedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_id: str
    credential_id: str
    secret: str
    scopes: list[str]


class CreateAgentRequest(BaseModel):
    """No account id. The owner credential selects the account."""

    model_config = ConfigDict(extra="forbid")


class AgentCreatedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str
    account_id: str


class CredentialCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expires_at: datetime | None = None


class CredentialCreatedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_id: str
    agent_id: str
    credential_id: str
    secret: str
    scopes: list[str]


class CredentialRevokedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    credential_id: str
    agent_id: str
    revoked: bool
