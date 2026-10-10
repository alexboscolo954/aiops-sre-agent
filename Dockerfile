FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

FROM python:3.12-slim
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin aiops
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY runbooks ./runbooks
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1 AIOPS_IN_CLUSTER=true
USER 10001
EXPOSE 8080
ENTRYPOINT ["aiops"]
CMD ["serve"]
