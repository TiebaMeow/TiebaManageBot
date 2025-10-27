# syntax=docker/dockerfile:1.6

FROM python:3.13-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libffi-dev curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip uv

WORKDIR /app

COPY pyproject.toml ./

RUN uv pip install --system --requirements pyproject.toml

# --------- Runtime image ---------
FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    HOST=0.0.0.0 \
    PORT=18765

WORKDIR /app

COPY --from=builder /usr/local /usr/local

RUN mkdir -p "$PLAYWRIGHT_BROWSERS_PATH" \
    && python -m playwright install-deps chromium \
    && python -m playwright install chromium-headless-shell \
    && rm -rf /var/lib/apt/lists/*

RUN addgroup --system bot \
    && adduser --system --ingroup bot bot

COPY . .

RUN chown -R bot:bot /app /ms-playwright

USER bot

VOLUME ["/app/data", "/app/logs"]

EXPOSE 18765

ENTRYPOINT ["python", "bot.py"]
