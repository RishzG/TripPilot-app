# One image for the web process and the procrastinate worker (D-50: build once, promote it).
#
#   stage 1  python builder   uv sync --frozen, then dump the OpenAPI schema
#   stage 2  node builder     npm ci, generate the typed client from that schema, build the SPA
#   stage 3  python runtime   the venv, the source, alembic.ini and web/dist
#
# The worker uses the same image with the command
#   procrastinate --app=trippilot.jobs.app.app worker

FROM python:3.12-slim AS py-build
COPY --from=ghcr.io/astral-sh/uv:0.11.14 /uv /uvx /bin/
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_PREFERENCE=only-system \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY scripts ./scripts
RUN uv sync --frozen --no-dev
RUN /app/.venv/bin/python scripts/dump_openapi.py /out/openapi.json

FROM node:22-slim AS web-build
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
COPY --from=py-build /out/openapi.json ./openapi.json
RUN npm run gen:api && npm run build

FROM python:3.12-slim AS runtime
ARG GIT_SHA=dev
ENV APP_GIT_SHA=$GIT_SHA \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    WEB_DIST_DIR=/app/web/dist
RUN useradd --system --no-create-home --uid 10001 app
WORKDIR /app
COPY --from=py-build /app/.venv /app/.venv
COPY src ./src
COPY alembic.ini ./
COPY scripts ./scripts
COPY --from=web-build /web/dist ./web/dist
USER app
EXPOSE 8000
# Shell form so ${PORT:-8000} expands (Render sets PORT).
CMD uvicorn trippilot.app:create_app --factory --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --no-access-log
