"""Narrow, explicitly authorized Gold handoff; never runs ETL or touches StatsBomb.

Four views share one records table. Candidate validation precedes one EXCHANGE.
Old/partial generations are retained, never dropped or truncated by this module.
"""
from dataclasses import dataclass
import json
import re
import uuid

from src.openfootball_etl.clickhouse import IMAGE, TYPES, union_fields
from src.openfootball_etl.contract import GOLD, KEYS, check, encoded, row_digest
from src.openfootball_etl.serving_contract import (
    AUTHORIZATION, DATABASE, HOST, PINNED, PREFIX, RECORDS, valid_uuid, validate_bundle,
)
from src.recovery import runtime as io

VIEWS = tuple(PREFIX + name for name in GOLD)


def allowed(name):
    return name in (RECORDS, *VIEWS) or bool(re.fullmatch(PREFIX + r"candidate_[0-9a-f]{32}", name))


def declarations():
    return [("dataset", "String"), ("record_key", "String")] + [
        (name, TYPES[kind] if name == "batch_id" else "Nullable(" + TYPES[kind] + ")")
        for name, kind in union_fields().items()]


def permitted_sql(sql):
    """Exact generated statements, not a generic production SQL escape hatch."""
    suffix = " SETTINGS readonly=2 FORMAT JSONEachRow"
    sql = sql.removesuffix(suffix)
    statements = {"SELECT toString(serverUUID()) AS server_uuid",
        "SELECT engine FROM system.databases WHERE name='football'",
        "SELECT name,toString(uuid) AS uuid,engine,create_table_query FROM system.tables "
        "WHERE database='football' AND startsWith(name,'" + PREFIX + "') ORDER BY name",
        "DESCRIBE TABLE football." + RECORDS,
        "CREATE TABLE football." + RECORDS + " (" + ",".join(n + " " + t for n, t in declarations()) +
        ") ENGINE=MergeTree ORDER BY (batch_id,dataset,record_key)"}
    candidates = set(re.findall(PREFIX + r"candidate_[0-9a-f]{32}\b", sql))
    for name in (RECORDS, *candidates):
        table = DATABASE + "." + name
        statements.add("SELECT count() AS n,uniqExact(tuple(dataset,record_key)) AS unique_keys FROM " + table)
        statements.add("SELECT count() AS n FROM " + table)
        if name != RECORDS:
            statements.add("CREATE TABLE " + table + " AS football." + RECORDS)
            statements.add("INSERT INTO " + table + " FORMAT JSONEachRow")
            statements.add("EXCHANGE TABLES football." + RECORDS + " AND " + table)
        for dataset, fields in GOLD.items():
            columns = ",".join(n for n, _, _ in fields)
            statements.add("SELECT " + columns + " FROM " + table + " WHERE dataset='" + dataset +
                           "' ORDER BY " + ",".join(KEYS[dataset]))
    for dataset, fields in GOLD.items():
        projection = [n if null else "assumeNotNull(" + n + ") AS " + n for n, _, null in fields]
        view = DATABASE + "." + PREFIX + dataset
        statements.add("CREATE VIEW " + view + " AS SELECT " + ",".join(projection) +
                       " FROM football." + RECORDS + " WHERE dataset='" + dataset + "'")
        statements.add("SELECT " + ",".join(n for n, _, _ in fields) + " FROM " + view + " ORDER BY " + ",".join(KEYS[dataset]))
    return sql in statements


@dataclass(frozen=True)
class Target:
    container_id: str
    server_uuid: str
    production: bool
    image_id: str = ""


def attest_isolated(info):
    # Docker may report --tmpfs only in HostConfig.Tmpfs, not in Mounts.
    tmpfs = json.loads(io.docker("inspect", "--format", "{{json .HostConfig.Tmpfs}}", info["id"])) or {}
    image = io.docker("inspect", "--format", "{{.Config.Image}}", info["id"]).decode().strip()
    check(info["network"] == "none" and not info["ports"] and
          image == IMAGE and
          set(tmpfs) == {"/var/lib/clickhouse", "/var/log/clickhouse-server"} and
          all(m["Type"] == "tmpfs" for m in info["mounts"]) and
          info["labels"].get("pet3d.scope") == "historical-rehearsal", "ISOLATION_ATTESTATION")


