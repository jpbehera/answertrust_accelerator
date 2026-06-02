#!/usr/bin/env bash
# init-env.sh — guided setup for the AnswerTrust azd environment (posix).
#
# Interactively collects the tenant-specific values AnswerTrust needs and writes
# them into the current azd environment via `azd env set`. This is the recommended
# one-step path before `azd up`:
#
#   azd auth login
#   azd init            # (or: azd env new <name>)
#   ./scripts/init-env.sh
#   azd up
#
# azd does NOT prompt for these custom parameters on its own, so this script fills
# that gap. Values are stored in .azure/<env>/.env (gitignored by azd) and are read
# by both Bicep (infra/main.parameters.json ${VAR} bindings) and the postprovision
# Fabric deploy hook. Re-run any time to update values; existing answers are shown
# as defaults. Power users can instead edit .env (see .env.example) + `azd env set`.
set -euo pipefail

if ! command -v azd >/dev/null 2>&1; then
  echo "ERROR: Azure Developer CLI (azd) is not installed. See https://aka.ms/azd-install" >&2
  exit 1
fi

# Ensure an azd environment exists/selected.
if ! azd env list >/dev/null 2>&1 || [[ -z "$(azd env get-values 2>/dev/null || true)" ]]; then
  read -r -p "No azd environment selected. Enter a name to create one (e.g. answertrust-dev): " _env
  azd env new "${_env:-answertrust-dev}"
fi

# current value of an azd env var (empty if unset)
_cur() { azd env get-values 2>/dev/null | grep "^$1=" | head -n1 | cut -d'=' -f2- | tr -d '"' || true; }

# prompt KEY "description" [required]
prompt() {
  local key="$1" desc="$2" required="${3:-}" cur ans
  cur="$(_cur "$key")"
  if [[ -n "$cur" ]]; then
    read -r -p "$desc [$cur]: " ans
    ans="${ans:-$cur}"
  else
    read -r -p "$desc: " ans
  fi
  if [[ -z "$ans" && -n "$required" ]]; then
    echo "  -> $key is required." >&2
    prompt "$key" "$desc" "$required"
    return
  fi
  azd env set "$key" "$ans" >/dev/null
}

echo "=== AnswerTrust environment setup ==="
echo "Press Enter to keep the value shown in [brackets]."
echo

echo "-- Azure context --"
prompt AZURE_LOCATION        "Azure region for control-plane resources (e.g. westus3)" required
prompt AT_NAME_PREFIX        "Resource name prefix for control-plane resources"

echo
echo "-- Existing Fabric workspace (AnswerTrust is an add-on) --"
prompt FABRIC_WORKSPACE_ID   "Target Fabric workspace GUID" required

echo
echo "-- Existing Azure AI Foundry project --"
prompt FOUNDRY_PROJECT_ID    "Foundry project resource id (.../projects/<name>)" required
prompt FOUNDRY_ACCOUNT_NAME  "Foundry / AI Services account name"

echo
echo "-- Microsoft Purview (leave blank for the unified tenant portal) --"
prompt PURVIEW_ACCOUNT_NAME  "Purview account name (blank if using the unified portal)"

echo
echo "-- RBAC --"
prompt AT_ADMIN_PRINCIPAL_ID   "Admin user/group object ID (receives AnswerTrust roles)" required
prompt AT_ADMIN_PRINCIPAL_TYPE "Admin principal type (User | Group | ServicePrincipal)"
prompt FABRIC_PRINCIPAL_ID     "Fabric workspace identity object ID (blank to skip)"
prompt FOUNDRY_PRINCIPAL_ID    "Foundry project identity object ID (blank to skip)"

echo
echo "Saved to azd environment '$(azd env get-value AZURE_ENV_NAME 2>/dev/null || echo current)'."
echo "Next: run 'azd up' to provision the control plane and deploy the Fabric data plane."
