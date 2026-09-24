"""Offline coverage of generation, replay, classification and persistence."""

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from selenium.common.exceptions import NoSuchElementException, WebDriverException
from selenium.webdriver.common.by import By

from autotest.monitoring.browser import build_options
from autotest.monitoring.contract import replay, validate_script
from autotest.monitoring.generation import generate_site
from autotest.monitoring.interactions import bezier_points, movement_time
from autotest.monitoring.runner import execute_page, run_site
from autotest.monitoring.runtime import BotBlocked, ElementNotReady, Runtime, resolve_target
from autotest.monitoring.store import Store


SITE = "https://example.test/"


def script(url=SITE, body='ctx.assert_title("Example")'):
    return 'def run(ctx):\n    ctx.open(' + repr(url) + ')\n    ' + body + '\n'


class Element:
    def __init__(self, text="Save", visible=True, enabled=True, **attrs):
        self.text, self.visible, self.enabled = text, visible, enabled
        self.tag_name = "button"
        self.attrs = attrs

    def get_attribute(self, key):
        return self.text if key == "textContent" else self.attrs.get(key)

    def is_displayed(self):
        return self.visible

    def is_enabled(self):
        return self.enabled


class Driver:
    title = "Example"
    current_url = SITE

    def __init__(self, elements=()):
        self.elements = elements
        self.quit = Mock()

    def find_elements(self, by, value):
        return [] if by == By.CSS_SELECTOR else self.elements

    def get(self, url):
        self.current_url = url


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path)


def publish(store, source=None, url=SITE):
    return store.publish(SITE, url, source or script(url), {"test_cases": []}, "test-provider")


def test_browser_options():
    options = build_options()
    assert options.experimental_options["excludeSwitches"] == ["enable-automation"]
    assert options.experimental_options["useAutomationExtension"] is False
    assert "--disable-blink-features=AutomationControlled" in options.arguments
    assert "--headless=new" not in build_options(False).arguments


@pytest.mark.parametrize("source", [
    'import os\n' + script(),
    script(body='ctx.driver.get("https://example.test/")'),
    script(body='ctx.click({"xpath": "/html/body"})'),
    script(body='ctx.click({"tag": "button"})'),
    script(body='ctx.assert_title(str(1))'),
    script(body='ctx.assert_title(expected="Example")'),
    script(body='ctx.assert_title("Example"); __import__("os")'),
    script().replace('def run(ctx):', 'def run(ctx=print("oops")):'),
    script(body='ctx.click({"text": "Save"})'),
    script(body='try:\n        ctx.assert_title("Example")\n    except:\n        pass'),
])
def test_contract_rejects_bypass_and_empty_tests(source):
    with pytest.raises((ValueError, SyntaxError)):
        validate_script(source)


def test_replay_calls_runtime_without_exec():
    context = Mock(spec=Runtime)
    replay(script(), context)
    context.open.assert_called_once_with(SITE)
    context.assert_title.assert_called_once_with("Example")


def test_versioning_queue_and_integrity(store):
    old = publish(store)
    store.enqueue(old, "dom_changed")
    store.enqueue(old, "dom_changed")
    assert len(store.pending(SITE)) == 1
    new = publish(store)
    assert new["version"] != old["version"]
    assert store.source(old) == store.source(new)
    assert store.pending(SITE) == []
    store.enqueue(old, "dom_changed")
    assert store.pending(SITE) == []
    assert store.manifest(SITE)["pages"][SITE] == new
    (store.root / new["script"]).write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        store.source(new)


def test_invalid_publish_preserves_previous_version(store):
    old = publish(store)
    with pytest.raises(ValueError):
        publish(store, script(body="ctx.assert_title(__import__('os'))"))
    with pytest.raises(ValueError, match="origin"):
        publish(store, script(body='ctx.open("https://other.test/"); ctx.assert_title("Example")'))
    assert store.manifest(SITE)["pages"][SITE] == old


def test_path_escape(store):
    record = publish(store)
    with pytest.raises(ValueError, match="escaped"):
        store.source({**record, "script": "../outside.py"})


def test_semantic_resolution_ignores_hidden_duplicate():
    visible = Element(**{"aria-label": "Save"})
    hidden = Element(visible=False, **{"aria-label": "Save"})
    assert resolve_target(Driver([hidden, visible]), {"aria_label": " save "}, timeout=0) is visible


