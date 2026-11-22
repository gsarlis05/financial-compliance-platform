#!/usr/bin/env bash
# Version 1 on your own computer (V1-3, docs/user-guide/install-on-your-computer.md).
#
#   scripts/local/fcp.sh install --email you@example.com   first time: build, start, create your sign-in
#   scripts/local/fcp.sh start | stop | status | logs [service]
#   scripts/local/fcp.sh backup                            database, sign-in data, documents, secrets
#   scripts/local/fcp.sh restore backups/fcp-....tar.gz    replace everything with a backup
#   scripts/local/fcp.sh upgrade                           backup, rebuild from this checkout, migrate
#   scripts/local/fcp.sh verify                            audit chain, ledger and actuals checks
#
# Everything runs in Docker and listens on 127.0.0.1 only. Nothing is sent anywhere.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DIR="$ROOT/deploy/local"
ENV_FILE="$DIR/.env"
BACKUPS="${FCP_BACKUPS:-$ROOT/backups}"
compose() { docker compose --project-directory "$DIR" -f "$DIR/compose.yaml" --env-file "$ENV_FILE" "$@"; }
say() { printf '%s\n' "$*"; }
die() { printf 'Error: %s\n' "$*" >&2; exit 1; }
secret() { python3 -c "import secrets; print(secrets.token_urlsafe($1))"; }

need_docker() {
  command -v docker >/dev/null || die "Docker is not installed. Install Docker Desktop (or Docker Engine) first."
  docker info >/dev/null 2>&1 || die "Docker is not running. Start Docker and try again."
  docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is needed (docker compose)."
}

write_env() {
  [ -f "$ENV_FILE" ] && return 0
  umask 077
  cat > "$ENV_FILE" <<ENV
# Secrets of your local platform. Keep this file; backups contain a copy. Never share it.
DJANGO_SECRET_KEY=$(secret 50)
POSTGRES_PASSWORD=$(secret 24)
POSTGRES_OWNER_PASSWORD=$(secret 24)
POSTGRES_APP_PASSWORD=$(secret 24)
KEYCLOAK_DB_PASSWORD=$(secret 24)
KEYCLOAK_ADMIN_PASSWORD=$(secret 24)
OIDC_CLIENT_SECRET=$(secret 32)
S3_ACCESS_KEY=fcp$(secret 9 | tr -dc 'A-Za-z0-9' | head -c 12)
S3_SECRET_KEY=$(secret 32)
ENV
  say "Secrets written to deploy/local/.env (readable by you only)."
}

build() {
  local flags=()
  if [ -n "${BUILD_CA:-}" ]; then  # behind a TLS-inspecting proxy, as in `make images`
    flags=(--network host --secret "id=extra_ca,src=$BUILD_CA" --build-arg HTTPS_PROXY --build-arg https_proxy)
  fi
  say "Building the application images (a few minutes the first time)..."
  docker build "${flags[@]}" -q -t fcp-backend:local "$ROOT/backend" >/dev/null
  docker build "${flags[@]}" -q -t fcp-web:local "$ROOT/frontend" >/dev/null
}

wait_ready() {
  say "Waiting for the platform to start..."
  for _ in $(seq 1 120); do
    # The API answers 401 to an anonymous /api/me once it is up behind the web server.
    if [ "$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8088/api/me)" = "401" ] \
       && curl -fs http://localhost:8080/realms/fcp/.well-known/openid-configuration >/dev/null 2>&1; then
      return 0
    fi
    sleep 3
  done
  compose ps
  die "The platform did not start in time. See: scripts/local/fcp.sh logs"
}

kcadm() {
  compose exec -T keycloak /opt/keycloak/bin/kcadm.sh "$@"
}

create_owner() {
  local email="$1" password
  password="$(secret 12)Aa1"
  kcadm config credentials --server http://localhost:8080 --realm master --user admin \
    --password "$(grep '^KEYCLOAK_ADMIN_PASSWORD=' "$ENV_FILE" | cut -d= -f2-)" >/dev/null
  if kcadm get users -r fcp -q "email=$email" --fields id | grep -q '"id"'; then
    say "A sign-in for $email already exists."
    return 0
  fi
  kcadm create users -r fcp -s "username=$email" -s "email=$email" -s enabled=true \
    -s emailVerified=true -s 'requiredActions=["CONFIGURE_TOTP","UPDATE_PASSWORD"]' >/dev/null
  kcadm set-password -r fcp --username "$email" --new-password "$password" --temporary >/dev/null
  say ""
  say "Your sign-in:   $email"
  say "First password: $password   (shown once; you choose a new one at first sign-in)"
  say "At first sign-in you also set up an authenticator app (one-time codes)."
}

