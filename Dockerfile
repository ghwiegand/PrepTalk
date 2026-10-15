# Interview coach: LangGraph graph "agent" served by Aegra, flow controlled by FrameX, model = Apertus 1.5 8B
# (OpenAI-compatible endpoint from LLM_BASE_URL; the model itself is not in this image).

# 1. FrameX reasoning engine (Rust, no third-party crates), from the public FrameX core repository; the Python
#    package of the same commit comes in through pyproject.toml
FROM rust:1-slim-bookworm AS framex
ARG FRAMEX_COMMIT=dee72c7fdfa4bcefe4eed5abbec8d457dd7f48e6
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*
RUN git clone https://gitlab.com/ds-unisg/framex-core /framex && cd /framex && git checkout $FRAMEX_COMMIT \
    && cargo build --release --offline

# 2. FHGR challenge datasets (licensed for HackApertus use only, so fetched instead of committed)
FROM alpine/git:latest AS fhgr
ARG FHGR_COMMIT=d8edb68f4944c0c2e70459f6cb00dcade3bc9efa
RUN git clone https://github.com/fhgr/Hackapertus /fhgr && cd /fhgr && git checkout $FHGR_COMMIT

# 3. Aegra + LangGraph, as in the FHGR project template
FROM python:3.12-slim-bookworm AS base
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
RUN addgroup --system app && adduser --system --ingroup app app

FROM base AS builder
COPY --from=ghcr.io/astral-sh/uv:0.10.0 /uv /bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends build-essential libpq-dev git \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project --compile-bytecode
COPY src/ ./src/
RUN uv sync --locked --no-dev --compile-bytecode

FROM base AS final
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl libpq5 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /app/.venv /app/.venv
COPY --from=framex /framex/target/release/framex /usr/local/bin/framex
COPY --from=fhgr /fhgr/datasets ./fhgr/datasets
COPY aegra.json .
COPY src/ ./src/
ENV PATH="/app/.venv/bin:$PATH" FRAMEX_BINARY=/usr/local/bin/framex FHGR_DATA=/app/fhgr/datasets \
    FRAMEX_MODEL_CACHE=/tmp/coach-model-cache
EXPOSE 2026
USER app
CMD ["aegra", "serve"]
