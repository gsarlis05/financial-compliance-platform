#!/usr/bin/env bash
# Production-like smoke test of the container images (M2-0). Local and CI only; deploys nothing.
#
# Runs the images the way AWS ECS would: non-root, read-only root filesystem, production settings,
# TLS to PostgreSQL (a throwaway server with a self-signed certificate stands in for RDS), the
# migration as a separate one-off task with the owner role, then the API and the web front end.
#
# Usage: scripts/ci/container-smoke.sh [backend-image] [web-image]
set -euo pipefail

API_IMAGE="${1:-fcp-backend:dev}"
WEB_IMAGE="${2:-fcp-web:dev}"
NET="fcp-smoke-net"
WORK="$(mktemp -d)"
PG="fcp-smoke-pg"; API="fcp-smoke-api"; WEB="fcp-smoke-web"

cleanup() {
  docker rm -f "$PG" "$API" "$WEB" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
  rm -rf "$WORK"
}
trap cleanup EXIT
cleanup_quiet() { docker rm -f "$PG" "$API" "$WEB" >/dev/null 2>&1 || true; }
cleanup_quiet
docker network create "$NET" >/dev/null

fail() { echo "FAIL: $*" >&2; docker logs "$API" 2>&1 | tail -5 | cut -c1-300 >&2 || true; exit 1; }
rand() { python3 -c "import secrets; print(secrets.token_urlsafe($1))"; }

echo "1. PostgreSQL 17 with TLS (stand-in for RDS)"
openssl req -new -x509 -days 1 -nodes -subj "/CN=$PG" -keyout "$WORK/server.key" -out "$WORK/server.crt" 2>/dev/null
chmod 644 "$WORK/server.crt"; chmod 600 "$WORK/server.key"
docker run -d --name "$PG" --network "$NET" -e POSTGRES_PASSWORD="$(rand 24)" -e POSTGRES_DB=fcp \
  -v "$WORK:/tls-src:ro" --entrypoint sh postgres:17.11 -c \
  'cp /tls-src/server.* /var/lib/postgresql/ && chown postgres /var/lib/postgresql/server.* && chmod 600 /var/lib/postgresql/server.key && exec docker-entrypoint.sh postgres -c ssl=on -c ssl_cert_file=/var/lib/postgresql/server.crt -c ssl_key_file=/var/lib/postgresql/server.key' >/dev/null
for _ in $(seq 1 30); do docker exec "$PG" pg_isready -U postgres -d fcp >/dev/null 2>&1 && break; sleep 1; done
sleep 2
OWNER_PW="$(rand 24)"; APP_PW="$(rand 24)"
docker cp scripts/db/create_roles.sql "$PG:/tmp/roles.sql"
docker exec "$PG" psql -q -U postgres -v owner_password="$OWNER_PW" -v app_password="$APP_PW" -v db_name=fcp -f /tmp/roles.sql >/dev/null

ENV_ARGS=(
  -e DJANGO_SECRET_KEY="$(rand 50)" -e DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost,"$API" -e CSRF_TRUSTED_ORIGINS=https://localhost
  -e POSTGRES_HOST="$PG" -e POSTGRES_DB=fcp -e POSTGRES_SSLMODE=verify-full -e POSTGRES_SSLROOTCERT=/tls/ca.crt
  -e POSTGRES_OWNER_USER=fcp_owner -e POSTGRES_OWNER_PASSWORD="$OWNER_PW"
  -e POSTGRES_APP_USER=fcp_app -e POSTGRES_APP_PASSWORD="$APP_PW"
  -e OIDC_ISSUER=https://id.example.test/realms/fcp -e OIDC_CLIENT_ID=fcp-backend -e OIDC_CLIENT_SECRET="$(rand 24)"
  -e OIDC_REDIRECT_URI=https://localhost/auth/callback -e OIDC_POST_LOGOUT_REDIRECT_URI=https://localhost/
  -e DOCUMENTS_BUCKET=fcp-documents-smoke -e DOCUMENTS_KMS_KEY_ID=smoke-test-not-used -e CLAMD_HOST=clamav.invalid
)
RUN_ARGS=(--network "$NET" --read-only --tmpfs /tmp -v "$WORK/server.crt:/tls/ca.crt:ro")

