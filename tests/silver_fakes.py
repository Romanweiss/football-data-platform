"""In-memory S3 fixtures for offline Silver tests. Deliberately no delete API."""

import io

from botocore.exceptions import ClientError
from botocore.response import StreamingBody

from src.common.checksum import sha256_bytes
from src.silver.build_identity import build_specification, input_fingerprint


def artifact(match_id=1, checksum="a" * 64):
    return {
        "match_id": match_id,
        "source_url": f"https://raw.githubusercontent.com/hudl/open-data/master/data/events/{match_id}.json",
        "s3_bucket": "test-bucket",
        "object_key": f"football/bronze/statsbomb/events/match_id={match_id}/sha256={checksum}/events.json",
        "sha256": checksum,
    }


def specification(inputs):
    return build_specification(
        input_fingerprint=input_fingerprint(inputs), schema_sha256="b" * 64,
        transform_version="event_core_v1", competition_id=43, season_id=106,
    )


def error(code, operation="GetObject"):
    return ClientError({"Error": {"Code": code}}, operation)


class FakeS3:
    def __init__(self):
        self.objects = {}
        self.calls = []

    def seed(self, bucket, key, body=b"parquet-fixture", metadata=None):
        self.objects[(bucket, key)] = {
            "Body": body, "Metadata": metadata or {}, "ETag": f'"{sha256_bytes(body)}"',
        }

    def head_object(self, *, Bucket, Key):
        self.calls.append(("head", Bucket, Key))
        if (Bucket, Key) not in self.objects:
            raise error("404", "HeadObject")
        item = self.objects[(Bucket, Key)]
        return {"Metadata": dict(item["Metadata"]), "ContentLength": len(item["Body"]), "ETag": item["ETag"]}

    def get_object(self, *, Bucket, Key):
        self.calls.append(("get", Bucket, Key))
        if (Bucket, Key) not in self.objects:
            raise error("NoSuchKey")
        item = self.objects[(Bucket, Key)]
        return {**item, "Body": StreamingBody(io.BytesIO(item["Body"]), len(item["Body"]))}

    def put_object(self, *, Bucket, Key, Body, Metadata, ContentType, IfNoneMatch):
        self.calls.append(("put", Bucket, Key))
        assert IfNoneMatch == "*"
        assert ContentType == "application/json"
        if (Bucket, Key) in self.objects:
            raise error("PreconditionFailed", "PutObject")
        self.seed(Bucket, Key, Body, Metadata)
        return {}

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return self

    def paginate(self, *, Bucket, Prefix):
        self.calls.append(("list", Bucket, Prefix))
        objects = [
            {"Key": key, "Size": len(item["Body"]), "ETag": item["ETag"]}
            for (bucket, key), item in sorted(self.objects.items())
            if bucket == Bucket and key.startswith(Prefix)
        ]
        for index in range(0, len(objects), 2):
            yield {"Contents": objects[index:index + 2]}

    def close(self):
        self.calls.append(("close",))


def seed_output(client, bucket, prefix):
    client.seed(bucket, prefix, b"")  # S3A directory marker is retained by Hadoop 3.5.
    client.seed(bucket, prefix + "_SUCCESS", b"{}")
    for index in range(4):
        client.seed(bucket, prefix + f"part-{index:05d}-test.snappy.parquet")
