"""Execute validated declarative adapters and describe them for the account catalog."""

from urllib.parse import urlencode

from jsonschema import Draft202012Validator

from openmcp.product.config import Provider

from .browser import Browser
from .models import Adapter, CreateRequest, origin


def input_schema(spec):
    return {
        "type": "object",
        "properties": {
            p.name: {"type": p.type, "description": p.description} for p in spec.parameters
        },
        "required": [p.name for p in spec.parameters],
        "additionalProperties": False,
    }


def provider_definition(job, settings, mode):
    if job["state"] != "ready":
        raise ValueError("Validate the Creator job before publishing")
    spec = Adapter.model_validate(job["adapter"])
    request = CreateRequest.model_validate(job["request"])
    return Provider.model_validate(
        {
            "provider_id": job["id"],
            "name": spec.name,
            "description": spec.description,
            "secret_ref": "OPENMCP_CREATOR_API_TOKEN",
            "queries": [
                {
                    "endpoint_id": job["id"],
                    "name": spec.name,
                    "description": spec.description,
                    "keywords": spec.keywords,
                    "url": settings.base_url.rstrip("/") + "/" + job["id"],
                    "settlement": "api_key",
                    "adapter": "creator",
                    "price_cents": request.price_cents,
                    "input_schema": input_schema(spec),
                    "output_schema": {"type": "object", "required": ["source_url", "data"]},
                    "enabled": False,
                    "mode": mode,
                    "supports_idempotency": True,
                }
            ],
        }
    )


class AdapterRuntime:
    def __init__(self, settings, network, vault, *, browser_factory=Browser):
        self.settings, self.network, self.vault = settings, network, vault
        self.browser_factory = browser_factory

    async def invoke(self, job, spec, payload):
        Draft202012Validator(input_schema(spec)).validate(payload)
        request = CreateRequest.model_validate(job["request"])
        if origin(spec.url) not in request.origins:
            raise ValueError("Adapter origin was not authorized")
        query = urlencode({key: payload[value] for key, value in spec.query.items()})
        url = spec.url + ("?" + query if query else "")
        if spec.kind == "http_json":
            headers = {}
            if spec.credential:
                credential = spec.credential
                headers[credential.header] = credential.prefix + self.vault.secret(
                    job["id"], credential.secret_name, spec.url
                )
            response = await self.network.request(
                url, headers=headers, allowed_origin=origin(spec.url)
            )
            response.raise_for_status()
            data = response.json()
        else:
            async with self.browser_factory(
                self.settings, self.network, self.vault, job["id"]
            ) as browser:
                observation = await browser.read(url, spec.selector)
                data = observation["text"]
        if data in (None, "", {}, []):
            raise ValueError("Source returned no data")
        return {"source_url": spec.url, "data": data}
