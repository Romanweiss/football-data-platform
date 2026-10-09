ARG PYTHON_VERSION=3.12.14
FROM python:${PYTHON_VERSION}-slim-bookworm
WORKDIR /workspace
COPY requirements/ /workspace/requirements/
RUN python -m pip install --no-cache-dir -r requirements/ci.txt
COPY src/ src/
COPY application/ application/
COPY scripts/ scripts/
COPY tests/ tests/
COPY dags/ dags/
COPY infrastructure/ infrastructure/
COPY docker/ docker/
COPY docs/ docs/
COPY frontend/ frontend/
COPY ci/ ci/
COPY .github/ .github/
COPY compose.yaml .env.example .dockerignore ruff.toml README.md manage.py ./
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PLATFORM_ALERTS_ENABLED=false
CMD ["python", "-m", "unittest", "discover", "-s", "tests/ci", "-p", "test_*.py"]
