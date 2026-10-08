"""Source snapshots/recommendations only. Never ingest or auto-trigger ETL."""
from collections import Counter
from datetime import datetime, timezone
import json
from uuid import uuid4

from src.common.checksum import sha256_bytes
from src.common.http import download_bytes, DownloadError
from src.common.source_transport import SourceAccessError
from src.orchestration.commands import context
from src.orchestration.monitoring import registered_contexts
from src.statsbomb.context import CATALOG_URL, matches_url, matches_context


def catalog_entries(raw):
    rows = json.loads(raw)
    if not isinstance(rows,list) or len(rows) > 1000:
        raise ValueError('Invalid source catalog or source-check budget exceeded')
    result = {}
    for row in rows:
        c = context(row)
        pair = tuple(c.values())
        if pair in result:
            raise ValueError('Ambiguous source context')
        result[pair] = sha256_bytes(json.dumps(row,sort_keys=True,separators=(',',':')).encode())
    return result


def change_status(entry, matches, previous, baseline_parent=None, *, first_snapshot=False):
    if previous is None:
        if baseline_parent and matches != baseline_parent:
            return 'CHANGED'
        return 'BASELINE' if first_snapshot else 'NEW'
    return 'UNCHANGED' if (entry,matches)==previous else 'CHANGED'


def discover(connection, *, dry_run=False, downloader=download_bytes, airflow=None):
    from src.alerts.operations import observe_operation
    contexts = registered_contexts(connection)
    with connection.transaction(), connection.cursor() as cur:
        cur.execute('''SELECT DISTINCT ON(o.competition_id,o.season_id)
            o.competition_id,o.season_id,o.entry_sha256,o.matches_sha256
            FROM metadata.source_discovery_observations o JOIN metadata.source_discovery_runs r USING(discovery_id)
            ORDER BY o.competition_id,o.season_id,r.checked_at DESC,r.discovery_id DESC''')
        previous = {tuple(r[:2]):tuple(r[2:]) for r in cur.fetchall()}
        cur.execute('SELECT EXISTS(SELECT 1 FROM metadata.source_discovery_runs)')
        first = not cur.fetchone()[0]
        parents = {}
        for c in contexts:
            url = matches_url(**c)
            cur.execute("SELECT sha256 FROM metadata.ingestion_objects WHERE source='statsbomb' "
                        "AND source_url IN(%s,%s) ORDER BY id DESC LIMIT 1", (url,url.replace('/hudl/','/statsbomb/')))
            row = cur.fetchone()
            parents[tuple(c.values())] = row[0] if row else None
    raw = downloader(CATALOG_URL)  # Existing bounded transient-only retries; no nested loop.
    entries = catalog_entries(raw)
    registered = {tuple(c.values()) for c in contexts}
    matches = {}
    for c in contexts:
        pair = tuple(c.values())
        if pair not in entries:
            continue
        request = {'step':'source_discovery','context':c,'airflow':airflow}
        try:
            payload = downloader(matches_url(**c))
            matches_context(payload,**c)
        except Exception as exc:
            if not dry_run:
                observe_operation(request,passed=False,source_access=isinstance(exc,(DownloadError,SourceAccessError)))
                exc.operation_alert_handled = True
            raise
        matches[pair] = sha256_bytes(payload)
        if not dry_run:
            observe_operation(request,passed=True)
    rows = []
    for pair, entry in sorted(entries.items()):
        match = matches.get(pair)
        # Unregistered contexts have catalog-only observations. Onboarding
        # changes the observation scope and is informational, not automatic ETL.
        old = previous.get(pair)
        status = change_status(entry,match,old,parents.get(pair),first_snapshot=first)
        rows.append((*pair,entry,match,pair in registered,status))
    for pair in sorted((set(previous)|registered)-set(entries)):
        prior = previous.get(pair)
        rows.append((*pair,prior[0] if prior else '0'*64,None,pair in registered,'MISSING'))
    if not dry_run:
        id_ = uuid4()
        with connection.transaction(), connection.cursor() as cur:
            cur.execute('INSERT INTO metadata.source_discovery_runs(discovery_id,checked_at,catalog_sha256) VALUES(%s,%s,%s)',
                        (id_,datetime.now(timezone.utc),sha256_bytes(raw)))
            cur.executemany('INSERT INTO metadata.source_discovery_observations(discovery_id,competition_id,season_id,'
                            'entry_sha256,matches_sha256,registered,status) VALUES(%s,%s,%s,%s,%s,%s,%s)',
                            [(id_,*r) for r in rows])
        observe_operation({'step':'source_discovery','airflow':airflow},passed=True)
    return dict(status='DISCOVERED',dry_run=dry_run,catalog_sha256=sha256_bytes(raw),
                counts=dict(Counter(r[-1] for r in rows)),registered_contexts=len(contexts),
                recommendations=[dict(competition_id=r[0],season_id=r[1],status=r[-1])
                                 for r in rows if r[-1] in ('NEW','CHANGED','MISSING')][:20],
                auto_trigger=False)
