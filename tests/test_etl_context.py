"""Stage 6B-1 generic contracts; synthetic IDs and no external services."""
import argparse
import io
import json
import os
import unittest
from contextlib import ExitStack, redirect_stdout, redirect_stderr
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.statsbomb.context import (catalog_context, matches_context, matches_url, matches_prefix,
                                  child_prefix, add_bronze_arguments, SourceContextError)
from src.common.bronze import build_versioned_key
from src.common.postgres import find_matches_parent, find_latest_ingestion_objects
from src.silver.build_identity import build_specification, calculate_build_id, input_fingerprint, silver_prefix
from src.gold import build_identity as gold_identity
from src.gold.stats_snapshot import validate_context_snapshot
from src.gold.manifest import GoldIntegrityError
from src.analytics import loader, gold_loader
from src.analytics.specs import SPECS
from src.analytics.gold_specs import V2_SPECS, RESULTS
from src.analytics.validation import expected_metrics, ClickHouseIntegrityError
from src.analytics.job import LoadDiagnostics


CONTEXTS = (dict(competition_id=7, season_id=9), dict(competition_id=80, season_id=10))


class SourceContextTests(unittest.TestCase):
    def test_authoritative_resolution_and_context_separated_bronze_keys(self):
        raw = json.dumps([dict(**c, competition_name="Synthetic league", season_name="Test") for c in CONTEXTS]).encode()
        keys = set()
        for context in CONTEXTS:
            self.assertEqual(catalog_context(raw, **context)["competition_id"], context["competition_id"])
            self.assertTrue(matches_url(**context).endswith(f"/matches/{context['competition_id']}/{context['season_id']}.json"))
            for prefix, name in ((matches_prefix(**context), "matches.json"),
                                 (child_prefix("events", 1, **context), "events.json"),
                                 (child_prefix("lineups", 1, **context), "lineups.json")):
                keys.add(build_versioned_key(prefix, name, "a" * 64))
            parent = json.dumps([dict(match_id=1, competition={"competition_id": context["competition_id"]},
                                      season={"season_id": context["season_id"]})]).encode()
            self.assertEqual(matches_context(parent, **context), [1])
            other = CONTEXTS[1] if context == CONTEXTS[0] else CONTEXTS[0]
            with self.assertRaises(SourceContextError): matches_context(parent, **other)
        self.assertEqual(len(keys), 6)
        for invalid in (b"[]", b"{}", raw):
            with self.assertRaises(SourceContextError): catalog_context(invalid, competition_id=999, season_id=99)

    def test_explicit_snapshot_arguments_required(self):
        parser = argparse.ArgumentParser(exit_on_error=False)
        add_bronze_arguments(parser, children=True)
        args = parser.parse_args(["--competition-id", "7", "--season-id", "9", "--parent-sha256", "a" * 64,
                                  "--bronze-max-id", "123"])
        self.assertEqual((args.competition_id, args.season_id, args.bronze_max_id), (7, 9, 123))
        # Python 3.10 exits for missing required args even with exit_on_error=False;
        # newer argparse raises ArgumentError. Both must reject the missing snapshot.
        errors = io.StringIO()
        with redirect_stderr(errors), self.assertRaises((argparse.ArgumentError, SystemExit)) as raised:
            parser.parse_args([])
        if isinstance(raised.exception, SystemExit):
            self.assertEqual(raised.exception.code, 2)
            detail = errors.getvalue()
        else:
            detail = str(raised.exception)
        for option in ('--competition-id', '--season-id', '--parent-sha256', '--bronze-max-id'):
            self.assertIn(option, detail)

    def test_parent_sql_binds_context_url_and_exact_hash_and_children_cutoff(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [("bucket", "key", "a" * 64, 1, None, "statsbomb", "matches", matches_url(**CONTEXTS[0]))]
        find_matches_parent(connection, **CONTEXTS[0], sha256="a" * 64)
        sql, parameters = cursor.execute.call_args.args
        self.assertIn("sha256 = %s", sql)
        self.assertIn(matches_url(**CONTEXTS[0]), parameters)
        cursor.fetchall.return_value = []
        find_latest_ingestion_objects(connection, source="statsbomb", dataset="match_events", max_id=123, **CONTEXTS[0])
        sql, parameters = cursor.execute.call_args.args
        self.assertIn("id <= %s", sql)
        self.assertIn(123, parameters)
        self.assertTrue(any(isinstance(v, str) and "/competition_id=7/season_id=9/" in v for v in parameters))

    def test_build_identity_is_deterministic_and_context_sensitive(self):
        identities = set()
        for context in CONTEXTS:
            parent = dict(source="statsbomb", dataset="matches", source_url=matches_url(**context), s3_bucket="bucket",
                          object_key=build_versioned_key(matches_prefix(**context), "matches.json", "a" * 64), sha256="a" * 64)
            fingerprint = input_fingerprint([parent], artifact_kind="matches")
            spec = build_specification(**context, dataset="matches", transform_version="matches_v1",
                                       input_fingerprint=fingerprint, schema_sha256="b" * 64)
            build_id = calculate_build_id(spec)
            self.assertEqual(build_id, calculate_build_id(dict(reversed(list(spec.items())))))
            identities.add(silver_prefix(spec, build_id))
            gold = gold_identity.build_specification(**context, dataset="match_results", transform_version="match_results_v1",
                                                     input_fingerprint=fingerprint, schema_sha256="b" * 64)
            identities.add(gold_identity.gold_prefix(gold, gold_identity.calculate_build_id(gold)))
        self.assertEqual(len(identities), 4)

    def test_generic_v2_exact_lineage_and_cross_context_rejection(self):
        pins = {name: str(i) * 64 for i, name in enumerate(gold_identity.REQUIRED_INPUTS, 1)}
        context = CONTEXTS[0]
        inputs = [dict(dataset=name, build_id=value, s3_prefix=f"football/silver/statsbomb/{name}/competition_id=7/season_id=9/build_id={value}/")
                  for name, value in pins.items()]
        validate_context_snapshot(inputs, pins, **context)
        for wrong in (inputs[:-1], inputs + inputs[:1], [{**inputs[0], "build_id": "f" * 64}, *inputs[1:]]):
            with self.assertRaises(GoldIntegrityError): validate_context_snapshot(wrong, pins, **context)
        with self.assertRaises(GoldIntegrityError): validate_context_snapshot(inputs, pins, **CONTEXTS[1])


class ExactResolverContextTests(unittest.TestCase):
    def test_every_loader_target_resolves_exact_pins_and_rejects_other_contexts(self):
        from src.analytics import silver_input, gold_input
        from src.silver.manifest import SilverIntegrityError

        # Synthetic endpoint is only validated as a string; no service IO is used.
        environment = {"S3_ENDPOINT": "https://s3.ru-3.storage.selcloud.ru", "S3_BUCKET": "test-bucket"}
        with patch.dict(os.environ, environment, clear=True):
            for layer, module, specs, error_type in (
                ("silver", silver_input, SPECS.values(), SilverIntegrityError),
                ("gold", gold_input, [*V2_SPECS.values(), RESULTS], GoldIntegrityError),
            ):
                resolve = getattr(module, f"resolve_{layer}_build")
                prefix = silver_prefix if layer == "silver" else gold_identity.gold_prefix
                for spec in specs:
                    for context in CONTEXTS:
                        with self.subTest(layer=layer, dataset=spec.dataset, context=context):
                            identity = dict(source="statsbomb", layer=layer, dataset=spec.dataset, **context,
                                            transform_version=spec.transform_version, input_fingerprint="a" * 64,
                                            schema_sha256="b" * 64)
                            build_id = calculate_build_id(identity)
                            build = dict(identity, build_id=build_id, s3_bucket="test-bucket",
                                         s3_prefix=prefix(identity, build_id), row_count=4, file_count=1)
                            with patch.object(module, f"find_{layer}_build", return_value=build) as exact, \
                                 patch.object(module, f"find_latest_{layer}_build") as latest:
                                self.assertEqual(resolve(None, build_id, **context, spec=spec), build)
                                exact.assert_called_once_with(None, dataset=spec.dataset, **context, build_id=build_id)
                                for field, value in (("competition_id", 999), ("season_id", 999),
                                                     ("build_id", "f" * 64), ("transform_version", "wrong")):
                                    exact.return_value = dict(build, **{field: value})
                                    with self.assertRaises(error_type):
                                        resolve(None, build_id, **context, spec=spec)
                                exact.return_value = None
                                with self.assertRaises(error_type):
                                    resolve(None, build_id, **context, spec=spec)
                                latest.assert_not_called()


class ContextTarget:
    """Aggregate fake evaluates bound context/build scopes, not one global target."""
    def __init__(self, spec, gold):
        self.spec, self.gold = spec, gold
        self.rows, self.inserts = {}, []

    def query(self, sql, *, parameters, **kwargs):
        if "uniqExact(" + ("gold" if self.gold else "silver") + "_build_id)" in sql:
            assert "competition_id = %(competition_id)s AND season_id = %(season_id)s" in sql
            selected = [m for m in self.rows.values() if all(m[k] == parameters[k] for k in ("competition_id", "season_id"))]
            count = sum(m["row_count"] for m in selected)
            other = sum(m["row_count"] for m in selected if m["build_id"] != parameters["build_id"])
            row = (count, len(selected), other) + (() if self.gold else (parameters["build_id"],))
        else:
            assert "WHERE " + ("gold" if self.gold else "silver") + "_build_id = %(build_id)s" in sql
            manifest = self.rows.get(parameters["build_id"])
            row = expected_metrics(manifest, self.spec) if manifest else (0,) * len(expected_metrics(self.active, self.spec))
        return SimpleNamespace(result_rows=[row])

    def command(self, sql, **kwargs):
        assert sql.startswith("INSERT INTO " + self.spec.target)
        self.inserts.append(sql)
        self.rows[self.active["build_id"]] = dict(self.active)


class LoaderCoexistenceTests(unittest.TestCase):
    def test_all_silver_and_gold_tables_coexist_repeat_and_conflict_safely(self):
        for gold, specs in ((False, SPECS.values()), (True, [*V2_SPECS.values(), RESULTS])):
            module = gold_loader if gold else loader
            for spec in specs:
                with self.subTest(gold=gold, dataset=spec.dataset), ExitStack() as stack:
                    target = ContextTarget(spec, gold)
                    catalog = {}
                    kind = "gold" if gold else "silver"
                    stack.enter_context(patch.object(module, "validate_table_schema"))
                    stack.enter_context(patch.object(module, "validate_extra"))
                    stack.enter_context(patch.object(module, "source_metrics", side_effect=lambda *a, **k: expected_metrics(target.active, spec)))
                    stack.enter_context(patch.object(module, "find_clickhouse_" + ("gold_load" if gold else "load"),
                                                    side_effect=lambda *a, **k: catalog.get(k[kind + "_build_id"])))
                    def register(connection, **record):
                        catalog[record[kind + "_build_id"]] = record
                        return True
                    stack.enter_context(patch.object(module, "register_clickhouse_" + ("gold_load" if gold else "load"), side_effect=register))
                    stack.enter_context(redirect_stdout(io.StringIO()))
                    run = module.load_gold if gold else module.load_dataset
                    builds = []
                    for context in CONTEXTS:
                        identity = dict(**context, source="statsbomb", layer=kind, dataset=spec.dataset,
                                        transform_version=spec.transform_version, input_fingerprint="a" * 64, schema_sha256="b" * 64)
                        build = dict(**identity, build_id=calculate_build_id(identity), s3_bucket="bucket", s3_prefix="exact/",
                                     row_count=4, file_count=1, match_count=2)
                        target.active = build
                        result = run(target, None, build, build, "unused", spec=spec, check_only=False, diagnostics=LoadDiagnostics())
                        self.assertEqual(result["output_status"], "LOADED")
                        self.assertIn("ALREADY_LOADED", run(target, None, build, build, "unused", spec=spec, check_only=False, diagnostics=LoadDiagnostics())["output_status"])
                        builds.append(build)
                    self.assertEqual(len(target.rows), 2)
                    self.assertEqual(len(target.inserts), 2)
                    target.active = dict(builds[0], build_id="f" * 64)
                    with self.assertRaises(ClickHouseIntegrityError):
                        run(target, None, target.active, target.active, "unused", spec=spec, check_only=False, diagnostics=LoadDiagnostics())
                    self.assertEqual(len(target.inserts), 2)
                    self.assertEqual(target.rows[builds[0]["build_id"]], builds[0])


class PreflightTests(unittest.TestCase):
    def test_public_preflight_only_reads_authoritative_context_urls(self):
        from scripts import check_statsbomb_source as script
        context = CONTEXTS[0]
        catalog = json.dumps([dict(**context, competition_name="League", season_name="Test")]).encode()
        matches = json.dumps([dict(match_id=1, competition={"competition_id": 7}, season={"season_id": 9},
                                   home_team={"home_team_id": 10}, away_team={"away_team_id": 20})]).encode()
        with patch.object(script, "download_bytes", side_effect=[catalog, matches]), patch.object(script, "head", side_effect=lambda url: url) as head:
            result = script.inspect_source(context)
        self.assertEqual((result["match_count"], result["team_count"], result["events_available"], result["lineups_available"]), (1, 2, 1, 1))
        self.assertEqual({call.args[0].rsplit("/data/", 1)[1] for call in head.call_args_list}, {"events/1.json", "lineups/1.json"})

    def test_bronze_preflight_checks_both_domains_without_publication(self):
        from scripts import check_statsbomb_bronze as script
        from src.silver.diagnostics import PublishDiagnostics
        parent = {"s3_bucket": "bucket", "object_key": "parent", "sha256": "a" * 64}
        raw = b'[{"match_id":1,"competition":{"competition_id":7},"season":{"season_id":9}}]'
        artifacts = []
        for kind in ("events", "lineups"):
            artifacts.append([dict(source_url=f"https://raw.githubusercontent.com/hudl/open-data/master/data/{kind}/1.json",
                                   s3_bucket="bucket", object_key=build_versioned_key(child_prefix(kind, 1, **CONTEXTS[0]), kind + ".json", "a" * 64),
                                   sha256="a" * 64, size_bytes=1)])
        client = MagicMock()
        with patch.object(script, "find_matches_parent", return_value=parent), patch.object(script, "read_bronze_object", return_value=raw), \
             patch.object(script, "find_latest_ingestion_objects", side_effect=artifacts) as find, \
             patch.object(script, "verify_bronze_object_metadata") as verify, redirect_stdout(io.StringIO()):
            script.check_bronze(None, client, context=CONTEXTS[0], parent_sha256="a" * 64, bronze_max_id=12, diagnostics=PublishDiagnostics())
        self.assertEqual(verify.call_count, 2)
        self.assertEqual(find.call_args.kwargs["max_id"], 12)
        self.assertEqual(find.call_args.kwargs["competition_id"], 7)
        self.assertEqual(client.mock_calls, [])

    def test_inventory_uses_only_select_and_bound_context(self):
        from scripts.inspect_context_catalog import inspect_catalog
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (123,)
        cursor.fetchall.return_value = []
        result = inspect_catalog(connection, CONTEXTS[0])
        self.assertEqual(result["bronze_max_id"], 123)
        self.assertTrue(all(call.args[0].startswith("SELECT ") for call in cursor.execute.call_args_list))
        self.assertEqual(cursor.execute.call_args.args[1], (7, 9))
