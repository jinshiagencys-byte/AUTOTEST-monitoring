"""Opt-in local Selenium integration, never calls an external site or an LLM."""

import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from autotest.monitoring.runner import run_site
from autotest.monitoring.store import Store


pytestmark = pytest.mark.skipif(os.environ.get("MONITOR_LIVE_TEST") != "1",
                                reason="Set MONITOR_LIVE_TEST=1 to start local Chrome")


class Page(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'''<!doctype html><title>Monitor fixture</title>
        <label>Email <input aria-label="Email" placeholder="Email"></label>
        <button style="display:none">Save</button>
        <button onclick="document.getElementById('output').textContent='Saved'">Save</button>
        <p id="output">Waiting</p>'''
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


def test_browser_replay_and_regeneration_queue(tmp_path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), Page)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = "http://127.0.0.1:{}/".format(server.server_port)
    store = Store(tmp_path)
    try:
        sources = {
            url: 'ctx.type_text({"aria_label": "Email"}, "monitor@example.test")\n'
                 '    ctx.assert_value({"placeholder": "Email"}, "monitor@example.test")\n'
                 '    ctx.click({"tag": "button", "text": "Save"})\n'
                 '    ctx.assert_text({"id": "output"}, "Saved")',
            url + "fail": 'ctx.assert_text({"id": "output"}, "Wrong")',
            url + "missing": 'ctx.assert_visible({"id": "removed"})',
        }
        for page, body in sources.items():
            source = 'def run(ctx):\n    ctx.open(' + repr(page) + ')\n    ' + body + '\n'
            store.publish(url, page, source, {}, "local-fixture")
        report = run_site(store, url, page_timeout=90)
        assert report["counts"] == {"OK": 1, "FAIL": 1, "SKIP": 1}, report
        assert [item["page_url"] for item in store.pending(url)] == [url + "missing"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)