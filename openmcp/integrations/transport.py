"""Small request/result types shared by provider adapters and the account worker."""

from dataclasses import dataclass, field
from typing import Any


class Rejected(ValueError):
    """Conclusive evidence that the vendor rejected the request without billing."""


@dataclass
class Request:
    url: str
    method: str = "POST"
    headers: dict = field(default_factory=dict)
    json: Any = None
    content: bytes | None = None
    params: dict | None = None
    context: Any = None
    require_success: bool = True

    def options(self):
        result = {"headers": self.headers}
        if self.content is not None:
            result["content"] = self.content
        else:
            result["json"] = self.json
        if self.params is not None:
            result["params"] = self.params
        return result