@pytest.mark.parametrize("elements, error", [
    ([], NoSuchElementException),
    ([Element(visible=False)], ElementNotReady),
    ([Element(enabled=False)], ElementNotReady),
    ([Element(), Element()], ElementNotReady),
])
def test_semantic_absent_not_ready_and_ambiguous(elements, error):
    with pytest.raises(error):
        resolve_target(Driver(elements), {"text": "Save"}, timeout=0, actionable=True)


@pytest.mark.parametrize("body, elements, status, reason, regenerate", [
    ('ctx.assert_title("Example")', [], "OK", "completed", False),
    ('ctx.assert_title("Wrong")', [], "FAIL", "assertion_failed", False),
    ('ctx.assert_visible({"id": "missing"})', [], "SKIP", "dom_changed", True),
    ('ctx.assert_text({"id": "output"}, "Wrong")', [Element(id="output")], "FAIL", "assertion_failed", False),
    ('ctx.assert_visible({"id": "output"})', [Element(id="output", visible=False)], "SKIP", "element_not_ready", False),
])
def test_execution_classification(store, body, elements, status, reason, regenerate):
    record = publish(store, script(body=body))
    driver = Driver(elements)
    result = execute_page(store, record, lambda: driver, timeout=0)
    assert (result["status"], result["reason"], result["regenerate"]) == (status, reason, regenerate)
    driver.quit.assert_called_once()


def test_bot_block_not_regenerated(store):
    driver = Driver()
    driver.title = "Just a moment..."
    result = execute_page(store, publish(store), lambda: driver)
    assert result["status"] == "SKIP" and result["reason"] == "bot_blocked"
    assert not result["regenerate"]


def test_browser_start_failure(store):
    result = execute_page(store, publish(store), Mock(side_effect=WebDriverException("startup")))
    assert result["reason"] == "browser_error"
    assert not result["regenerate"]


def test_cross_origin_action_refused():
    with pytest.raises(ValueError):
        Runtime(Driver(), SITE).open("https://other.test/")


def test_phase_a_reuses_crawler_and_generator(store):
    driver = Driver()
    generator = SimpleNamespace(
        driver=driver, url_extractor=Mock(), llm=SimpleNamespace(provider="test-provider"),
        generate_monitoring_page=Mock(side_effect=lambda url: (script(url), {"metadata": {"url": url}})))
    generator.url_extractor.extract_urls.return_value = [SITE, SITE + "about"]
    report = generate_site(store, SITE, generator, max_depth=3)
    generator.url_extractor.extract_urls.assert_called_once_with(SITE, max_depth=3)
    assert len(report["published"]) == 2
    old = store.manifest(SITE)
    generator.generate_monitoring_page.side_effect = ValueError("LLM unavailable")
    report = generate_site(store, SITE, generator, pages=[SITE])
    assert len(report["errors"]) == 1 and store.manifest(SITE) == old
    assert generator.url_extractor.extract_urls.call_count == 1


def test_run_hard_timeout(store, monkeypatch):
    publish(store)
    process = Mock(pid=987654321)
    process.wait.side_effect = [subprocess.TimeoutExpired("worker", 1), 0]
    monkeypatch.setattr("autotest.monitoring.runner.subprocess.Popen", Mock(return_value=process))
    kill = Mock()
    monkeypatch.setattr("autotest.monitoring.runner.os.killpg", kill)
    result = run_site(store, SITE, page_timeout=0.01)
    assert result["pages"][0]["reason"] == "execution_timeout"
    assert store.pending(SITE) == []
    kill.assert_called_once()


def test_motion_endpoints_and_zero_distance():
    assert tuple(bezier_points((0, 0), (100, 200)))[-1] == (100, 200)
    assert movement_time(0, 0) > 0


def test_phase_b_imports_no_llm():
    package = str(Path(__file__).resolve().parents[2])
    check = """
import sys
import autotest.monitoring.runner
import autotest.monitoring.__main__
assert not any(n.startswith(('langchain', 'openai', 'groq', 'sqlalchemy')) for n in sys.modules)
assert 'autotest.core.web_test_generator' not in sys.modules
assert 'autotest.monitoring.generation' not in sys.modules
"""
    subprocess.run([sys.executable, "-c", check], env={**os.environ, "PYTHONPATH": package}, check=True)