#!/usr/bin/env bash
# deploy-fabric-pipeline.sh — azd postprovision hook (posix).
#
# After the Bicep control plane is provisioned, this uploads the AnswerTrust module
# notebooks to the target Fabric workspace, imports the deploy pipeline, and triggers
# a run. Idempotent: existing items are updated via updateDefinition.
#
# Requires: az CLI (logged in), jq. Reads FABRIC_WORKSPACE_ID from the azd environment.
set -euo pipefail

FABRIC_API="https://api.fabric.microsoft.com/v1"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# ── Resolve workspace id (azd env -> environment variable) ────────────────────
WORKSPACE_ID="${FABRIC_WORKSPACE_ID:-}"
if [[ -z "$WORKSPACE_ID" ]] && command -v azd >/dev/null 2>&1; then
  WORKSPACE_ID="$(azd env get-values 2>/dev/null | grep '^FABRIC_WORKSPACE_ID=' | cut -d'=' -f2 | tr -d '"' || true)"
fi
if [[ -z "$WORKSPACE_ID" ]]; then
  echo "ERROR: FABRIC_WORKSPACE_ID is not set (azd env or environment)." >&2
  exit 1
fi
echo "Target Fabric workspace: $WORKSPACE_ID"

token() { az account get-access-token --resource "https://api.fabric.microsoft.com" --query accessToken -o tsv; }
TOKEN="$(token)"

b64() { base64 < "$1" | tr -d '\n'; }

# ── Upload module notebooks as Fabric Notebook items ─────────────────────────
upsert_notebook() {
  local path="$1"
  local name; name="$(basename "$path" .ipynb)"
  local payload; payload="$(b64 "$path")"
  local body
  body="$(jq -n --arg name "$name" --arg payload "$payload" \
    '{displayName:$name, type:"Notebook",
      definition:{format:"ipynb",
        parts:[{path:"notebook-content.ipynb", payload:$payload, payloadType:"InlineBase64"}]}}')"

  local existing
  existing="$(curl -s -H "Authorization: Bearer $TOKEN" \
    "$FABRIC_API/workspaces/$WORKSPACE_ID/items?type=Notebook" \
    | jq -r --arg n "$name" '.value[]? | select(.displayName==$n) | .id' | head -n1)"

  if [[ -n "$existing" ]]; then
    echo "  update notebook '$name' ($existing)"
    curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
      -d "$(jq -n --arg payload "$payload" \
        '{definition:{format:"ipynb", parts:[{path:"notebook-content.ipynb", payload:$payload, payloadType:"InlineBase64"}]}}')" \
      "$FABRIC_API/workspaces/$WORKSPACE_ID/items/$existing/updateDefinition" >/dev/null
  else
    echo "  create notebook '$name'"
    curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
      -d "$body" "$FABRIC_API/workspaces/$WORKSPACE_ID/items" >/dev/null
  fi
}

echo "Uploading module notebooks..."
for nb in "$ROOT_DIR"/modules/*.ipynb; do
  upsert_notebook "$nb"
done

# ── Import the data pipeline ─────────────────────────────────────────────────
PIPELINE_JSON="$ROOT_DIR/pipelines/AnswerTrust_Deploy_Pipeline.json"
if [[ -f "$PIPELINE_JSON" ]]; then
  echo "Importing AnswerTrust_Deploy_Pipeline..."
  PL_PAYLOAD="$(b64 "$PIPELINE_JSON")"
  curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d "$(jq -n --arg payload "$PL_PAYLOAD" \
      '{displayName:"AnswerTrust_Deploy_Pipeline", type:"DataPipeline",
        definition:{parts:[{path:"pipeline-content.json", payload:$payload, payloadType:"InlineBase64"}]}}')" \
    "$FABRIC_API/workspaces/$WORKSPACE_ID/items" >/dev/null || true
fi

# ── Trigger a pipeline run ───────────────────────────────────────────────────
PIPELINE_ID="$(curl -s -H "Authorization: Bearer $TOKEN" \
  "$FABRIC_API/workspaces/$WORKSPACE_ID/items?type=DataPipeline" \
  | jq -r '.value[]? | select(.displayName=="AnswerTrust_Deploy_Pipeline") | .id' | head -n1)"

if [[ -n "$PIPELINE_ID" ]]; then
  echo "Triggering pipeline run ($PIPELINE_ID)..."
  curl -s -X POST -H "Authorization: Bearer $TOKEN" \
    "$FABRIC_API/workspaces/$WORKSPACE_ID/items/$PIPELINE_ID/jobs/instances?jobType=Pipeline" >/dev/null
  echo "AnswerTrust data plane deployment triggered."
else
  echo "WARNING: pipeline not found; notebooks uploaded but run not triggered." >&2
fi
