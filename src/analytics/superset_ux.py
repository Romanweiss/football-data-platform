"""Pinned Superset UX revisions and CAS protocol. No service or file IO."""
from copy import deepcopy
import hashlib
import json

BUNDLE_HASHES = {
    "before.json": "37e5a53dadaf3bdbf10755ef82660d32e488744c15960a23a6d429d3dcd21b86",
    "candidate-config.json": "4f8f923deddb2bb3108b65145f565580ba78606f8105b156e5617a5996464514",
    "config-patch.json": "7e030c99a6b1c82d1f7afa30dbd3a578f68d4319c0d56fc37473cf915a71851d",
    "rollback-fields.json": "91e99eb42f9acc53a46d198842dd58e7516896e07dcbaa97862a26c151c82c34",
}
UX3_R1_HASHES = {
    "before.json": "37e5a53dadaf3bdbf10755ef82660d32e488744c15960a23a6d429d3dcd21b86",
    "candidate-config.json": "e4108a79dffa0985a8ca41e1674eca82b713b9225c3c9799deb1795cffa5695d",
    "config-patch.json": "2dff6691f5a43416de37ece324e77f27accdc2cfc1c8564fa92182d3867a12ca",
    "rollback-fields.json": "caa3fe19c8de9a3b12247853657331c1bc0a76b0643c81e96bd75b419f8dddb3",
}
UX3_R2_HASHES = {
    "before.json": "37e5a53dadaf3bdbf10755ef82660d32e488744c15960a23a6d429d3dcd21b86",
    "candidate-config.json": "d741625a585e12a96f786994e18df92b04ce5d1a2ecae91881938da530ec3555",
    "config-patch.json": "3d6d2c5037c7c1a9e3f8cd7c1f2ef3e5441ae7ae43cdc89358cb8b2cd18c2a6c",
    "rollback-fields.json": "35652191f52c20cfa9a0329a06df9a28936435cfa5383925608bc0490c78a22e",
}
ALLOWED_PATHS = frozenset(
    [f"/charts/{cid}/{field}" for cid in range(9, 17) for field in ("params", "query_context")]
    + ["/charts/13/description", "/charts/14/description", "/datasets/5/sql",
       "/datasets/5/columns", "/dashboards/2/metadata", "/dashboards/2/position"]
)


class UXConflict(ValueError):
    """Safe diagnostic code only; never embed config/SQL/credential values."""


def check(condition, code):
    if not condition:
        raise UXConflict(code)


def hashes_for(revision):
    revisions = {"ux1": BUNDLE_HASHES, "ux3-r1": UX3_R1_HASHES, "ux3-r2": UX3_R2_HASHES}
    check(revision in revisions, "UNKNOWN_REVISION")
    return revisions[revision]


def load_bundle(raw, revision="ux1"):
    """Validate trusted external file fingerprints BEFORE parsing JSON."""
    hashes = hashes_for(revision)
    check(set(raw) == set(hashes), "BUNDLE_FILES")
    for name, digest in hashes.items():
        check(type(raw[name]) is bytes and len(raw[name]) <= 2 * 1024 * 1024, "BUNDLE_SIZE")
        check(hashlib.sha256(raw[name]).hexdigest() == digest, "BUNDLE_FINGERPRINT")
    bundle = {name: json.loads(value) for name, value in raw.items()}
    changes = bundle["config-patch.json"]
    check(len(changes) == 22 and {c["path"] for c in changes} == ALLOWED_PATHS, "PATCH_SCOPE")
    before, after = bundle["before.json"], bundle["candidate-config.json"]
    check(before["dashboards"]["2"]["metadata"].get("shared_label_colors") ==
          after["dashboards"]["2"]["metadata"].get("shared_label_colors"), "COLOR_CACHE_NOT_OWNED")
    for change in changes:
        _, kind, identifier, field = change["path"].split("/")
        check(change["before"] == before[kind][identifier][field], "PATCH_BEFORE")
        check(change["after"] == after[kind][identifier][field], "PATCH_AFTER")
    check(bundle["rollback-fields.json"] == [
        {"path": c["path"], "expected": c["after"], "restore": c["before"]} for c in changes
    ], "ROLLBACK_BUNDLE")
    return bundle


def expected_fields(bundle, direction):
    check(direction in ("apply", "rollback"), "DIRECTION")
    changes = bundle["config-patch.json"]
    check(len(changes) == 22 and {c["path"] for c in changes} == ALLOWED_PATHS, "PATCH_SCOPE")
    old, new = ("before", "after") if direction == "apply" else ("after", "before")
    return [(c["path"], deepcopy(c[old]), deepcopy(c[new])) for c in bundle["config-patch.json"]]


def cas_value(path, value):
    """Only Superset's auto-maintained color cache is outside patch ownership."""
    value = deepcopy(value)
    if path == "/dashboards/2/metadata" and isinstance(value, dict):
        value.pop("shared_label_colors", None)
    return value


def merge_runtime(path, current, target):
    target = deepcopy(target)
    if path == "/dashboards/2/metadata" and isinstance(target, dict):
        if "shared_label_colors" in current:
            target["shared_label_colors"] = deepcopy(current["shared_label_colors"])
        else:
            target.pop("shared_label_colors", None)
    return target


def transact(store, bundle, direction):
    """Store owns one serializable transaction, scoped locks and protected IDs.

    No best-effort partial writes, replays, commits in loops, or implicit rollback
    of someone else's edits. Test stores must implement the same interface.
    """
    changes = expected_fields(bundle, direction)
    store.begin()
    try:
        protected = store.protected()
        actual_targets = []
        for path, before, after in changes:
            current = store.read(path)
            check(cas_value(path, current) == cas_value(path, before), "CAS_CONFLICT")
            actual_targets.append((path, merge_runtime(path, current, after)))
        for path, after in actual_targets:
            store.write(path, after)
        store.flush()
        check(store.protected() == protected, "PROTECTED_IDENTITY_CHANGED")
        for path, after in actual_targets:
            check(store.read(path) == after, "WRITE_VERIFICATION")
        store.commit()
    except Exception:
        store.rollback()
        raise
    return {"status": "PASS", "direction": direction, "fields": len(changes), "commits": 1}


def display_mapping(guard):
    prefix = "{% set lookup = "
    check(guard.startswith(prefix), "GUARD_MAPPING")
    value = json.loads(guard[len(prefix):guard.index(" %}")])
    check(type(value) is dict and len(value) == 98 and len(set(value.values())) == 98, "MAPPING_UNIQUENESS")
    return value


def require_fresh_mapping(expected, records):
    """Any rename/date/score correction requires review, not reassignment."""
    actual = {r["match_display"]: f"{r['competition_id']}/{r['season_id']}/{r['match_id']}" for r in records}
    check(len(records) == len(actual) == 98 and len(set(actual.values())) == 98, "SOURCE_MAPPING_UNIQUENESS")
    check(actual == expected, "STALE_DISPLAY_MAPPING")
