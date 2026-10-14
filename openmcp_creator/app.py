"""Single-operator Creator research and authenticated generated-service hosting."""

import asyncio
import hmac
import json
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from jsonschema import Draft202012Validator
from pydantic import Field

from openmcp.errors import OpenMCPError

from .adapter import AdapterRuntime, input_schema
from .inference import Inference
from .models import Adapter, CreateRequest, StrictModel
from .network import PublicHTTP
from .settings import CreatorSettings
from .store import CreatorStore
from .vault import Vault
from .worker import Worker


class ResumeRequest(StrictModel):
    approve_action: bool = False
    regenerate: bool = False
    note: str = Field(default="", max_length=4000)


def public_job(job):
    return {
        k: v
        for k, v in job.items()
        if k not in {"observations", "approved_action", "action_started"}
    }


def create_app(settings=None, *, start_worker=True, store=None, runtime=None):
    settings = settings or CreatorSettings()
    if (
        min(
            len(settings.admin_token.get_secret_value()), len(settings.api_token.get_secret_value())
        )
        < 16
    ):
        raise ValueError(
            "Configure separate Creator admin and service tokens (at least 16 characters)"
        )
    if settings.admin_token.get_secret_value() == settings.api_token.get_secret_value():
        raise ValueError("Creator admin and service tokens must differ")
    store = store or CreatorStore(settings.database)
    owns_network = runtime is None
    network = (
        PublicHTTP(allow_loopback=settings.allow_loopback) if owns_network else runtime.network
    )
    vault = Vault(settings.state_dir) if runtime is None else runtime.vault
    runtime = runtime or AdapterRuntime(settings, network, vault)
    inference = Inference(settings)
    worker = Worker(store, settings, inference, network, vault, runtime)

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(worker.run()) if start_worker else None
        try:
            yield
        finally:
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            await inference.close()
            if owns_network:
                await network.close()

    app = FastAPI(title="OpenMCP API Creator", lifespan=lifespan)
    app.state.store, app.state.worker, app.state.runtime = store, worker, runtime

    @app.middleware("http")
    async def authorize(request, call_next):
        if request.url.path == "/health":
            return await call_next(request)
        token = settings.admin_token if request.url.path.startswith("/jobs") else settings.api_token
        expected = "Bearer " + token.get_secret_value()
        if not hmac.compare_digest(
            request.headers.get("Authorization", "").encode(), expected.encode()
        ):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > 131_072:
                return JSONResponse({"error": "request_too_large"}, status_code=413)
            chunks.append(chunk)
        request._body = b"".join(chunks)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(OpenMCPError)
    async def error(request, exc):
        return JSONResponse({"error": exc.as_dict()}, status_code=exc.status)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/jobs", status_code=202)
    async def submit(body: CreateRequest):
        return public_job(store.submit(body))

    @app.get("/jobs")
    async def jobs():
        return {"jobs": [public_job(j) for j in store.list()]}

    @app.get("/jobs/{job_id}")
    async def job(job_id: str):
        return public_job(store.get(job_id))

    @app.post("/jobs/{job_id}/resume")
    async def resume(job_id: str, body: ResumeRequest):
        return public_job(
            store.resume(
                job_id,
                approve_action=body.approve_action,
                regenerate=body.regenerate,
                note=body.note,
            )
        )

    @app.post("/{endpoint_id}")
    async def execute(endpoint_id: str, request: Request):
        job = store.get(endpoint_id)
        if job["state"] != "ready":
            raise OpenMCPError("not_ready", "Service has not passed validation", 409)
        key = request.headers.get("Idempotency-Key", "")
        if not 1 <= len(key) <= 200 or any(not 33 <= ord(c) <= 126 for c in key):
            raise OpenMCPError("invalid_key", "Supply an Idempotency-Key", 422)
        spec = Adapter.model_validate(job["adapter"])
        try:
            payload = await request.json()
        except ValueError:
            raise OpenMCPError("invalid_payload", "JSON input required", 422) from None
        if next(Draft202012Validator(input_schema(spec)).iter_errors(payload), None):
            raise OpenMCPError("invalid_payload", "Input does not match service schema", 422)
        previous = store.begin_call(endpoint_id, key, payload)
        if previous is not None:
            return previous
        try:
            data = await runtime.invoke(job, spec, payload)
            if len(json.dumps(data, allow_nan=False).encode()) > 1_000_000:
                raise ValueError("Response too large")
            store.finish_call(key, data)
        except Exception:
            raise OpenMCPError(
                "call_pending", "Source call needs review; reuse this key", 503
            ) from None
        return data

    return app
