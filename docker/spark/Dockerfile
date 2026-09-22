FROM spark:4.2.0-python3

USER root

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYSPARK_PYTHON=python3 \
    PATH="/opt/spark/bin:${PATH}"

# The official image uses Ubuntu/Python 3. Python boto3 needs the same
# system CA bundle as python-tools.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates wget openssl \
    && wget -O /tmp/globalsign-root-r6.der https://secure.globalsign.net/cacert/root-r6.crt \
    && openssl x509 -inform DER -outform PEM \
        -in /tmp/globalsign-root-r6.der \
        -out /usr/local/share/ca-certificates/globalsign-root-r6.crt \
    && update-ca-certificates \
    && rm -f /tmp/globalsign-root-r6.der \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY requirements/tools.txt /tmp/requirements/tools.txt
RUN python3 -m pip install --requirement /tmp/requirements/tools.txt

# S3A subset of spark-hadoop-cloud 4.2.0's published dependency contract.
# Hadoop client, Jackson core/databind, HTTP client and SLF4J already ship in
# this exact Spark image. No Azure/GCS connectors or runtime --packages needed.
RUN set -eu; \
    for artifact in \
      org/apache/spark/spark-hadoop-cloud_2.13/4.2.0/spark-hadoop-cloud_2.13-4.2.0.jar \
      org/apache/hadoop/hadoop-aws/3.5.0/hadoop-aws-3.5.0.jar \
      software/amazon/awssdk/bundle/2.35.4/bundle-2.35.4.jar \
      software/amazon/s3/analyticsaccelerator/analyticsaccelerator-s3/1.3.1/analyticsaccelerator-s3-1.3.1.jar \
      org/wildfly/openssl/wildfly-openssl/2.2.5.Final/wildfly-openssl-2.2.5.Final.jar \
      com/fasterxml/jackson/dataformat/jackson-dataformat-cbor/2.21.2/jackson-dataformat-cbor-2.21.2.jar; \
    do \
      wget --no-verbose -P /opt/spark/jars "https://repo.maven.apache.org/maven2/${artifact}"; \
    done

# Temurin 21's existing cacerts already contains this exact GlobalSign Root R6.
# Fail the build if the pinned base stops providing it; do not replace cacerts.
RUN keytool -exportcert -cacerts -storepass changeit \
      -alias 'cn_globalsign,o_globalsign,ou_globalsign_root_ca__r6 [jdk]' \
      -file /tmp/java-globalsign-r6.der \
    && openssl x509 -inform DER -in /tmp/java-globalsign-r6.der -out /tmp/java-globalsign-r6.pem \
    && openssl x509 -in /tmp/java-globalsign-r6.pem -noout -fingerprint -sha256 \
       | grep -F '2C:AB:EA:FE:37:D0:6C:A2:2A:BA:73:91:C0:03:3D:25:98:29:52:C4:53:64:73:49:76:3A:3A:B5:AD:6C:CF:69' \
    && rm -f /tmp/java-globalsign-r6.der /tmp/java-globalsign-r6.pem

WORKDIR /app
USER spark

CMD ["spark-submit", "--version"]
