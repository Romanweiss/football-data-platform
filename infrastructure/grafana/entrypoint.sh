#!/bin/sh
set -eu
# Consume runtime secrets privately. No tracing, output, or secret-bearing URL.
GRAFANA_READER_PASSWORD="$(cat /run/grafana-secrets/reader_password)"
export GRAFANA_READER_PASSWORD
exec /run.sh
