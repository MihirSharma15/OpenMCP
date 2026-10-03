"""Compile declarative adapters to typed, payment-gated FastAPI handlers."""

import inspect
import json
import os
from decimal import Decimal
from typing import Annotated
from urllib.parse import urlencode

from pydantic import Field

from openmcp.config import Provider
from openmcp_provider import OpenMCPProvider, create_provider_app
from openmcp_provider.settings import ProviderSettings

from .browser import Browser
from .models import Adapter, CreateRequest, origin


class AdapterRuntime:
    def __init__(self, settings, creator_settings, network, vault, *, browser_factory=Browser):
        self.settings, self.creator_settings = settings, creator_settings
        self.network, self.vault, self.browser_factory = network, vault, browser_factory

    async def invoke(self, job, spec, payload):
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
                self.creator_settings, self.network, self.vault, job["id"]
            ) as browser:
                observation = await browser.read(url, spec.selector)
                data = observation["text"]
        if data in (None, "", {}, []):
            raise ValueError("Source returned no data")
        return {"source_url": spec.url, "data": data}

    def compile(self, job):
        request, spec = (
            CreateRequest.model_validate(job["request"]),
            Adapter.model_validate(job["adapter"]),
        )
        if origin(spec.url) not in request.origins:
            raise ValueError("Adapter origin was not authorized")
        fee = (request.price_cents * self.settings.fee_bps + 5000) // 10000
        if request.price_cents <= fee:
            raise ValueError("Provider proceeds must be positive")
        provider = OpenMCPProvider(name=spec.name, wallet=request.wallet, realm=job["id"])

        async def fetch(**kwargs):
            return await self.invoke(job, spec, kwargs)

        types = {"string": str, "integer": int, "number": float, "boolean": bool}
        annotations = {}
        parameters = []
        for parameter in spec.parameters:
            annotation = Annotated[
                types[parameter.type], Field(description=parameter.description, strict=True)
            ]
            annotations[parameter.name] = annotation
            parameters.append(
                inspect.Parameter(
                    parameter.name, inspect.Parameter.KEYWORD_ONLY, annotation=annotation
                )
            )
        fetch.__annotations__ = annotations
        fetch.__signature__ = inspect.Signature(parameters)
        provider.tool(route=f"/{job['id']}", price_usd=Decimal(request.price_cents - fee) / 100)(
            fetch
        )
        entry = Provider(
            id=job["id"],
            name=spec.name,
            description=spec.description,
            keywords=[word.lower() for word in spec.keywords],
            url=self.creator_settings.base_url.rstrip("/") + "/" + job["id"],
            price_cents=request.price_cents,
            wallet=request.wallet,
            input_schema=provider.tools[0].input_schema,
        )
        return provider, entry

    def build(self, job):
        provider, entry = self.compile(job)
        directory = self.settings.creator_database.parent / "creator" / "services" / job["id"]
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        # These files contain only validated specifications and public payment terms.
        for name, value in (
            ("adapter.json", job["adapter"]),
            ("catalog.json", [entry.model_dump(mode="json")]),
        ):
            path = directory / name
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(value, indent=2))
            os.replace(temporary, path)
        app = create_provider_app(
            [provider],
            settings=ProviderSettings(
                _env_file=None,
                state_dir=directory / "payments",
                wallets=self.settings.wallets,
                catalog=directory / "catalog.json",
                base_url=self.creator_settings.base_url,
                fee_bps=self.settings.fee_bps,
                rpc_url=self.settings.rpc_url,
            ),
        )
        return app, entry
