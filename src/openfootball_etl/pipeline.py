"""Isolated local artifacts: immutable inputs/manifests and atomic phase sealing."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import uuid

from src.common.checksum import sha256_bytes
from src.openfootball_etl.contract import GOLD, SILVER, SPARK_VERSION, check, encoded, proposal

OWNER = {"scope": "pet3-openfootball-isolated", "schema_version": 1}


def safe_path(path):
    path = Path(os.path.abspath(path))
    for item in (path, *path.parents):
        if item.exists() or item.is_symlink():
            attrs = item.lstat()
            check(not item.is_symlink() and not (getattr(attrs, "st_file_attributes", 0) &
                getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024)), "PATH_LINK")
    check(path != Path(path.anchor) and not any(p.casefold() in
          ("footballplatformbackups", "footballplatformrestoredrills", "footballrecoveryvault", ".recovery-keys")
          for p in path.parts), "ISOLATED_PATH_REQUIRED")
    return path


def write_new(path, raw):
    path = safe_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def read_json(path):
    path = safe_path(path)
    check(path.stat().st_size <= 16 * 1024 * 1024, "METADATA_LIMIT")
    return json.loads(path.read_bytes())


def initialize(store):
    store = safe_path(store)
    if store.exists():
        marker = store / "_isolated.json"
        check(marker.is_file() or not any(store.iterdir()), "FOREIGN_STORAGE")
    else:
        store.mkdir(parents=True)
    marker = store / "_isolated.json"
    if not marker.exists():
        write_new(marker, encoded(OWNER))
    check(read_json(marker) == OWNER, "FOREIGN_STORAGE")
    return store


@contextmanager
def writer(store):
    path = store / "_writer.lock"
    token = uuid.uuid4().hex
    write_new(path, token.encode())
    try:
        yield token
    finally:
        # Remove only this process's exclusive lock, never data/foreign files.
        check(path.read_bytes() == token.encode(), "LOCK_CHANGED")
        path.unlink()


def code_sha():
    directory = Path(__file__).parent
    return sha256_bytes(encoded({name: sha256_bytes((directory / name).read_bytes()) for name in
        ("contract.py", "pipeline.py", "spark_job.py", "clickhouse.py")}))


def build_id(result):
    return sha256_bytes(encoded({"domain": "openfootball-local-etl-v1", "source": result.manifest.content_sha256,
        "semantic": result.semantic_digest, "normalized_schema": 2, "spark": SPARK_VERSION,
        "code_sha256": code_sha(), "silver_schemas": SILVER, "gold_schemas": GOLD}))


def verify_source(source, receipt):
    source = safe_path(source)
    check(source.name == "uefa.cl.json" and source.stat().st_size == 58305, "SOURCE_SIZE_OR_PATH")
    raw = source.read_bytes()
    evidence = read_json(receipt)
    result = proposal(raw, evidence, datetime.now(timezone.utc))
    return raw, evidence, result


def bronze(store, raw, receipt, result):
    location = store / "bronze" / "openfootball" / ("sha256=" + result.manifest.content_sha256)
    if location.exists():
        manifest = verify_phase(location)
        check(manifest["source_sha256"] == result.manifest.content_sha256 and
              (location / "uefa.cl.json").read_bytes() == raw and read_json(location / "acquisition.json") == receipt,
              "BRONZE_MISMATCH")
        return location, "REUSED"
    staging = store / "attempts" / uuid.uuid4().hex
    staging.mkdir(parents=True)
    write_new(staging / "uefa.cl.json", raw)
    from src.providers.validation import primitive
    write_new(staging / "source_manifest.json", encoded(primitive(result.manifest)))
    write_new(staging / "acquisition.json", encoded(receipt))
    manifest = {"layer": "bronze", "source_sha256": result.manifest.content_sha256,
        "dataset_id": result.manifest.dataset_id, "source_revision": result.manifest.commit,
        "observed_at": result.observed_at.isoformat(), "license_id": result.manifest.license_id,
        "files": inventory(staging)}
    seal(staging, location, manifest)
    return location, "CREATED"


def inventory(directory):
    result = []
    for path in sorted(directory.rglob("*")):
        safe_path(path)
        if path.is_file() and not path.name.endswith(".crc") and path.name not in ("_manifest.json",):
            raw = path.read_bytes()
            result.append({"path": path.relative_to(directory).as_posix(), "bytes": len(raw), "sha256": sha256_bytes(raw)})
    return result


def verify_phase(directory):
    directory = safe_path(directory)
    check((directory / "_SUCCESS").is_file(), "UNSEALED_PHASE")
    manifest = read_json(directory / "_manifest.json")
    actual = [f for f in inventory(directory) if f["path"] != "_SUCCESS"]
    check(actual == manifest["files"], "ARTIFACT_INTEGRITY")
    return manifest


def seal(staging, destination, manifest):
    check(not destination.exists(), "NO_OVERWRITE")
    write_new(staging / "_manifest.json", encoded(manifest))
    write_new(staging / "_SUCCESS", b"")
    verify_phase(staging)
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.rename(staging, destination)  # Same-filesystem phase rename under writer lock.


def bundle(store, batch):
    return store / "builds" / ("batch_id=" + batch)


def gold_rows(store, batch):
    root = bundle(store, batch) / "gold"
    manifest = verify_phase(root)
    result = {}
    for name in GOLD:
        rows = []
        for item in manifest["files"]:
            if item["path"].startswith(name + "/json/") and item["path"].endswith(".json"):
                raw = (root / item["path"]).read_bytes()
                check(len(raw) <= 16 * 1024 * 1024, "GOLD_EXPORT_LIMIT")
                rows.extend(json.loads(line) for line in raw.splitlines() if line)
        from src.openfootball_etl.contract import row_digest
        check(len(rows) == manifest["datasets"][name]["rows"] and
              row_digest(rows) == manifest["datasets"][name]["logical_sha256"], "GOLD_EXPORT_INTEGRITY")
        result[name] = rows
    return result
