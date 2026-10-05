"""Normalized wrappers around the existing Bronze identity/membership primitives."""
from src.dq.model import Rule


def check(run, connection, s3, *, parent_sha256=None, bronze_max_id=None):
    from scripts.inspect_context_catalog import inspect_catalog
    from src.common.postgres import find_matches_parent, find_latest_ingestion_objects
    from src.common.bronze_reader import read_bronze_object, verify_bronze_object_metadata
    from src.statsbomb.context import matches_context
    from src.silver.statsbomb.membership import (select_parent_event_artifacts, select_parent_lineup_artifacts,
                                                event_artifact_s3a_path, lineup_artifact_s3a_path)

    def rule(name, dataset='matches', category='source_integrity'):
        return Rule('bronze.' + name, category, 'bronze', dataset, name.replace('_', ' '))

    def resolve():
        inventory = inspect_catalog(connection, run.context)
        hashes = {r['sha256'] for r in inventory['parents']}
        if parent_sha256 is None and len(hashes) != 1:
            raise ValueError('Explicit parent required for ambiguous or absent catalog')
        sha = parent_sha256 or next(iter(hashes))
        boundary = bronze_max_id if bronze_max_id is not None else inventory['bronze_max_id']
        if type(boundary) is not int or boundary <= 0:
            raise ValueError('Invalid Bronze boundary')
        return find_matches_parent(connection, **run.context, sha256=sha), boundary

    ok, resolved = run.call(rule('parent_catalog'), resolve)
    if not ok:
        return None
    parent, boundary = resolved
    ok, raw = run.call(rule('source_hash_valid'), lambda: read_bronze_object(
        s3, bucket=parent['s3_bucket'], key=parent['object_key'], checksum=parent['sha256']))
    if not ok:
        return None
    ok, ids = run.call(rule('parent_context_membership'), lambda: matches_context(raw, **run.context))
    if not ok:
        return None
    run.record(Rule('bronze.match_count', 'operational', 'bronze', 'matches', 'Parent match count', 'INFO'), observed=len(ids))
    for dataset, selector, path in (
        ('match_events', select_parent_event_artifacts, event_artifact_s3a_path),
        ('match_lineups', select_parent_lineup_artifacts, lineup_artifact_s3a_path),
    ):
        ok, selected = run.call(rule(dataset + '_membership', dataset), lambda: selector(ids,
            find_latest_ingestion_objects(connection, source='statsbomb', dataset=dataset,
                                          max_id=boundary, **run.context)))
        if not ok:
            run.record(rule(dataset + '_metadata', dataset), skip=True, reason='prerequisite failed')
            continue
        def verify():
            for artifact in selected:
                path(artifact)
                verify_bronze_object_metadata(s3, artifact)
        run.call(rule(dataset + '_metadata', dataset), verify)
    return ids
