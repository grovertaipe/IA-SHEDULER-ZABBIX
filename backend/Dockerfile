# zabbix-ai-maintenance-v2 backend image (Req 18.1).
#
# Builds a runnable image for the v2 clean structure. The WSGI entry point is
# the Flask app factory `app:create_app` (module-level `application` also exists
# in app.py). No secrets are baked into the image: every credential is provided
# at runtime via environment variables / env_file (Req 18.4, 18.5).
FROM python:3.12-slim

# Avoid .pyc files and unbuffer stdout/stderr for clean container logs.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=5005

# Create an unprivileged user; the app never runs as root.
RUN useradd -m -u 10001 appuser

WORKDIR /app

# System dependencies: curl is only needed for the HEALTHCHECK.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Install pinned dependencies first to leverage layer caching (Req 1.6).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy ONLY the v2 package (clean structure). The legacy monolith `main.py` and
# `requirements.legacy.txt` are intentionally NOT copied; `.dockerignore` also
# excludes tests, caches and any local `.env`.
COPY config.py app.py pyproject.toml ./
COPY api/ ./api/
COPY ai/ ./ai/
COPY core/ ./core/
COPY services/ ./services/
COPY zabbix/ ./zabbix/
COPY i18n/ ./i18n/
COPY cache/ ./cache/
COPY observability/ ./observability/

# Expose the service port.
EXPOSE 5005

# Health probe hits the /health endpoint (Req 16.1).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

# Run as the unprivileged user and serve the app factory via gunicorn.
# IMPORTANT: target the app factory `app:create_app()` (NOT the legacy main:app).
USER appuser
CMD ["gunicorn", "--bind", "0.0.0.0:5005", "--workers", "2", "--timeout", "60", "app:create_app()"]
