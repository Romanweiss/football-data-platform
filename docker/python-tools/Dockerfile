FROM python:3.12.14-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements/tools.txt /tmp/requirements/tools.txt
RUN python -m pip install --requirement /tmp/requirements/tools.txt

CMD ["python", "--version"]
