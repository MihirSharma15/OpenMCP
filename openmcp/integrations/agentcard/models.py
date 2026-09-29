from typing import Literal

from pydantic import AliasChoices, BaseModel, Field, SecretStr


class AgentCardError(Exception):
    """Sanitized integration error; upstream payloads can contain credentials.

    An unknown mutation outcome must be reconciled, never blindly retried.
    """

    def __init__(self, code: str, *, status: int | None = None, outcome_unknown: bool = False):
        self.code = code
        self.status = status
        self.outcome_unknown = outcome_unknown
        super().__init__(f"AgentCard: {code}")


class AccessToken(BaseModel):
    access_token: SecretStr = Field(min_length=1, repr=False)
    token_type: Literal["Bearer"] = "Bearer"
    expires_in: int = Field(gt=0, strict=True)


class CredentialIdentity(BaseModel):
    organization_id: str = Field(min_length=1)
    test_mode: bool = Field(strict=True)


class ConnectAttempt(BaseModel):
    # The endpoint reference uses `id`; the issuing guide uses `connect_id`.
    id: str = Field(min_length=1, validation_alias=AliasChoices("id", "connect_id"))
    channel: Literal["email", "phone"]


class ConnectionTokens(AccessToken):
    refresh_token: SecretStr = Field(min_length=1, repr=False)


class ConnectedUser(BaseModel):
    id: str = Field(min_length=1)


class Connection(ConnectionTokens):
    user: ConnectedUser


class VerificationStatus(BaseModel):
    status: Literal[
        "awaiting_documents",
        "needs_information",
        "requires_verification",
        "pending",
        "approved",
        "rejected",
    ]
    iframe_url: str | None = Field(default=None, repr=False)


class IssuedCardRequest(BaseModel):
    """Provider input only. The application must first reserve spending authority."""

    model_config = {"extra": "forbid"}
    amount_cents: int = Field(ge=100, strict=True)
    type: Literal["single_use", "multi_use"] = "single_use"
    scope_preset: Literal["ai_labs"] | None = None

    def tool_arguments(self) -> dict:
        return {"source": "issued", **self.model_dump(exclude_none=True)}
