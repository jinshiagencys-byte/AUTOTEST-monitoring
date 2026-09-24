"""Phase B runtime: semantic Selenium actions, never LLM decisions."""

from urllib.parse import urlparse

from selenium.common.exceptions import (
    NoSuchElementException, StaleElementReferenceException, TimeoutException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from .interactions import HumanInteractions


class ElementNotReady(Exception):
    """A target exists but is hidden, disabled, stale or ambiguous."""


class BotBlocked(Exception):
    """An observed challenge prevents testing; not an application assertion."""


def origin(url):
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Expected an HTTP(S) URL without credentials")
    return parsed.scheme, parsed.hostname.lower(), parsed.port or (443 if parsed.scheme == "https" else 80)


def check_blocked(driver):
    # Deliberately narrow heuristics, not a CAPTCHA solver or a WAF bypass.
    title = driver.title.lower().strip()
    if title in {"just a moment...", "attention required! | cloudflare", "access denied"}:
        raise BotBlocked("Challenge/access-denied page: " + title)
    for el in driver.find_elements(By.CSS_SELECTOR,
                                   '#challenge-running, #challenge-stage, iframe[src*="challenges.cloudflare.com"]'):
        if el.is_displayed():
            raise BotBlocked("Visible challenge widget")


def resolve_target(driver, target, timeout=10, actionable=False):
    """Match semantic attributes conjunctively, ignoring hidden duplicates.

    Adapted from element_selectors.py's visible-copy / not-ready distinction.
    There is no SentinelSite resolver in this repository to delegate to.
    """
    seen = False

    def find(_):
        nonlocal seen
        check_blocked(driver)
        matches = []
        elements = driver.find_elements(By.TAG_NAME, target.get("tag", "*"))
        for el in elements:
            try:
                for key, expected in target.items():
                    actual = ((el.text or el.get_attribute("textContent")) if key == "text" else el.tag_name if key == "tag"
                              else el.get_attribute(key.replace("_", "-")))
                    if " ".join((actual or "").split()).casefold() != " ".join(expected.split()).casefold():
                        break
                else:
                    seen = True
                    if el.is_displayed() and (not actionable or el.is_enabled()):
                        matches.append(el)
            except StaleElementReferenceException:
                continue
        return matches[0] if len(matches) == 1 else False

    try:
        return WebDriverWait(driver, timeout, poll_frequency=0.2).until(find)
    except TimeoutException as exc:
        if seen:
            raise ElementNotReady("Target not uniquely usable: " + repr(target)) from exc
        raise NoSuchElementException("Semantic target absent: " + repr(target)) from exc


class Runtime:
    def __init__(self, driver, site_url, timeout=10, resolver=resolve_target):
        self.driver = driver
        self.site_origin = origin(site_url)
        self.timeout = timeout
        self.resolver = resolver
        self.human = HumanInteractions(driver)

    def guard(self):
        check_blocked(self.driver)
        if origin(self.driver.current_url) != self.site_origin:
            raise ValueError("Navigation left the configured origin")

    def open(self, url):
        if origin(url) != self.site_origin:
            raise ValueError("Cross-origin navigation is not allowed")
        self.driver.get(url)
        self.guard()

    def target(self, target, actionable=False):
        self.guard()
        return self.resolver(self.driver, target, timeout=self.timeout, actionable=actionable)

    def click(self, target):
        self.human.click(self.target(target, actionable=True))
        self.guard()

    def type_text(self, target, text):
        self.human.type_text(self.target(target, actionable=True), text)

    def _assert(self, predicate, message):
        def ready(_):
            self.guard()
            try:
                return predicate()
            except StaleElementReferenceException:
                return False
        try:
            WebDriverWait(self.driver, self.timeout, poll_frequency=0.2).until(ready)
        except TimeoutException as exc:
            raise AssertionError(message) from exc

    def assert_visible(self, target):
        self.target(target)

    def assert_text(self, target, expected):
        element = self.target(target)
        self._assert(lambda: expected in element.text, "Expected text: " + expected)

    def assert_value(self, target, expected):
        element = self.target(target)
        self._assert(lambda: element.get_attribute("value") == expected, "Unexpected field value")

    def assert_url(self, expected):
        self._assert(lambda: self.driver.current_url == expected, "Expected URL: " + expected)

    def assert_title(self, expected):
        self._assert(lambda: self.driver.title == expected, "Expected title: " + expected)