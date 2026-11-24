#!/usr/bin/env bash
# V1-4 (#210): the end-to-end walk-through in a real browser (make e2e-walkthrough). Local only.
# Needs: make services, make run-backend (:8000), make run-frontend (:5173), Node with Playwright.
# Resets the throwaway Keycloak user "e2e.owner", signs in with MFA, loads the demo year shared
# with that user, then walks every module and checks the figures shown agree.
set -euo pipefail
cd "$(dirname "$0")/../.."
set -a; . ./.env; set +a
WORK="${WALK_DIR:-$(mktemp -d)}"
export SCREENSHOT_DIR="${SCREENSHOT_DIR:-$WORK}"
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
export NODE_PATH="${NODE_PATH:-$(npm root -g)}"
node scripts/e2e/walkthrough.js signin "$WORK/state.json"
(cd backend && uv run python -m fcp.devtools.demo --share-with e2e.owner@example.test \
  --json "$WORK/demo.json")
node scripts/e2e/walkthrough.js walk "$WORK/state.json" "$WORK/demo.json"
echo "Screenshots: $SCREENSHOT_DIR"