echo "2. Deployment checks (manage.py check --deploy)"
docker run --rm "${RUN_ARGS[@]}" "${ENV_ARGS[@]}" "$API_IMAGE" python manage.py check --deploy --fail-level WARNING

echo "3. Migration task (DB_ROLE=owner, TLS verify-full)"
docker run --rm "${RUN_ARGS[@]}" "${ENV_ARGS[@]}" -e DB_ROLE=owner "$API_IMAGE" python manage.py migrate --noinput >/dev/null

echo "4. API service (runtime role, non-root)"
docker run -d --name "$API" "${RUN_ARGS[@]}" "${ENV_ARGS[@]}" "$API_IMAGE" >/dev/null
[ "$(docker exec "$API" id -u)" = "10001" ] || fail "API does not run as uid 10001"

echo "5. Web front end (unprivileged nginx)"
docker run -d --name "$WEB" --network "$NET" -p 127.0.0.1:18089:8080 --read-only \
  --tmpfs /tmp:uid=101,gid=101 --tmpfs /etc/nginx/conf.d:uid=101,gid=101 \
  -e API_UPSTREAM="http://$API:8000" -e IDP_ORIGIN=https://id.example.test "$WEB_IMAGE" >/dev/null

check() {  # check <name> <expected-status> <url> [grep-pattern]
  local status body
  for _ in $(seq 1 30); do
    status="$(curl -s -o "$WORK/body" -w '%{http_code}' "$3" || true)"
    [ "$status" = "$2" ] && break; sleep 1
  done
  body="$(cat "$WORK/body" 2>/dev/null || true)"
  [ "$status" = "$2" ] || fail "$1: expected $2, got $status: ${body:0:200}"
  if [ -n "${4:-}" ]; then grep -q "$4" <<<"$body" || fail "$1: body lacks $4"; fi
  echo "   ok  $1 ($status)"
}
check "web serves the app" 200 http://127.0.0.1:18089/ 'id="root"'
check "deep links fall back to the app" 200 http://127.0.0.1:18089/w/demo/e/x/entries 'id="root"'
check "API reachable through the web origin (anonymous)" 401 http://127.0.0.1:18089/api/me 'auth.unauthenticated'
docker run --rm --network "$NET" curlimages/curl:8.17.0 -s "http://$API:8000/readyz" | grep -q '"database": "ok"' \
  || fail "readiness probe did not report the database as ok"
echo "   ok  API readiness probe (database over TLS)"
headers="$(curl -sI http://127.0.0.1:18089/)"
for h in "Content-Security-Policy: default-src 'self'" "X-Frame-Options: DENY" "Cache-Control: no-store"; do
  grep -qi "$h" <<<"$headers" || fail "missing header: $h"
done
echo "   ok  security headers"
tls="$(docker exec "$PG" psql -U postgres -d fcp -tAc "SELECT bool_and(ssl) FROM pg_stat_ssl JOIN pg_stat_activity USING (pid) WHERE usename = 'fcp_app'")"
[ "$tls" = "t" ] || fail "runtime database connections are not encrypted"
echo "   ok  runtime database connections use TLS"

echo "6. Scheduled job tasks (integrity checks, audit verification)"
docker run --rm "${RUN_ARGS[@]}" "${ENV_ARGS[@]}" -e DB_ROLE=owner "$API_IMAGE" \
  sh -c "python manage.py ledger_integrity_check && python manage.py audit_verify" >/dev/null

echo "7. Bank statement import worker (runtime role, one pass)"
docker run --rm "${RUN_ARGS[@]}" "${ENV_ARGS[@]}" "$API_IMAGE" \
  python manage.py banking_process_imports >/dev/null || fail "import worker did not run"
echo "   ok  import worker runs with the runtime role"

echo "Container smoke test passed."
