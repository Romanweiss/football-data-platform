"""In-memory Gold/Silver metadata fixtures; no cloud or database access."""

from clickhouse_model_fakes import dataset_fixture
from silver_fakes import FakeS3
from src.analytics.specs import SPECS
from src.gold.build_identity import REQUIRED_INPUTS, build_specification, input_fingerprint


def silver_inputs(required=REQUIRED_INPUTS):
    client, builds, manifests = FakeS3(), [], {}
    for name in required:
        s3, build, manifest = dataset_fixture(SPECS[name])
        client.objects.update(s3.objects)
        builds.append(build)
        manifests[name] = manifest
    client.calls.clear()
    return client, builds, manifests


def specification(builds, dataset="team_match_stats"):
    return build_specification(dataset=dataset, competition_id=43, season_id=106,
                               transform_version=dataset + "_v1", input_fingerprint=input_fingerprint(builds),
                               schema_sha256="b" * 64)


def seed_output(client, bucket, prefix, partitions=1):
    client.seed(bucket, prefix + "_SUCCESS", b"{}")
    for index in range(partitions):
        client.seed(bucket, prefix + f"part-{index:05d}.snappy.parquet")
