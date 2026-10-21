"""Read-only Docker metadata adapter, reusing the Stage 8C snapshot helpers."""
import re

from src.recovery import runtime
from src.recovery.runtime import identifier, require
from src.recovery.s3_workflow import guarded


class DockerMetadataSource:
    def __init__(self, postgres, clickhouse, *, transport=runtime):
        self.postgres, self.clickhouse, self.transport = postgres, clickhouse, transport

    @guarded
    def snapshot(self):
        io = self.transport
        with io.pg_snapshot(self.postgres) as snapshot:
            catalog = io.registry(self.postgres, snapshot)
            serving = {}
            tables = io.ch_json(self.clickhouse, "SELECT name,engine,sorting_key FROM system.tables "
                                "WHERE database='football' ORDER BY name SETTINGS readonly=2")
            for item in tables:
                require(item['engine'] in ('MergeTree', 'View'), 'UNSUPPORTED_CLICKHOUSE_ENGINE')
                if item['engine'] == 'View':
                    continue
                name = item['name']
                table = 'football.' + identifier(name)
                columns = io.ch_json(self.clickhouse, 'DESCRIBE TABLE ' + table)
                builds = [c['name'] for c in columns if c['name'] in ('silver_build_id', 'gold_build_id')]
                require(len(builds) == 1, 'SERVING_BUILD_COLUMN_MISSING')
                groups = io.ch_json(self.clickhouse, 'SELECT competition_id,season_id,' + builds[0] +
                                    ' AS build_id,count() AS rows FROM ' + table +
                                    ' GROUP BY ALL ORDER BY ALL SETTINGS readonly=2')
                # The server-owned sorting expression is used only after restrictive validation.
                key = item['sorting_key']
                require(isinstance(key, str) and re.fullmatch(r'[A-Za-z0-9_(), ]+', key), 'S3_UNSAFE_SORTING_KEY')
                duplicates = io.ch_json(self.clickhouse, 'SELECT count() AS n FROM (SELECT ' + key +
                                       ',count() AS n FROM ' + table + ' GROUP BY ' + key +
                                       ' HAVING n>1) SETTINGS readonly=2')
                serving[name] = {'groups': groups, 'duplicate_keys': int(duplicates[0]['n'])}
        return {'catalog': catalog, 'serving': serving}
