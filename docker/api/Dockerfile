FROM python:3.12.14-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements/api.txt /tmp/requirements-api.txt
RUN python -m pip install --requirement /tmp/requirements-api.txt \
    && useradd --uid 10001 --create-home api
COPY application /app/application
COPY src/common/__init__.py src/common/clickhouse.py /app/src/common/
COPY manage.py /app/manage.py
COPY scripts/check_application_api.py /app/scripts/check_application_api.py
USER api
EXPOSE 8000
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000", "--noreload"]
