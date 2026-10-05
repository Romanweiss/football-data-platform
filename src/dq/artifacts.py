"""Exact-build checks reusing existing manifest and loader validators; no writes."""
from src.dq.model import Rule


def check(run, connection, s3, client, *, layer, dataset, build_id, expected_inputs=None):
    from src.analytics.specs import SPECS
    from src.analytics.gold_specs import V2_SPECS, RESULTS
    from src.analytics.silver_input import resolve_silver_build, verify_silver_manifest, parquet_url
    from src.analytics.gold_input import resolve_gold_build, verify_gold_manifest
    from src.analytics.validation import source_metrics, validate_metrics, validate_extra, S3_SOURCE
    from src.analytics.loader import load_dataset
    from src.analytics.gold_loader import load_gold
    from src.analytics.job import LoadDiagnostics
    from src.gold.stats_snapshot import validate_context_snapshot

    spec = (SPECS if layer == 'silver' else {**V2_SPECS, 'match_results': RESULTS})[dataset]
    def rule(name, category):
        return Rule(f'{layer}.{dataset}.{name}', category, layer, dataset, name.replace('_', ' '))
    resolve = resolve_silver_build if layer == 'silver' else resolve_gold_build
    ok, build = run.call(rule('catalog_identity', 'source_integrity'), lambda: resolve(
        connection, build_id, **run.context, spec=spec), build_id=build_id)
    if not ok:
        return
    verify = (lambda: verify_silver_manifest(s3, build, spec=spec)) if layer == 'silver' else lambda: verify_gold_manifest(s3, build)
    ok, manifest = run.call(rule('manifest_integrity', 'source_integrity'), verify, build_id=build_id)
    if not ok:
        return
    if layer == 'gold' and spec.version == 'v2':
        ok, _ = run.call(rule('silver_lineage', 'source_integrity'), lambda: validate_context_snapshot(
            manifest['inputs'], expected_inputs or {}, **run.context), build_id=build_id)
        if not ok:
            return
    url = parquet_url(build)
    ok, metrics = run.call(rule('parquet_metrics_read', 'operational'), lambda: source_metrics(client, url, spec=spec), build_id=build_id)
    if not ok:
        return
    run.record(Rule(f'{layer}.{dataset}.row_count', 'operational', layer, dataset, 'Parquet row count', 'INFO'),
               observed=metrics[0], expected=manifest['row_count'], build_id=build_id)
    run.record(Rule(f'{layer}.{dataset}.grain_count', 'structural', layer, dataset, 'Distinct grain count', 'INFO'),
               observed=metrics[2 if spec.has_match_count else 1], expected=manifest['row_count'], build_id=build_id)
    ok, _ = run.call(rule('structure_domain_counts', 'structural'), lambda: validate_metrics(metrics, manifest, spec=spec), build_id=build_id)
    if not ok:
        return
    if spec.two_teams_per_match:
        run.call(rule('team_coverage', 'referential'), lambda: validate_extra(client, S3_SOURCE, {'url':url}, spec=spec), build_id=build_id)
    # Preserve the entire existing preflight/recovery contract. check_only guarantees
    # no INSERT, registrations, cleanup or lock acquisition; aggregate scans only.
    loader = load_dataset if layer == 'silver' else load_gold
    run.call(rule('loader_preflight', 'reconciliation'), lambda: loader(
        client, connection, build, manifest, url, spec=spec, check_only=True, diagnostics=LoadDiagnostics()), build_id=build_id)
