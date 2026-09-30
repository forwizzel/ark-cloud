FROM python:3.14.7-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN addgroup --system arkcloud && adduser --system --ingroup arkcloud arkcloud

COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir ".[dev]"

COPY alembic.ini ./
COPY alembic ./alembic

USER arkcloud

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
