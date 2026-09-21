FROM spark:4.2.0-python3

USER root

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYSPARK_PYTHON=python3 \
    PATH="/opt/spark/bin:${PATH}"

# The official image uses Ubuntu/Python 3. Python boto3 needs the same
# system CA bundle as python-tools; Java S3A trust is outside Stage 2A.
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

WORKDIR /app
USER spark

CMD ["spark-submit", "--version"]
