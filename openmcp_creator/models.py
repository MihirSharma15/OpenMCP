from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def origin(url: str) -> str:
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"https", "http"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise ValueError("An HTTP(S) URL without credentials or fragment is required")
    port = parsed.port
    host = parsed.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    suffix = f":{port}" if port and port != (443 if parsed.scheme == "https" else 80) else ""
    return f"{parsed.scheme}://{host}{suffix}"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateRequest(StrictModel):
    url: str = Field(max_length=2000)
    goal: str = Field(default="Expose useful data from this source", max_length=4000)
    price_cents: int = Field(ge=1, le=100000, strict=True)
    wallet: str = Field(default="openmcp", pattern=r"^[a-z0-9-]+$")
    allowed_origins: list[str] = Field(default_factory=list, max_length=20)
    max_steps: int = Field(default=20, ge=1, le=100)
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")

    @field_validator("url")
    @classmethod
    def valid_url(cls, value):
        origin(value)
        return value

    @field_validator("allowed_origins")
    @classmethod
    def valid_origins(cls, values):
        return sorted({origin(v) for v in values})

    @property
    def origins(self):
        return {origin(self.url), *self.allowed_origins}


class Parameter(StrictModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    type: Literal["string", "integer", "number", "boolean"] = "string"
    description: str = Field(max_length=500)

    @field_validator("name")
    @classmethod
    def safe_name(cls, value):
        import keyword

        if keyword.iskeyword(value) or value in {"request", "arguments"}:
            raise ValueError("Reserved parameter name")
        return value


class Credential(StrictModel):
    secret_name: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    header: str = Field(default="Authorization", pattern=r"^[a-zA-Z][a-zA-Z0-9-]{0,63}$")
    prefix: Literal["", "Bearer ", "Basic "] = "Bearer "

    @field_validator("header")
    @classmethod
    def safe_header(cls, value):
        if value.lower() in {"host", "cookie", "connection", "content-length", "transfer-encoding"}:
            raise ValueError("Unsupported credential header")
        return value


class Adapter(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=2000)
    keywords: list[str] = Field(min_length=1, max_length=30)
    kind: Literal["http_json", "web_text"]
    url: str = Field(max_length=2000)
    parameters: list[Parameter] = Field(default_factory=list, max_length=20)
    # Fixed URL and query-only arguments keep callers from choosing an upstream host/path.
    query: dict[str, str] = Field(default_factory=dict)
    credential: Credential | None = None
    selector: str = Field(default="body", min_length=1, max_length=300)
    sample_input: dict = Field(default_factory=dict)
    evidence_urls: list[str] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def check_adapter(self):
        origin(self.url)
        if urlsplit(self.url).query:
            raise ValueError("Use query fields; do not put credentials in the adapter URL")
        names = [p.name for p in self.parameters]
        if len(names) != len(set(names)):
            raise ValueError("Duplicate parameter")
        if not set(self.query.values()) <= set(names):
            raise ValueError("Query values must reference declared parameters")
        if self.credential and self.kind != "http_json":
            raise ValueError("Web adapters use the encrypted browser session, not header secrets")
        return self


class BrowserAction(StrictModel):
    kind: Literal["click", "fill", "capture_secret"]
    url: str = Field(max_length=2000)
    selector: str = Field(min_length=1, max_length=300)
    value: str = Field(default="", max_length=1000)
    secret_name: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    reason: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def complete(self):
        origin(self.url)
        if self.kind == "capture_secret" and not self.secret_name:
            raise ValueError("Secret capture requires a destination secret_name")
        if self.secret_name and self.value:
            raise ValueError("Use a secret reference without a literal value")
        return self


class Decision(StrictModel):
    action: Literal["browse", "interact", "finish", "needs_input"]
    url: str | None = None
    interaction: BrowserAction | None = None
    adapter: Adapter | None = None
    message: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def complete(self):
        required = {"browse": self.url, "interact": self.interaction, "finish": self.adapter}
        if self.action in required and required[self.action] is None:
            raise ValueError("Missing action payload")
        return self
