"""Offline, byte-reproducible UX-3 layout revisions from the trusted UX-1 bundle.

No network, credentials, Superset bootstrap, SQL execution or live writes.
Original bundles and existing destination directories are never overwritten.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.analytics.superset_ux import ALLOWED_PATHS, BUNDLE_HASHES, check, hashes_for, load_bundle


def layout_revision(original, revision):
    check(revision in ("ux3-r1", "ux3-r2"), "UNKNOWN_REVISION")
    result = deepcopy(original)
    result["dashboards"]["2"]["metadata"]["filter_bar_orientation"] = "HORIZONTAL"
    for node in result["dashboards"]["2"]["position"].values():
        if not isinstance(node, dict):
            continue
        if node.get("meta", {}).get("chartId") == 14:
            node["meta"]["height"] = 20
        if node.get("meta", {}).get("chartId") == 13:
            node["meta"]["height"] = 36 if revision == "ux3-r1" else 44
        if node.get("type") == "MARKDOWN":
            node["meta"]["height"] = 12 if revision == "ux3-r1" else 20
    chart = result["charts"]["13"]
    chart["params"]["page_length"] = 5
    chart["query_context"]["form_data"]["page_length"] = 5
    if revision == "ux3-r2":
        config = deepcopy(chart["params"].get("column_config") or {})
        config.update({"player_name": {"columnWidth": 320}, "team_name": {"columnWidth": 140},
                       "outcome_name": {"columnWidth": 110}})
        chart["params"]["column_config"] = config
        chart["query_context"]["form_data"]["column_config"] = deepcopy(config)
    return result


def encoded(value):
    return (json.dumps(value, ensure_ascii=True, indent=2) + "\n").encode()


def build(raw, revision):
    old = load_bundle(raw)
    before = old["before.json"]
    candidate = layout_revision(old["candidate-config.json"], revision)
    changes = []
    for kind in ("charts", "datasets", "dashboards"):
        for key, original in before[kind].items():
            for field, value in original.items():
                after = candidate[kind][key][field]
                if after != value:
                    path = f"/{kind}/{key}/{field}"
                    check(path in ALLOWED_PATHS, "PATCH_SCOPE")
                    changes.append({"path": path, "before": value, "after": after})
    check(len(changes) == 22, "PATCH_SCOPE")
    payload = {"before.json": raw["before.json"], "candidate-config.json": encoded(candidate),
               "config-patch.json": encoded(changes), "rollback-fields.json": encoded([
                   {"path": c["path"], "expected": c["after"], "restore": c["before"]} for c in changes])}
    load_bundle(payload, revision)  # Refuse drift from the measured/pinned revision.
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--revision", choices=("ux3-r1", "ux3-r2"), required=True)
    args = parser.parse_args()
    check(not args.output.exists() and not args.output.is_symlink(), "NO_OVERWRITE")
    raw = {}
    for name in BUNDLE_HASHES:
        file = args.bundle_dir / name
        check(file.is_file() and not file.is_symlink(), "BUNDLE_INPUT")
        with file.open("rb") as stream:
            raw[name] = stream.read(2 * 1024 * 1024 + 1)
    payload = build(raw, args.revision)
    args.output.mkdir(parents=True)
    for name, content in payload.items():
        with (args.output / name).open("xb") as stream:
            stream.write(content)
    print(json.dumps({"revision": args.revision, "hashes": hashes_for(args.revision),
                      "verified": all(hashlib.sha256(v).hexdigest() == hashes_for(args.revision)[k]
                                      for k, v in payload.items())}))


if __name__ == "__main__":
    main()
