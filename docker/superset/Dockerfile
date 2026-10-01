FROM apache/superset:6.0.0@sha256:6f6c9982bd64d81797bd4f33834f2ce4a4653c8ac8322f1e5f9df9b0332d092a

USER root
COPY requirements/superset.txt /app/requirements/football-superset.txt
RUN uv pip install --python /app/.venv/bin/python \
        --constraint /app/requirements/base.txt \
        --requirement /app/requirements/football-superset.txt \
    && uv pip check --python /app/.venv/bin/python

COPY infrastructure/superset/superset_config.py /app/pythonpath/superset_config.py
COPY infrastructure/superset/init_superset.py /app/pythonpath/init_superset.py
ENV SUPERSET_CONFIG_PATH=/app/pythonpath/superset_config.py \
    SUPERSET_LOAD_EXAMPLES=no
USER superset
