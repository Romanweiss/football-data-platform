"""Session-scoped S3A configuration; credentials stay in the environment."""

import os
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from pyspark.sql import SparkSession

CREDENTIAL_PROVIDER = "software.amazon.awssdk.auth.credentials.EnvironmentVariableCredentialsProvider"
S3A_IMPLEMENTATION = "org.apache.hadoop.fs.s3a.S3AFileSystem"

HADOOP_OPTIONS = {
    "fs.s3a.impl": S3A_IMPLEMENTATION,
    "fs.s3a.path.style.access": "false",
    "fs.s3a.connection.ssl.enabled": "true",
    "fs.s3a.aws.credentials.provider": CREDENTIAL_PROVIDER,
    "mapreduce.outputcommitter.factory.scheme.s3a": "org.apache.hadoop.fs.s3a.commit.S3ACommitterFactory",
    "fs.s3a.committer.name": "directory",
    "fs.s3a.committer.staging.conflict-mode": "fail",
    "fs.s3a.committer.staging.unique-filenames": "true",
    "fs.s3a.committer.abort.pending.uploads": "true",
    "fs.s3a.multipart.purge": "false",
    # Directory committer stages Parquet/pending-upload metadata locally, not Bronze JSON.
    "fs.s3a.committer.staging.tmp.path": "file:///tmp/football-s3a-commits",
    "fs.s3a.buffer.dir": "/tmp/football-s3a-buffer",
    "mapreduce.fileoutputcommitter.marksuccessfuljobs": "true",
}
SPARK_OPTIONS = {
    "spark.sql.sources.commitProtocolClass": "org.apache.spark.internal.io.cloud.PathOutputCommitProtocol",
    "spark.sql.parquet.output.committer.class": "org.apache.spark.internal.io.cloud.BindingParquetOutputCommitter",
}


def configure_s3a(spark: "SparkSession") -> None:
    """Configure before any S3A filesystem is created. Never copy secret values."""
    names = ("S3_ENDPOINT", "S3_REGION", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")
    missing = [name for name in names if not os.environ.get(name, "").strip()]
    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
    endpoint = os.environ["S3_ENDPOINT"]
    region = os.environ["S3_REGION"]
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
        or parsed.path not in ("", "/") or parsed.query or parsed.fragment
        or endpoint.strip() != endpoint or any(char.isspace() for char in endpoint)
    ):
        raise ValueError("S3_ENDPOINT must be a plain HTTPS endpoint without credentials, bucket or query.")
    if region.strip() != region or any(char.isspace() for char in region):
        raise ValueError("S3_REGION must be a nonempty region identifier.")
    conf = spark.sparkContext._jsc.hadoopConfiguration()
    for name, value in {
        **HADOOP_OPTIONS, "fs.s3a.endpoint": endpoint, "fs.s3a.endpoint.region": region,
    }.items():
        conf.set(name, value)
    for name, value in SPARK_OPTIONS.items():
        spark.conf.set(name, value)


def runtime_versions(spark: "SparkSession") -> dict[str, str]:
    """Resolve the filesystem class without initializing a remote filesystem."""
    jvm = spark.sparkContext._jvm
    conf = spark.sparkContext._jsc.hadoopConfiguration()
    return {
        "Spark version": spark.version,
        "Hadoop version": jvm.org.apache.hadoop.util.VersionInfo.getVersion(),
        "S3A filesystem implementation": jvm.org.apache.hadoop.fs.FileSystem.getFileSystemClass(
            "s3a", conf,
        ).getName(),
    }
