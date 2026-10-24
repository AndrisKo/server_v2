# 1. Этап сборки зависимостей
FROM python:3.13-slim AS builder

WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# 2. Финальный образ приложения
FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    libjpeg62-turbo \
    zlib1g \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /root/.local /root/.local

COPY app.py .
COPY utils/ ./utils/
COPY templates/ ./templates/
COPY static/ ./static/

ENV PATH=/root/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    STORAGE_DIR=/images \
    LOG_DIR=/app/logs \
    PORT=8000 \
    HOST=0.0.0.0

EXPOSE 8000

CMD ["python", "app.py"]