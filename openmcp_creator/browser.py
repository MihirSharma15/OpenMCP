"""Isolated Chromium contexts with bounded, address-checked HTTP access."""

from urllib.parse import urlsplit

from .models import origin


class Browser:
    def __init__(self, settings, network, vault, job_id):
        self.settings, self.network, self.vault, self.job_id = settings, network, vault, job_id
        self.allowed_mutation_origin = None
        self.current = None
        self.playwright = self.browser = self.context = None

    async def __aenter__(self):
        from playwright.async_api import async_playwright

        self.playwright = await async_playwright().start()
        try:
            options = {"headless": self.settings.headless}
            if self.settings.browser_executable:
                options["executable_path"] = str(self.settings.browser_executable)
            self.browser = await self.playwright.chromium.launch(**options)
            self.context = await self.browser.new_context(
                service_workers="block",
                accept_downloads=False,
                storage_state=self.vault.load(self.job_id).get("browser_state"),
            )
            await self.context.route("**/*", self._route)
            await self.context.route_web_socket("**/*", lambda ws: ws.close())
            self.page = await self.context.new_page()
            self.page.set_default_timeout(15000)
            return self
        except BaseException:
            await self.__aexit__(None, None, None)
            raise

    async def __aexit__(self, *args):
        if self.context:
            try:
                values = self.vault.load(self.job_id)
                values["browser_state"] = await self.context.storage_state()
                self.vault.save(self.job_id, values)
            finally:
                await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

    async def _route(self, route):
        request = route.request
        try:
            if request.resource_type in {"media", "font", "image"}:
                await route.abort()
                return
            scope = origin(request.url)
            if request.method not in {"GET", "HEAD"} and scope != self.allowed_mutation_origin:
                await route.abort()
                return
            # Cookie-bearing requests never cross origins during redirect resolution.
            headers = await request.all_headers()
            headers = {
                k: v
                for k, v in headers.items()
                if k.lower() in {"accept", "content-type", "cookie", "authorization"}
            }
            response = await self.network.request(
                request.url,
                method=request.method,
                headers=headers,
                content=request.post_data_buffer,
                allowed_origin=scope,
                follow_redirects=False,
            )
            response_headers = dict(response.headers)
            cookies = response.headers.get_list("set-cookie")
            if cookies:
                response_headers["set-cookie"] = "\n".join(cookies)
            await route.fulfill(
                status=response.status_code, headers=response_headers, body=response.content
            )
        except Exception:
            await route.abort()

    async def read(self, url, selector="body"):
        await self.network.address(url)
        if self.page.url != url:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
        self.current = self.page.url
        text = await self.page.locator(selector).first.inner_text()
        links = await self.page.locator("a[href]").evaluate_all(
            "els => els.slice(0, 80).map(e => ({text: e.innerText.slice(0,120), url: e.href}))"
        )
        fields = await self.page.locator("input,button,select").evaluate_all(
            "els => els.slice(0, 60).map(e => ({tag: e.tagName, type: e.type, name: e.name, id: e.id, text: e.innerText.slice(0,120)}))"
        )
        return {
            "url": self.current,
            "text": self.vault.redact(self.job_id, text[:20000]),
            "links": links,
            "fields": fields,
        }

    async def interact(self, action, allowed_origins):
        if origin(action.url) not in allowed_origins:
            raise ValueError("Browser interaction origin was not authorized")
        if urlsplit(action.url).query:
            raise ValueError("Use a signup URL without query credentials")
        if self.page.url != action.url:
            await self.read(action.url)
        # Form values are not included in Playwright storage_state. Restore approved
        # fills on this page before a later approved click, with mutations blocked.
        values = self.vault.load(self.job_id)
        fills = values.get("form_fills", {}).get(action.url, {})
        for selector, fill in fills.items():
            value = (
                self.vault.secret(self.job_id, fill["secret_name"], action.url)
                if fill.get("secret_name")
                else fill["value"]
            )
            await self.page.locator(selector).fill(value)
        self.allowed_mutation_origin = origin(action.url)
        try:
            locator = self.page.locator(action.selector)
            if action.kind == "fill":
                value = (
                    self.vault.secret(self.job_id, action.secret_name, action.url)
                    if action.secret_name
                    else action.value
                )
                await locator.fill(value)
                values.setdefault("form_fills", {}).setdefault(action.url, {})[action.selector] = {
                    "value": action.value,
                    "secret_name": action.secret_name,
                }
                self.vault.save(self.job_id, values)
            elif action.kind == "capture_secret":
                tag = await locator.evaluate("e => e.tagName.toLowerCase()")
                value = (
                    await locator.input_value()
                    if tag in {"input", "textarea"}
                    else await locator.inner_text()
                )
                if not value.strip():
                    raise ValueError("Credential field is empty")
                self.vault.put(self.job_id, action.secret_name, value.strip(), action.url)
            else:
                await locator.click()
                values.setdefault("form_fills", {}).pop(action.url, None)
                self.vault.save(self.job_id, values)
            return await self.read(self.page.url)
        finally:
            self.allowed_mutation_origin = None
