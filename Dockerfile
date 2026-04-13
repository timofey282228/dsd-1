ARG PYTHON_TAG=slim

FROM python:${PYTHON_TAG} AS uv

RUN pip install --no-cache-dir uv
ENV UV_COMPILE_BYTECODE=true \
    UV_LINK_MODE=copy \
    UV_NO_DEV=true \
    UV_NO_DEFAULT_GROUPS=true \
    UV_FROZEN=true \
    UV_NO_EDITABLE=true \
    UV_TOOL_BIN_DIR=/usr/local/bin


FROM python:${PYTHON_TAG} AS microservice_base
ENV PATH="/.venv/bin:${PATH}"
WORKDIR /app
USER 666:666
EXPOSE 80


FROM uv AS logging-build
# Install dependencies
RUN --mount=type=cache,target=~/.cache \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=services/logsvc/pyproject.toml,target=services/logsvc/pyproject.toml \
    --mount=type=bind,source=packages,target=packages \
    uv sync --package logsvc --no-install-project
# Install service itself in a different layer
RUN --mount=type=cache,target=~/.cache \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=services/logsvc,target=services/logsvc \
    --mount=type=bind,source=packages,target=packages \
    uv sync --package logsvc


FROM microservice_base AS logging
COPY --link --from=logging-build .venv /.venv
CMD [ "uvicorn", "--host=0.0.0.0", "--port=80", "--no-access-log", "logsvc:api"]


FROM uv AS counter-build
# Install dependencies
RUN --mount=type=cache,target=~/.cache \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=services/countersvc/pyproject.toml,target=services/countersvc/pyproject.toml \
    --mount=type=bind,source=packages,target=packages \
    uv sync --package countersvc --no-install-project
# Install service itself in a different layer
RUN --mount=type=cache,target=~/.cache \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=services/countersvc,target=services/countersvc \
    --mount=type=bind,source=packages,target=packages \
    uv sync --package countersvc


FROM microservice_base AS counter
COPY --link --from=counter-build .venv /.venv
CMD [ "uvicorn", "--host=0.0.0.0", "--port=80", "--no-access-log", "countersvc:api"]


FROM uv AS facade-build
# Install dependencies
RUN --mount=type=cache,target=~/.cache \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=services/facade/pyproject.toml,target=services/facade/pyproject.toml \
    --mount=type=bind,source=packages,target=packages \
    uv sync --package facade --no-install-project
# Install service itself in a different layer
RUN --mount=type=cache,target=~/.cache \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=services/facade,target=services/facade \
    --mount=type=bind,source=packages,target=packages \
    uv sync --package facade


FROM microservice_base AS facade
COPY --link --from=facade-build .venv /.venv
CMD [ "uvicorn", "--host=0.0.0.0", "--port=80", "--no-access-log", "facade:api"]


FROM uv AS config-server-build
# Install dependencies
RUN --mount=type=cache,target=~/.cache \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=services/config-server/pyproject.toml,target=services/config-server/pyproject.toml \
    uv sync --package config-server --no-install-project
# Install service itself in a different layer
RUN --mount=type=cache,target=~/.cache \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=services/config-server,target=services/config-server \
    uv sync --package config-server


FROM microservice_base AS config-server
COPY --link --from=config-server-build .venv /.venv
CMD [ "uvicorn", "--host=0.0.0.0", "--port=80", "--no-access-log", "config_server:api"]
