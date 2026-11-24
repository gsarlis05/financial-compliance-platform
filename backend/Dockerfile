# syntax=docker/dockerfile:1.7
# Backend API image: Django + gunicorn, non-root, read-only-root-filesystem compatible.
# Build:  docker build -t fcp-backend backend/
# Runs with DJANGO_SETTINGS_MODULE=fcp.settings.prod; configuration comes from the environment.

FROM python:3.13.18-slim-bookworm AS build
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never PIP_NO_CACHE_DIR=1
# Optional build secret "extra_ca": a CA bundle for builds behind a TLS-inspecting proxy.
# Absent in CI and AWS builds; never copied into a layer.
ARG CA_SECRET=/run/secrets/extra_ca
WORKDIR /app
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -f "$CA_SECRET" ]; then export PIP_CERT="$CA_SECRET" SSL_CERT_FILE="$CA_SECRET"; fi; \
    pip install --no-cache-dir "uv==0.11.32" \
    && python -c "import urllib.request as u; u.urlretrieve('https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem', '/app/rds-global-bundle.pem')"
COPY pyproject.toml uv.lock ./
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -f "$CA_SECRET" ]; then export SSL_CERT_FILE="$CA_SECRET"; fi; \
    uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -f "$CA_SECRET" ]; then export SSL_CERT_FILE="$CA_SECRET"; fi; \
    uv sync --frozen --no-dev --no-editable

FROM python:3.13.18-slim-bookworm AS runtime
# TLS trust for Amazon RDS (POSTGRES_SSLMODE=verify-full).
COPY --from=build --chmod=644 /app/rds-global-bundle.pem /etc/ssl/certs/rds-global-bundle.pem
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin fcp
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY manage.py gunicorn.conf.py ./
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DJANGO_SETTINGS_MODULE=fcp.settings.prod
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).status != 200)"]
# Migrations are NOT run here: they run as a separate one-off task with DB_ROLE=owner.
CMD ["gunicorn", "-c", "gunicorn.conf.py", "fcp.wsgi"]
