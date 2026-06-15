FROM python:3.11-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m pip install --upgrade pip \
    && python -m pip install --no-compile --target=/app/site-packages .

FROM gcr.io/distroless/python3-debian12:nonroot AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH="/app/site-packages"

WORKDIR /app

COPY --from=builder --chown=nonroot:nonroot /app/site-packages /app/site-packages

EXPOSE 8000

CMD ["-m", "uvicorn", "aiops_platform.main:app", "--host", "0.0.0.0", "--port", "8000"]
