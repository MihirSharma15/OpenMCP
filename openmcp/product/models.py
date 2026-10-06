"""Small shared types for the account API and accounting boundaries."""

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, StrictInt


def now():
    return datetime.now(timezone.utc)


def identifier(prefix):
    return f"{prefix}_{uuid.uuid4().hex}"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def fingerprint(value):
    return hashlib.sha256(canonical(value)).hexdigest()


class ProductError(Exception):
    def __init__(self, code, message, status=400, retryable=False):
        self.code, self.message, self.status, self.retryable = code, message, status, retryable
        super().__init__(message)


@dataclass(frozen=True)
class Principal:
    account_id: str
    agent_id: str | None = None
    credential_id: str | None = None


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TopUpInput(Input):
    amount_cents: StrictInt = Field(ge=500, le=5000)


class AgentInput(Input):
    name: str = Field(min_length=1, max_length=80)
    spend_limit_cents: StrictInt = Field(ge=1, le=1_000_000)
    expires_at: datetime | None = None


class DiscoverInput(Input):
    query: str = Field(default="", max_length=4000)
    budget_cents: StrictInt | None = Field(default=None, ge=0)


class ExecuteInput(Input):
    endpoint_id: str = Field(min_length=1, max_length=100)
    payload: dict
    max_price_cents: StrictInt = Field(ge=1, le=1_000_000)
