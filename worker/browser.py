"""Playwright wrapper that gives the model text, not pixels.

snapshot() tags every interactive element in the page with a numeric
data-agent-id via JS, then returns a text block the model can read and a
parallel elements list for validation. Ids are only valid for the snapshot
they came from (browser.py enforces this, not the model's good behavior).
"""
from pathlib import Path

from playwright.sync_api import sync_playwright

_SNAPSHOT_JS = (Path(__file__).resolve().parent / "templates" / "snapshot.js").read_text()


class BrowserError(Exception):
    pass


class Browser:
    def __init__(self, headless=True):
        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch(headless=headless)
        self.context = self.browser.new_context()
        self.page = self.context.new_page()
        self._elements = {}
        self.last_status = None
        self.page.on("response", self._record_response)

    def _record_response(self, response):
        # Only the top-level document navigation, not css/js/image sub-requests
        # the resulting page makes (those would overwrite a real 500 with their
        # own 200 before anyone gets to check it).
        if response.frame == self.page.main_frame and response.request.resource_type == "document":
            self.last_status = response.status

    def open(self, url):
        self.page.goto(url, wait_until="load")
        return self.snapshot()

    def snapshot(self):
        data = self.page.evaluate(_SNAPSHOT_JS)
        self._elements = {el["id"]: el for el in data["elements"]}
        lines = []
        for el in data["elements"]:
            bits = [f'[{el["id"]}] {el["role"]} "{el["label"]}"']
            if el["value"]:
                bits.append(f'= "{el["value"]}"')
            if el["disabled"]:
                bits.append("(disabled)")
            if el["risk"]:
                bits.append(f'data-risk="{el["risk"]}"')
            lines.append(" ".join(bits))
        text = "URL: {}\n\n{}\n\nInteractive elements:\n{}".format(
            data["url"], data["text"], "\n".join(lines) or "(none)"
        )
        return {"url": data["url"], "text": text, "elements": data["elements"]}

    def _require(self, element_id):
        el = self._elements.get(element_id)
        if el is None:
            raise BrowserError(
                f"id {element_id} is not valid for the latest snapshot. Call browser_snapshot() again."
            )
        return el

    def element_risk(self, element_id):
        return self._require(element_id)["risk"]

    def click(self, element_id):
        self._require(element_id)
        self.last_status = None
        self.page.locator(f'[data-agent-id="{element_id}"]').click()
        try:
            self.page.wait_for_load_state("load", timeout=5000)
        except Exception:
            pass

    def type(self, element_id, text):
        self._require(element_id)
        self.page.locator(f'[data-agent-id="{element_id}"]').fill(text)

    def select(self, element_id, option):
        self._require(element_id)
        self.page.locator(f'[data-agent-id="{element_id}"]').select_option(label=option)

    def open_fresh(self, url):
        """A snapshot from a brand-new incognito context: no cookies/session carried
        over from the agent's own browsing. Reuses this process's Chromium instance
        instead of starting a second Playwright driver (which Playwright's sync API
        does not support within one thread)."""
        context = self.browser.new_context()
        page = context.new_page()
        try:
            page.goto(url, wait_until="load")
            data = page.evaluate(_SNAPSHOT_JS)
            lines = [f'[{el["id"]}] {el["role"]} "{el["label"]}"' for el in data["elements"]]
            text = "URL: {}\n\n{}\n\nInteractive elements:\n{}".format(
                data["url"], data["text"], "\n".join(lines) or "(none)"
            )
            return text
        finally:
            context.close()

    def screenshot(self, path):
        self.page.screenshot(path=str(path))

    def close(self):
        try:
            self.context.close()
            self.browser.close()
        finally:
            self._pw.stop()
