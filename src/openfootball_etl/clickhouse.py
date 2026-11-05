"""One atomic serving bundle in an explicitly labelled networkless test container."""
import json
import re
import uuid

from src.openfootball_etl.contract import GOLD, KEYS, check, encoded, row_digest
from src.recovery import runtime as io

IMAGE = "clickhouse/clickhouse-server:25.8.23.13-alpine"
TYPES = {"string": "String", "int": "Int32", "bool": "Bool", "date": "Date", "timestamp": "DateTime64(6, 'UTC')"}


def union_fields():
    result = {}
    for fields in GOLD.values():
        for name, kind, _ in fields:
            check(name not in result or result[name] == kind, "UNION_SCHEMA")
            result[name] = kind
    return dict(sorted(result.items()))


class IsolatedClickHouse:
    def __init__(self, container, database):
        check(re.fullmatch(r"pet3-openfootball-ch-[0-9a-f]{12,32}", container), "ISOLATED_CONTAINER")
        check(re.fullmatch(r"pet3_openfootball_[a-z0-9_]{8,48}", database), "ISOLATED_DATABASE")
        template = ('{"id":{{json .Id}},"image":{{json .Config.Image}},"network":{{json .HostConfig.NetworkMode}},'
                    '"ports":{{json .HostConfig.PortBindings}},"mounts":{{json .Mounts}},"labels":{{json .Config.Labels}}}')
        info = json.loads(io.docker("inspect", "--format", template, container))
        check(info["image"] == IMAGE and info["network"] == "none" and not info["ports"] and
              info["labels"].get("pet3.scope") == "openfootball-etl" and
              all(m["Type"] == "tmpfs" for m in info["mounts"]), "ISOLATION_ATTESTATION")
        self.container, self.database = info["id"], database  # Pin ID, not a replaceable name.

    def command(self, sql, data=None):
        return io.docker("exec", "-i", self.container, "clickhouse-client", "--query", sql, data=data)

    def query(self, sql):
        raw = self.command(sql + " SETTINGS readonly=2 FORMAT JSONEachRow")
        return [json.loads(line) for line in raw.splitlines() if line]

    def ensure(self):
        db = self.database
        self.command("CREATE DATABASE IF NOT EXISTS " + db + " ENGINE=Atomic")
        declarations = ["dataset String", "record_key String"] + [
            name + " " + (TYPES[kind] if name == "batch_id" else "Nullable(" + TYPES[kind] + ")")
            for name, kind in union_fields().items()]
        self.command("CREATE TABLE IF NOT EXISTS " + db + ".records (" + ",".join(declarations) +
                     ") ENGINE=MergeTree ORDER BY (batch_id,dataset,record_key)")
        actual = self.command("DESCRIBE TABLE " + db + ".records FORMAT JSONEachRow")
        actual = [(r["name"], r["type"]) for r in (json.loads(line) for line in actual.splitlines())]
        expected = [("dataset", "String"), ("record_key", "String")] + [
            (n, TYPES[t] if n == "batch_id" else "Nullable(" + TYPES[t] + ")") for n, t in union_fields().items()]
        check(actual == expected, "CLICKHOUSE_SCHEMA")
        for dataset, fields in GOLD.items():
            projection = [n if nullable else "assumeNotNull(" + n + ") AS " + n for n, _, nullable in fields]
            self.command("CREATE VIEW IF NOT EXISTS " + db + "." + dataset + " AS SELECT " + ",".join(projection) +
                         " FROM " + db + ".records WHERE dataset='" + dataset + "'")

    def read(self, dataset, table="records"):
        check(dataset in GOLD and re.fullmatch(r"records|candidate_[0-9a-f]{32}", table), "TABLE_SCOPE")
        columns = ",".join(n for n, _, _ in GOLD[dataset])
        return self.query("SELECT " + columns + " FROM " + self.database + "." + table +
                          " WHERE dataset='" + dataset + "' ORDER BY record_key")

    def matches(self, datasets, table="records"):
        counts = self.query("SELECT count() AS n,uniqExact(tuple(dataset,record_key)) AS unique_keys FROM " +
                            self.database + "." + table)[0]
        expected_count = sum(len(rows) for rows in datasets.values())
        check(int(counts["n"]) == int(counts["unique_keys"]) == expected_count, "CLICKHOUSE_COUNTS_OR_DUPLICATES")
        for name, rows in datasets.items():
            actual = self.read(name, table)
            # Exported Spark dates and native CH dates are both ISO strings here.
            check(len(actual) == len(rows) and row_digest(actual) == row_digest(rows), "CLICKHOUSE_CONTENT")
            if table == "records":
                view_rows = self.query("SELECT " + ",".join(n for n, _, _ in GOLD[name]) + " FROM " +
                    self.database + "." + name + " ORDER BY " + ",".join(KEYS[name]))
                check(row_digest(view_rows) == row_digest(rows), "SERVING_VIEW_CONTENT")
        return {name: len(rows) for name, rows in datasets.items()}

    def publish(self, datasets, *, fault=None):
        check(set(datasets) == set(GOLD), "GOLD_DATASETS")
        self.ensure()
        existing = int(self.query("SELECT count() AS n FROM " + self.database + ".records")[0]["n"])
        if existing:
            return "REUSED", self.matches(datasets)
        candidate = "candidate_" + uuid.uuid4().hex
        self.command("CREATE TABLE " + self.database + "." + candidate + " AS " + self.database + ".records")
        records = []
        for name, rows in datasets.items():
            check(rows and len(rows) <= 4096, "LOAD_LIMIT")
            for row in rows:
                check(set(row) == {n for n, _, _ in GOLD[name]}, "LOAD_COLUMNS")
                records.append({**{n: None for n in union_fields()}, **row, "dataset": name,
                                "record_key": encoded([row[k] for k in KEYS[name]]).decode()})
        split = max(1, len(records) // 2) if fault is not None else len(records)
        def insert(rows):
            if rows:
                self.command("INSERT INTO " + self.database + "." + candidate + " FORMAT JSONEachRow",
                             b"\n".join(encoded(row) for row in rows))
        insert(records[:split])
        if fault is not None:
            fault()
        insert(records[split:])
        self.matches(datasets, candidate)
        # One generation switch for all four datasets; never four partial table INSERTs.
        self.command("EXCHANGE TABLES " + self.database + ".records AND " + self.database + "." + candidate)
        return "CREATED", self.matches(datasets)
