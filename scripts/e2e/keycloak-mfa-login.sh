#!/usr/bin/env bash
# Creates (or resets) a throwaway local Keycloak user "e2e.owner", then runs the browser check.
# Requires: `make dev` services running, `make run-backend` on :8000, Node with Playwright.
set -euo pipefail
cd "$(dirname "$0")/../.."
set -a; . ./.env; set +a
KC=http://127.0.0.1:8080
TOKEN=$(curl -sf -d client_id=admin-cli -d "username=$KEYCLOAK_ADMIN_USER" \
  -d "password=$KEYCLOAK_ADMIN_PASSWORD" -d grant_type=password \
  "$KC/realms/master/protocol/openid-connect/token" | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
auth=(-H "Authorization: Bearer $TOKEN")
existing=$(curl -sf "${auth[@]}" "$KC/admin/realms/fcp-dev/users?username=e2e.owner&exact=true" \
  | python3 -c "import sys,json;u=json.load(sys.stdin);print(u[0]['id'] if u else '')")
if [ -n "$existing" ]; then curl -sf -X DELETE "${auth[@]}" "$KC/admin/realms/fcp-dev/users/$existing"; fi
curl -sf "${auth[@]}" -H "Content-Type: application/json" "$KC/admin/realms/fcp-dev/users" -d '{
  "username":"e2e.owner","email":"e2e.owner@example.test","emailVerified":true,"enabled":true,
  "firstName":"E2E","lastName":"Owner",
  "credentials":[{"type":"password","value":"Local-dev-only-pass-1","temporary":false}]}'
NODE_PATH="${NODE_PATH:-$(npm root -g)}" node scripts/e2e/keycloak-mfa-login.js
