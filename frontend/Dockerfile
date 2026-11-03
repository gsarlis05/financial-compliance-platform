# syntax=docker/dockerfile:1.7
# Web front end image: the built React app served by unprivileged nginx (port 8080).
# Build: docker build -t fcp-web frontend/
# Runtime settings: API_UPSTREAM (e.g. http://api:8000), IDP_ORIGIN (sign-in origin for the
# CSP form-action), FORWARDED_PROTO (https behind a TLS load balancer).

FROM node:22.23.4-bookworm-slim AS build
ARG CA_SECRET=/run/secrets/extra_ca
WORKDIR /app
COPY package.json pnpm-lock.yaml ./
# Optional build secret "extra_ca" for builds behind a TLS-inspecting proxy; never stored in a layer.
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -f "$CA_SECRET" ]; then export NODE_EXTRA_CA_CERTS="$CA_SECRET" npm_config_cafile="$CA_SECRET"; fi; \
    npm install -g pnpm@10.28.0 --no-fund --no-audit && pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

FROM nginxinc/nginx-unprivileged:1.29.8-alpine AS runtime
COPY --from=build /app/dist /usr/share/nginx/html
COPY deploy/*.template /etc/nginx/templates/
ENV API_UPSTREAM=http://api:8000 IDP_ORIGIN=https://id.invalid FORWARDED_PROTO=https \
    NGINX_ENVSUBST_FILTER="^(API_UPSTREAM|IDP_ORIGIN|FORWARDED_PROTO)$"
USER 101
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s CMD wget -qO- http://127.0.0.1:8080/healthz || exit 1