class PersistentPublisher:
    def __init__(self, target, expected_namespace, *, authorization=None):
        check(not target.production or authorization == AUTHORIZATION, "BLOCKED_PRODUCTION_AUTHORIZATION")
        check(re.fullmatch(r"[0-9a-f]{64}", target.container_id) and valid_uuid(target.server_uuid), "TARGET_IDENTITY")
        info = io.container_info(HOST if target.production else target.container_id)
        check(info["id"] == target.container_id, "TARGET_IDENTITY")
        if target.production:
            check(bool(re.fullmatch(r"sha256:[0-9a-f]{64}", target.image_id)) and
                  info["image"] == target.image_id and
                  info["labels"].get("com.docker.compose.project") == "football-data-platform" and
                  info["labels"].get("com.docker.compose.service") == HOST, "PRODUCTION_TARGET_MISMATCH")
        else:
            attest_isolated(info)
        self.target = target
        identity = self.query("SELECT toString(serverUUID()) AS server_uuid")[0]
        check(identity == {"server_uuid": target.server_uuid}, "SERVER_IDENTITY")
        check(self.query("SELECT engine FROM system.databases WHERE name='football'") == [{"engine": "Atomic"}], "ATOMIC_DATABASE")
        check(self.fingerprint() == expected_namespace, "NAMESPACE_DRIFT")
        self.expected_namespace = expected_namespace

    @classmethod
    def production(cls, *, authorization=None, expected_container_id="", expected_image_id="",
                   expected_server_uuid="", expected_namespace=""):
        check(authorization == AUTHORIZATION, "BLOCKED_PRODUCTION_AUTHORIZATION")
        check(re.fullmatch(r"[0-9a-f]{64}", expected_container_id) and
              re.fullmatch(r"sha256:[0-9a-f]{64}", expected_image_id), "TARGET_PIN_REQUIRED")
        info = io.container_info(HOST)
        check(info["id"] == expected_container_id and info["image"] == expected_image_id and
              info["labels"].get("com.docker.compose.project") == "football-data-platform" and
              info["labels"].get("com.docker.compose.service") == "football-clickhouse", "PRODUCTION_TARGET_MISMATCH")
        return cls(Target(info["id"], expected_server_uuid, True, expected_image_id), expected_namespace, authorization=authorization)

    @classmethod
    def rehearsal(cls, container, *, expected_namespace, confirm_isolated=False):
        check(confirm_isolated and re.fullmatch(r"pet3d-fix-ch-[0-9a-f]{12}", container), "ISOLATED_TARGET_REQUIRED")
        info = io.container_info(container)
        image = io.docker("inspect", "--format", "{{.Config.Image}}", info["id"]).decode().strip()
        check(image == IMAGE, "ISOLATED_IMAGE")
        attest_isolated(info)
        raw = io.docker("exec", info["id"], "clickhouse-client", "--query", "SELECT toString(serverUUID()) FORMAT TSV")
        return cls(Target(info["id"], raw.decode().strip(), False), expected_namespace)

    def command(self, sql, data=None):
        check(permitted_sql(sql) and (data is None or sql.startswith("INSERT INTO football." + PREFIX + "candidate_")), "SQL_ALLOWLIST")
        if self.target.production:
            return io.ch_query(self.target.container_id, sql, data)
        return io.docker("exec", "-i", self.target.container_id, "clickhouse-client",
                         "--output_format_json_quote_64bit_integers=0", "--query", sql, data=data)

    def query(self, sql):
        return [json.loads(line) for line in self.command(sql + " SETTINGS readonly=2 FORMAT JSONEachRow").splitlines() if line]

    def objects(self):
        rows = self.query("SELECT name,toString(uuid) AS uuid,engine,create_table_query FROM system.tables "
                          "WHERE database='football' AND startsWith(name,'" + PREFIX + "') ORDER BY name")
        check(all(allowed(row["name"]) for row in rows), "FOREIGN_NAMESPACE_OBJECT")
        return rows

    def fingerprint(self):
        return io.digest(encoded(self.objects()))

    def table(self, name):
        check(allowed(name), "TABLE_ALLOWLIST")
        return DATABASE + "." + name

    def object_uuid(self, name):
        check(allowed(name), "TABLE_ALLOWLIST")
        rows = [row for row in self.objects() if row["name"] == name]
        check(len(rows) == 1, "OBJECT_MISSING")
        return rows[0]["uuid"]

    def ensure(self):
        check(self.fingerprint() == self.expected_namespace, "NAMESPACE_DRIFT")
        names = {row["name"] for row in self.objects()}
        if RECORDS not in names:
            check(not names, "INCOMPLETE_NAMESPACE")
            self.command("CREATE TABLE " + self.table(RECORDS) + " (" +
                ",".join(n + " " + t for n, t in declarations()) + ") ENGINE=MergeTree ORDER BY (batch_id,dataset,record_key)")
        actual = self.query("DESCRIBE TABLE " + self.table(RECORDS))
        check([(r["name"], r["type"]) for r in actual] == declarations(), "SERVING_SCHEMA")
        check(next(row for row in self.objects() if row["name"] == RECORDS)["engine"] == "MergeTree", "SERVING_ENGINE")
        for dataset, fields in GOLD.items():
            name = PREFIX + dataset
            if name not in names:
                projection = [n if null else "assumeNotNull(" + n + ") AS " + n for n, _, null in fields]
                self.command("CREATE VIEW " + self.table(name) + " AS SELECT " + ",".join(projection) +
                             " FROM " + self.table(RECORDS) + " WHERE dataset='" + dataset + "'")
        # Refuse an adopted view that could redirect reads into another namespace.
        for dataset, fields in GOLD.items():
            row = next(row for row in self.objects() if row["name"] == PREFIX + dataset)
            projection = [n if null else "assumeNotNull(" + n + ") AS " + n for n, _, null in fields]
            expected = ",".join(projection) + " FROM " + self.table(RECORDS) + " WHERE dataset='" + dataset + "'"
            actual_select = re.split(r"\bAS\s+SELECT\s+", row["create_table_query"], maxsplit=1)
            normalize = lambda text: re.sub(r"\s+|`", "", text)
            check(row["engine"] == "View" and len(actual_select) == 2 and
                  normalize(actual_select[1]) == normalize(expected), "VIEW_DEFINITION")
        self.expected_namespace = self.fingerprint()

    def read_bundle(self, table=RECORDS):
        return {name: self.query("SELECT " + ",".join(n for n, _, _ in GOLD[name]) + " FROM " + self.table(table) +
            " WHERE dataset='" + name + "' ORDER BY " + ",".join(KEYS[name])) for name in GOLD}

    def validate(self, table=RECORDS, *, allow_empty=False):
        counts = self.query("SELECT count() AS n,uniqExact(tuple(dataset,record_key)) AS unique_keys FROM " + self.table(table))[0]
        if allow_empty and counts == {"n": 0, "unique_keys": 0}:
            return "EMPTY"
        expected_count = sum(count for _, count, _ in PINNED.datasets)
        check(counts == {"n": expected_count, "unique_keys": expected_count}, "SERVING_COUNTS")
        validate_bundle(self.read_bundle(table))
        if table == RECORDS:
            for name, _, digest in PINNED.datasets:
                rows = self.query("SELECT " + ",".join(n for n, _, _ in GOLD[name]) + " FROM " +
                                  self.table(PREFIX + name) + " ORDER BY " + ",".join(KEYS[name]))
                check(row_digest(rows) == digest, "SERVING_VIEW_CONTENT")
        return "PINNED"

    def publish(self, data, *, fault=None):
        check(fault is None or not self.target.production, "PRODUCTION_FAULT_INJECTION_DISABLED")
        validate_bundle(data)  # All provenance/content gates precede any mutation.
        self.ensure()
        previous_state = self.validate(allow_empty=True)
        if previous_state == "PINNED":
            return {"status": "REUSED", "batch_id": PINNED.batch_id, "namespace_sha256": self.fingerprint()}
        previous_uuid = self.object_uuid(RECORDS)
        candidate = PREFIX + "candidate_" + uuid.uuid4().hex
        self.command("CREATE TABLE " + self.table(candidate) + " AS " + self.table(RECORDS))
        candidate_uuid = self.object_uuid(candidate)
        records = []
        for name, rows in data.items():
            for row in rows:
                records.append({**{n: None for n in union_fields()}, **row, "dataset": name,
                                "record_key": encoded([row[k] for k in KEYS[name]]).decode()})
        cut = len(records) // 2
        for index, chunk in enumerate((records[:cut], records[cut:])):
            self.command("INSERT INTO " + self.table(candidate) + " FORMAT JSONEachRow", b"\n".join(encoded(row) for row in chunk))
            if index == 0 and fault is not None:
                fault()
        self.validate(candidate)
        check(self.object_uuid(RECORDS) == previous_uuid and self.object_uuid(candidate) == candidate_uuid, "GENERATION_CONFLICT")
        self.command("EXCHANGE TABLES " + self.table(RECORDS) + " AND " + self.table(candidate))
        check(self.object_uuid(RECORDS) == candidate_uuid and self.object_uuid(candidate) == previous_uuid, "GENERATION_CONFLICT")
        self.validate()
        self.expected_namespace = self.fingerprint()
        return {"status": "CREATED", "batch_id": PINNED.batch_id, "server_uuid": self.target.server_uuid,
                "container_id": self.target.container_id, "candidate": candidate, "published_uuid": candidate_uuid,
                "previous_uuid": previous_uuid, "previous_state": previous_state, "namespace_sha256": self.expected_namespace}

    def rollback(self, receipt):
        check(receipt.get("status") == "CREATED" and receipt.get("batch_id") == PINNED.batch_id and
              receipt.get("container_id") == self.target.container_id and receipt.get("server_uuid") == self.target.server_uuid and
              receipt.get("previous_state") == "EMPTY", "ROLLBACK_RECEIPT")
        candidate = receipt.get("candidate", "")
        check(bool(re.fullmatch(PREFIX + r"candidate_[0-9a-f]{32}", candidate)), "ROLLBACK_ALLOWLIST")
        check(self.fingerprint() == receipt.get("namespace_sha256") and
              self.object_uuid(RECORDS) == receipt.get("published_uuid") and
              self.object_uuid(candidate) == receipt.get("previous_uuid"), "ROLLBACK_CONFLICT")
        self.validate()
        check(self.validate(candidate, allow_empty=True) == receipt["previous_state"], "PREVIOUS_STATE_DRIFT")
        self.command("EXCHANGE TABLES " + self.table(RECORDS) + " AND " + self.table(candidate))
        check(self.object_uuid(RECORDS) == receipt["previous_uuid"], "ROLLBACK_CONFLICT")
        check(self.validate(allow_empty=True) == "EMPTY", "ROLLBACK_CONTENT")
        self.expected_namespace = self.fingerprint()
        return {"status": "ROLLED_BACK", "retained_uuid": self.object_uuid(candidate), "namespace_sha256": self.expected_namespace}