cmd_install() {
  local email=""
  while [ $# -gt 0 ]; do
    case "$1" in --email) email="${2:-}"; shift 2 ;; *) die "Unknown option $1" ;; esac
  done
  [ -n "$email" ] || die "Give your email address: scripts/local/fcp.sh install --email you@example.com"
  need_docker
  write_env
  build
  compose up -d
  wait_ready
  compose exec -T api python manage.py documents_dev_bucket >/dev/null
  create_owner "$email"
  say ""
  say "Ready. Open http://localhost:8088 and sign in."
  say "Emails the platform sends (alerts) appear at http://localhost:8025."
  say "Make a backup now and then: scripts/local/fcp.sh backup"
}

cmd_backup() {
  need_docker
  [ -f "$ENV_FILE" ] || die "Not installed yet."
  mkdir -p "$BACKUPS"
  local stamp work out
  stamp="$(date -u +%Y%m%d-%H%M%S)"
  work="$(mktemp -d)"
  trap 'rm -rf "$work"' RETURN
  say "Backing up the database, sign-in data and documents..."
  compose exec -T postgres pg_dump -U postgres -Fc fcp > "$work/fcp.dump"
  compose exec -T postgres pg_dump -U postgres -Fc keycloak > "$work/keycloak.dump"
  compose exec -T objectstore tar -C /data -cf - . > "$work/documents.tar"
  cp "$ENV_FILE" "$work/env"
  printf 'created=%s\nversion=%s\n' "$stamp" "$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)" > "$work/manifest"
  (cd "$work" && sha256sum fcp.dump keycloak.dump documents.tar env manifest > SHA256SUMS)
  out="$BACKUPS/fcp-$stamp.tar.gz"
  umask 077
  tar -C "$work" -czf "$out" .
  say "Backup written: $out"
  say "It holds your books and your secrets: keep it somewhere safe (an encrypted disk)."
}

cmd_restore() {
  local file="${1:-}"
  [ -f "$file" ] || die "Give a backup file: scripts/local/fcp.sh restore backups/fcp-....tar.gz"
  need_docker
  local work
  work="$(mktemp -d)"
  trap 'rm -rf "$work"' RETURN
  tar -C "$work" -xzf "$file"
  (cd "$work" && sha256sum -c --quiet SHA256SUMS) || die "The backup is damaged (checksums do not match)."
  say "This replaces everything in your local platform with the backup of $(grep '^created=' "$work/manifest" | cut -d= -f2)."
  if [ "${FCP_YES:-}" != "1" ]; then
    read -r -p "Type RESTORE to continue: " answer
    [ "$answer" = "RESTORE" ] || die "Cancelled."
  fi
  compose down >/dev/null 2>&1 || true
  docker volume rm fcp-local_pgdata fcp-local_documents >/dev/null 2>&1 || true
  umask 077
  cp "$work/env" "$ENV_FILE"
  compose up -d postgres objectstore
  for _ in $(seq 1 60); do compose exec -T postgres pg_isready -U postgres -d fcp >/dev/null 2>&1 && break; sleep 2; done
  sleep 3
  # As the superuser, keeping every object's owner: the roles exist (created on first start), and
  # some functions must stay owned by fcp_maintenance (see scripts/db/create_roles.sql).
  compose exec -T postgres pg_restore -U postgres -d fcp --exit-on-error < "$work/fcp.dump"
  compose exec -T postgres pg_restore -U postgres -d keycloak --exit-on-error < "$work/keycloak.dump"
  compose exec -T objectstore sh -c 'tar -C /data -xf -' < "$work/documents.tar"
  compose restart objectstore >/dev/null
  compose up -d
  wait_ready
  cmd_verify
  say "Restored."
}

cmd_verify() {
  need_docker
  say "Checking the audit chain, the ledger and the reported actuals..."
  compose exec -T -e DB_ROLE=owner -e POSTGRES_OWNER_USER=fcp_owner \
    -e "POSTGRES_OWNER_PASSWORD=$(grep '^POSTGRES_OWNER_PASSWORD=' "$ENV_FILE" | cut -d= -f2-)" api \
    sh -c 'python manage.py audit_verify && python manage.py ledger_integrity_check && python manage.py actuals_verify'
}

cmd_upgrade() {
  need_docker
  [ -f "$ENV_FILE" ] || die "Not installed yet."
  cmd_backup
  build
  compose up -d   # the migrate service runs first; the API waits for it
  wait_ready
  cmd_verify
  say "Upgraded to $(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo 'this checkout')."
}

case "${1:-}" in
  install) shift; cmd_install "$@" ;;
  start) need_docker; compose up -d; wait_ready; say "Running: http://localhost:8088" ;;
  stop) need_docker; compose stop; say "Stopped. Your data is kept." ;;
  status) need_docker; compose ps ;;
  logs) need_docker; shift; compose logs --tail 200 "$@" ;;
  backup) cmd_backup ;;
  restore) shift; cmd_restore "$@" ;;
  upgrade) cmd_upgrade ;;
  verify) cmd_verify ;;
  *) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
