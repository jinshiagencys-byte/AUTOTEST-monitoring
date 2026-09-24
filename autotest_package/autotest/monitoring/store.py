"""Versioned filesystem artifacts and durable, deduplicated regeneration queue."""

import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import fcntl

from .contract import validate_script


def now():
    return datetime.now(timezone.utc).isoformat()


def key(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def site_dir(self, site_url):
        return self.root / "sites" / key(site_url)

    @contextmanager
    def lock(self, site_url):
        directory = self.site_dir(site_url)
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / ".lock").open("a") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def manifest(self, site_url):
        path = self.site_dir(site_url) / "manifest.json"
        return read_json(path) if path.exists() else {"schema_version": 1, "site_url": site_url, "pages": {}}

    def publish(self, site_url, page_url, source, analysis, provider):
        from .runtime import origin

        calls = validate_script(source)
        if calls[0] != ("open", [page_url]):
            raise ValueError("Script must open its source page first")
        if origin(site_url) != origin(page_url) or any(
                origin(values[0]) != origin(site_url) for method, values in calls if method == "open"):
            raise ValueError("Script navigation must stay on the monitored origin")
        version = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid4().hex[:8]
        relative = Path("sites") / key(site_url) / "pages" / key(page_url) / version
        directory = self.root / relative
        directory.mkdir(parents=True)
        (directory / "test.py").write_text(source, encoding="utf-8")
        record = {"site_url": site_url, "page_url": page_url, "generated_at": now(),
                  "version": version, "sha256": key(source), "provider": provider,
                  "script": str(relative / "test.py")}
        write_json(directory / "metadata.json", {**record, "analysis": analysis})
        with self.lock(site_url):
            manifest = self.manifest(site_url)
            manifest["pages"][page_url] = record
            write_json(self.site_dir(site_url) / "manifest.json", manifest)
            queue = self.site_dir(site_url) / "queue" / (key(page_url) + ".json")
            if queue.exists():
                queue.unlink()
        return record

    def source(self, record):
        path = (self.root / record["script"]).resolve()
        if self.root not in path.parents:
            raise ValueError("Artifact path escaped the store")
        source = path.read_text(encoding="utf-8")
        if key(source) != record["sha256"]:
            raise ValueError("Script checksum mismatch")
        validate_script(source)
        return source

    def enqueue(self, record, reason):
        with self.lock(record["site_url"]):
            # A concurrent successful regeneration makes an old failure obsolete.
            current = self.manifest(record["site_url"])["pages"].get(record["page_url"])
            if current is None or current["version"] != record["version"]:
                return
            path = self.site_dir(record["site_url"]) / "queue" / (key(record["page_url"]) + ".json")
            if not path.exists():
                write_json(path, {"site_url": record["site_url"], "page_url": record["page_url"],
                                  "version": record["version"], "reason": reason, "requested_at": now()})

    def pending(self, site_url):
        with self.lock(site_url):
            return [read_json(path) for path in sorted((self.site_dir(site_url) / "queue").glob("*.json"))]