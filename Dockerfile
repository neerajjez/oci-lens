# Stage 1: install dependencies
FROM python:3.12-slim AS builder
WORKDIR /install
COPY requirements.txt .
RUN pip install --prefix=/install --no-cache-dir -r requirements.txt

# Stage 2: runtime image
FROM python:3.12-slim
WORKDIR /app

# Non-root user
RUN useradd -m -u 1000 appuser

COPY --from=builder /install /usr/local
COPY src/ src/
COPY main.py pyproject.toml ./
COPY config/config.example.yaml config/config.example.yaml

RUN mkdir -p logs reports config && chown -R appuser:appuser /app
USER appuser

ENV LOG_FORMAT=json \
    LOG_LEVEL=INFO \
    PYTHONUNBUFFERED=1

HEALTHCHECK --interval=60s --timeout=15s --retries=3 \
  CMD python main.py health || exit 2

ENTRYPOINT ["python", "main.py"]
CMD ["health"]
