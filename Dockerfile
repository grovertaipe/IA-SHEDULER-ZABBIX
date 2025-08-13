FROM python:3.12-slim

# Evita bytecode y buffer en logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Crea usuario no root
RUN useradd -m -u 10001 appuser

WORKDIR /app

# Dependencias del sistema (curl para healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Copia requirements e instala
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia el código
COPY main.py .

# Variables por defecto (puedes sobreescribirlas en runtime)
ENV PORT=5005

# Exponer puerto
EXPOSE 5005

# Healthcheck a /health
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

# Corre con gunicorn (no ejecuta el bloque __main__)
USER appuser
CMD ["gunicorn", "--bind", "0.0.0.0:5005", "--workers", "2", "--timeout", "60", "main:app"]
