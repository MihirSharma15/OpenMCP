import asyncio
import hmac
from contextlib import AsyncExitStack, asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import Field

from openmcp.config import Settings
from openmcp.models import OpenMCPError

from .adapter import AdapterRuntime
from .inference import Inference
from .models import CreateRequest, StrictModel
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


def create_app(settings=None, creator_settings=None, *, start_worker=True):
    settings, creator_settings = settings or Settings(), creator_settings or CreatorSettings()
    if len(settings.api_token.get_secret_value()) < 16:
        raise ValueError("Initialize the OpenMCP connection token")
    store = CreatorStore(settings.creator_database)
    vault = Vault(settings.creator_database.parent / "creator")
    network = PublicHTTP(allow_loopback=creator_settings.allow_loopback)
    inference = Inference(creator_settings)
    runtime = AdapterRuntime(settings, creator_settings, network, vault)
    worker = Worker(store, settings, creator_settings, inference, network, vault, runtime)
    services, lock = {}, asyncio.Lock()

    @asynccontextmanager
    async def lifespan(app):
        async with AsyncExitStack() as stack:
            app.state.stack = stack
            stack.push_async_callback(network.close)
            stack.push_async_callback(inference.close)
            task = asyncio.create_task(worker.run()) if start_worker else None
            try:
                yield
            finally:
                if task:
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task

    app = FastAPI(title="OpenMCP API Creator", lifespan=lifespan)
    app.state.store, app.state.worker, app.state.runtime = store, worker, runtime

    @app.middleware("http")
    async def authorize(request: Request, call_next):
        if request.url.path.startswith("/jobs"):
            expected = "Bearer " + settings.api_token.get_secret_value()
            if not hmac.compare_digest(
                request.headers.get("Authorization", "").encode(), expected.encode()
            ):
                return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)

    @app.exception_handler(OpenMCPError)
    async def error(request, exc):
        return JSONResponse({"error": exc.as_dict()}, status_code=exc.status)

    @app.get("/health")
    async def health():
        return {"status": "ok", "services": len(store.services())}

    @app.post("/jobs", status_code=202)
    async def submit(body: CreateRequest):
        if body.wallet not in settings.addresses():
            raise OpenMCPError("invalid_wallet", "Unknown receiving wallet", 422)
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
            raise OpenMCPError("not_ready", "Service has not passed validation", 404)
        async with lock:
            if endpoint_id not in services:
                service, _ = runtime.build(job)
                await app.state.stack.enter_async_context(service.router.lifespan_context(service))
                services[endpoint_id] = service
        # Preserve original request bytes, payment headers and response headers.
        import httpx
        from fastapi import Response

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=services[endpoint_id]),
            base_url=creator_settings.base_url,
        ) as client:
            response = await client.post(
                f"/{endpoint_id}", content=await request.body(), headers=dict(request.headers)
            )
        return Response(
            response.content, status_code=response.status_code, headers=dict(response.headers)
        )

    return app
