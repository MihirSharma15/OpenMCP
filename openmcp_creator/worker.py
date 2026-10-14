import asyncio
import json

from .browser import Browser
from .models import Adapter, BrowserAction, CreateRequest, origin


class Worker:
    def __init__(
        self,
        store,
        settings,
        inference,
        network,
        vault,
        runtime,
        *,
        browser_factory=Browser,
    ):
        self.store, self.settings = store, settings
        self.inference, self.network, self.vault, self.runtime = inference, network, vault, runtime
        self.browser_factory = browser_factory

    async def run_once(self):
        claimed = self.store.claim(self.settings.job_timeout_seconds + 60)
        if claimed is None:
            return False
        job, lease = claimed
        try:
            async with asyncio.timeout(self.settings.job_timeout_seconds):
                await self.process(job, lease)
        except asyncio.CancelledError:
            # The lease makes shutdown/restart recoverable. In-flight external actions
            # are sent to needs_input by claim(), never automatically replayed.
            raise
        except Exception as exc:
            # SDK exceptions can contain authorization headers, source data or keys.
            message = (
                f"{type(exc).__name__}: check source access, Creator configuration and credentials"
            )
            if job["action_started"]:
                job.update(action_started=False, approved_action=None)
                message = "Browser action outcome uncertain; inspect the account before resuming"
            self.store.save(job, lease, "needs_input", message)
        return True

    async def process(self, job, lease):
        request = CreateRequest.model_validate(job["request"])
        if job["adapter"]:
            await self.validate_sample(job, lease)
            return
        async with self.browser_factory(
            self.settings, self.network, self.vault, job["id"]
        ) as browser:
            if job["approved_action"]:
                action = BrowserAction.model_validate(job["approved_action"])
                job["action_started"] = True
                self.store.save(job, lease, message="Executing approved browser action")
                observation = await browser.interact(action, request.origins)
                job.update(action_started=False, approved_action=None)
                self.observe(job, observation)
                self.store.save(job, lease, message="Approved browser action completed")
            if not job["observations"]:
                self.observe(job, await browser.read(request.url))
                self.store.save(job, lease, message="Source page inspected")
            while job["steps"] < request.max_steps:
                # Reserve the step before calling inference; crashes still consume it.
                job["steps"] += 1
                self.store.save(job, lease)
                secrets = self.vault.load(job["id"]).get("secrets", {})
                decision = await self.inference.decide(
                    {
                        "request": request.model_dump(mode="json"),
                        "observations": job["observations"][-6:],
                        "operator_note": job.get("operator_note", ""),
                        "available_credentials": [
                            {"name": name, "origin": value["origin"]}
                            for name, value in secrets.items()
                        ],
                    }
                )
                if decision.action == "browse":
                    self.observe(job, await browser.read(decision.url))
                    self.store.save(job, lease, message="Documentation page inspected")
                elif decision.action == "interact":
                    action = decision.interaction
                    if origin(action.url) not in request.origins:
                        self.store.save(
                            job, lease, "needs_input", "Authorize the signup origin in a new job"
                        )
                        return
                    job["pending_action"] = action.model_dump(mode="json")
                    self.store.save(
                        job,
                        lease,
                        "needs_input",
                        "Review the proposed signup/login action before approval",
                    )
                    return
                elif decision.action == "needs_input":
                    self.store.save(
                        job, lease, "needs_input", self.vault.redact(job["id"], decision.message)
                    )
                    return
                else:
                    spec = decision.adapter
                    visited = {o["url"] for o in job["observations"]}
                    if not set(spec.evidence_urls) <= visited:
                        raise ValueError("Adapter cites unobserved documentation")
                    if origin(spec.url) not in request.origins:
                        self.store.save(
                            job,
                            lease,
                            "needs_input",
                            f"API origin requires authorization: {origin(spec.url)}; submit a job with allowed_origins",
                        )
                        return
                    job["adapter"] = spec.model_dump(mode="json")
                    self.store.save(
                        job, lease, message="Adapter generated; validating a live sample"
                    )
                    break
            else:
                self.store.save(
                    job,
                    lease,
                    "needs_input",
                    "Inference step limit reached; submit a new job with a narrower goal",
                )
                return
        await self.validate_sample(job, lease)

    def observe(self, job, observation):
        # Apply redaction to links and field metadata as well as page text.
        clean = self.vault.redact(job["id"], json.dumps(observation))
        job["observations"].append(json.loads(clean))

    async def validate_sample(self, job, lease):
        spec = Adapter.model_validate(job["adapter"])
        result = await self.runtime.invoke(job, spec, spec.sample_input)
        if len(json.dumps(result, allow_nan=False).encode()) > 1_000_000:
            raise ValueError("Sample result exceeds provider response limit")
        self.store.ready(job, lease)

    async def run(self):
        while True:
            if not await self.run_once():
                await asyncio.sleep(self.settings.poll_seconds)
