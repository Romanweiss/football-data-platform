FROM python:3.12.14-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

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

WORKDIR /app

COPY requirements/tools.txt /tmp/requirements/tools.txt
RUN python -m pip install --requirement /tmp/requirements/tools.txt

CMD ["python", "--version"]
