"""Phase B. No generation import, no LLM calls, bounded subprocess per page."""

import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from selenium.common.exceptions import NoSuchElementException, WebDriverException

from .browser import create_driver
from .contract import replay
from .runtime import BotBlocked, ElementNotReady, Runtime
from .store import now, read_json, write_json


def result_for(record, status, reason, detail="", regenerate=False):
    return {**record, "status": status, "reason": reason, "detail": detail,
            "regenerate": regenerate, "executed_at": now()}


def execute_page(store, record, driver_factory=create_driver, timeout=10):
    driver = None
    start = time.monotonic()
    try:
        source = store.source(record)
        driver = driver_factory()
        replay(source, Runtime(driver, record["site_url"], timeout=timeout))
        result = result_for(record, "OK", "completed")
    except BotBlocked as exc:
        result = result_for(record, "SKIP", "bot_blocked", str(exc))
    except ElementNotReady as exc:
        result = result_for(record, "SKIP", "element_not_ready", str(exc))
    except NoSuchElementException as exc:
        result = result_for(record, "SKIP", "dom_changed", str(exc), regenerate=True)
    except AssertionError as exc:
        result = result_for(record, "FAIL", "assertion_failed", str(exc))
    except WebDriverException as exc:
        result = result_for(record, "SKIP", "browser_error", str(exc))
    except Exception as exc:
        result = result_for(record, "SKIP", "execution_error", str(exc))
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass
    result["duration_seconds"] = round(time.monotonic() - start, 3)
    return result


def run_site(store, site_url, page_timeout=120, headless=True):
    records = list(store.manifest(site_url)["pages"].values())
    if not records:
        raise ValueError("No published scripts; run Phase A first")
    results = []
    for record in records:
        with tempfile.TemporaryDirectory(prefix="autotest-replay-") as directory:
            request, response = Path(directory) / "request.json", Path(directory) / "response.json"
            write_json(request, record)
            command = [sys.executable, "-m", "autotest.monitoring", "_worker",
                       "--store", str(store.root), "--request", str(request), "--output", str(response)]
            if not headless:
                command.append("--headed")
            # Separate process group permits cleanup of Chrome on hard timeouts.
            with (Path(directory) / "worker.log").open("w") as log:
                process = subprocess.Popen(command, stdout=log, stderr=log, start_new_session=True)
                try:
                    process.wait(timeout=page_timeout)
                    result = (read_json(response) if process.returncode == 0 and response.exists()
                              else result_for(record, "SKIP", "worker_error", "Replay worker failed"))
                except subprocess.TimeoutExpired:
                    result = result_for(record, "SKIP", "execution_timeout", "Page time budget exceeded")
                finally:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait()
            if result["regenerate"]:
                store.enqueue(record, result["reason"])
            results.append(result)
    return {"schema_version": 1, "site_url": site_url, "executed_at": now(), "pages": results,
            "counts": {status: sum(r["status"] == status for r in results) for status in ("OK", "SKIP", "FAIL")}}