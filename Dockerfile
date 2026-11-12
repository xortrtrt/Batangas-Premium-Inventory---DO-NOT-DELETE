# syntax=docker/dockerfile:1
FROM python:3.11.10-slim-bookworm AS runtime

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install -r requirements.txt

RUN groupadd --system --gid 10001 inventory && \
    useradd --system --uid 10001 --gid 10001 --home-dir /app inventory && \
    mkdir -p /app/app/static/uploads/profiles && \
    chown -R 10001:10001 /app

COPY --chown=10001:10001 app/ ./app/
COPY --chown=10001:10001 database/ ./database/
COPY --chown=10001:10001 tools/init_db.py tools/migrate_database.py ./tools/

USER 10001:10001

EXPOSE 8000

HEALTHCHECK --interval=20s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)" || exit 1

ENTRYPOINT ["python", "-m", "uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
