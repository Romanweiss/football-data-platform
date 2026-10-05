# Compose supplies the existing project Spark image as this build context.
FROM project_spark

USER root
RUN apt-get update && apt-get install -y --no-install-recommends python3-venv \
    && apt-get clean && rm -rf /var/lib/apt/lists/*
# The older proven Spark image predates the ClickHouse loader dependency.
# Install the project's existing pins without upgrading satisfied Spark deps.
COPY requirements/tools.txt /tmp/project-requirements.txt
RUN /usr/bin/python3 -m pip install --no-cache-dir --requirement /tmp/project-requirements.txt \
    && /usr/bin/python3 -m pip check
COPY requirements/airflow.txt /tmp/airflow-requirements.txt
RUN wget --no-verbose -O /tmp/airflow-constraints.txt \
      https://raw.githubusercontent.com/apache/airflow/constraints-3.2.2/constraints-3.10.txt \
    && echo 'a2d9cf1e1c61fbcd6a5c40bb51bbad82034c346b7ab2859a643654a1221ebf8e  /tmp/airflow-constraints.txt' | sha256sum -c - \
    && /usr/bin/python3 -m venv /opt/airflow-venv \
    && /opt/airflow-venv/bin/pip install --no-cache-dir \
      --constraint /tmp/airflow-constraints.txt --requirement /tmp/airflow-requirements.txt \
    && /opt/airflow-venv/bin/pip check \
    && useradd --uid 50000 --gid 0 --home-dir /opt/airflow --create-home airflow

COPY --chown=50000:0 infrastructure/airflow/ /opt/airflow/config/
COPY --chown=50000:0 dags/ /opt/airflow/dags/
COPY --chown=50000:0 src/ /app/src/
COPY --chown=50000:0 scripts/ /app/scripts/
COPY --chown=50000:0 tests/ /app/tests/
RUN mkdir -p /app/data/work && chown -R 50000:0 /app/data

ENV AIRFLOW_HOME=/opt/airflow \
    PATH="/opt/airflow-venv/bin:/opt/spark/bin:${PATH}" \
    PYTHONPATH=/app \
    PYSPARK_PYTHON=/usr/bin/python3 \
    PYSPARK_DRIVER_PYTHON=/usr/bin/python3 \
    PROJECT_PYTHON=/usr/bin/python3
WORKDIR /app
USER 50000:0
ENTRYPOINT []
CMD ["airflow", "version"]
