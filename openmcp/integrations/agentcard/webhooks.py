"""Verify the documented timestamped HMAC envelope before a durable inbox write."""

import hashlib
import hmac
import re
import time
from typing import Any

from pydantic import BaseModel, Field, SecretStr, ValidationError

from .models import AgentCardError


class WebhookEvent(BaseModel):
    id: str = Field(min_length=1)
    type: str = Field(min_length=1)
    created: int = Field(ge=0, strict=True)
    livemode: bool = Field(strict=True)
    data: dict[str, Any] = Field(repr=False)


def verify_webhook(
    raw_body: bytes,
    signature: str,
    secret: SecretStr,
    *,
    test_mode: bool = True,
    now: float | None = None,
    tolerance_seconds: int = 300,
) -> WebhookEvent:
    """Authenticate bytes and mode. Caller must deduplicate event IDs durably.

    Persist/enqueue before acknowledging. A valid signature does not establish
    OpenMCP ownership; resolve known provider object IDs inside the inbox worker.
    """
    if not secret.get_secret_value() or tolerance_seconds <= 0:
        raise ValueError("A nonempty webhook secret and positive tolerance are required")
    fields = {}
    for part in signature.split(","):
        key, separator, value = part.strip().partition("=")
        if not separator or key in fields:
            raise AgentCardError("invalid_webhook_signature")
        fields[key] = value
    timestamp, digest = fields.get("t", ""), fields.get("v1", "")
    if not re.fullmatch(r"[0-9]{1,12}", timestamp) or not re.fullmatch(r"[a-fA-F0-9]{64}", digest):
        raise AgentCardError("invalid_webhook_signature")
    current = time.time() if now is None else now
    if abs(current - int(timestamp)) > tolerance_seconds:
        raise AgentCardError("expired_webhook_signature")
    expected = hmac.new(
        secret.get_secret_value().encode(),
        timestamp.encode() + b"." + raw_body,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, digest.lower()):
        raise AgentCardError("invalid_webhook_signature")
    try:
        event = WebhookEvent.model_validate_json(raw_body)
    except ValidationError:
        raise AgentCardError("invalid_webhook_event") from None
    if event.livemode != (not test_mode):
        raise AgentCardError("mode_mismatch")
    return event
