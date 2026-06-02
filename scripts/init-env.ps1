# init-env.ps1 — guided setup for the AnswerTrust azd environment (windows).
#
# Interactively collects the tenant-specific values AnswerTrust needs and writes
# them into the current azd environment via `azd env set`. Recommended one-step
# path before `azd up`:
#
#   azd auth login
#   azd init            # (or: azd env new <name>)
#   ./scripts/init-env.ps1
#   azd up
#
# azd does NOT prompt for these custom parameters on its own, so this script fills
# that gap. Values are stored in .azure/<env>/.env (gitignored by azd) and are read
# by both Bicep (infra/main.parameters.json ${VAR} bindings) and the postprovision
# Fabric deploy hook. Re-run any time to update values; existing answers are shown
# as defaults. Power users can instead edit .env (see .env.example) + `azd env set`.
$ErrorActionPreference = "Stop"

if (-not (Get-Command azd -ErrorAction SilentlyContinue)) {
  throw "Azure Developer CLI (azd) is not installed. See https://aka.ms/azd-install"
}

# Ensure an azd environment exists/selected.
$values = (azd env get-values 2>$null)
if (-not $values) {
  $envName = Read-Host "No azd environment selected. Enter a name to create one (e.g. answertrust-dev)"
  if (-not $envName) { $envName = "answertrust-dev" }
  azd env new $envName
}

function Get-Current([string]$Key) {
  $line = (azd env get-values 2>$null | Select-String "^$Key=")
  if ($line) { return ($line -split '=', 2)[1].Trim('"') }
  return ""
}

function Set-Prompt([string]$Key, [string]$Desc, [bool]$Required = $false) {
  $cur = Get-Current $Key
  do {
    if ($cur) { $ans = Read-Host "$Desc [$cur]"; if (-not $ans) { $ans = $cur } }
    else      { $ans = Read-Host "$Desc" }
    if (-not $ans -and $Required) { Write-Host "  -> $Key is required." -ForegroundColor Yellow }
  } while (-not $ans -and $Required)
  azd env set $Key $ans | Out-Null
}

Write-Host "=== AnswerTrust environment setup ===" -ForegroundColor Cyan
Write-Host "Press Enter to keep the value shown in [brackets]."
Write-Host ""

Write-Host "-- Azure context --"
Set-Prompt "AZURE_LOCATION"         "Azure region for control-plane resources (e.g. westus3)" $true
Set-Prompt "AT_NAME_PREFIX"         "Resource name prefix for control-plane resources"

Write-Host ""
Write-Host "-- Existing Fabric workspace (AnswerTrust is an add-on) --"
Set-Prompt "FABRIC_WORKSPACE_ID"    "Target Fabric workspace GUID" $true

Write-Host ""
Write-Host "-- Existing Azure AI Foundry project --"
Set-Prompt "FOUNDRY_PROJECT_ID"     "Foundry project resource id (.../projects/<name>)" $true
Set-Prompt "FOUNDRY_ACCOUNT_NAME"   "Foundry / AI Services account name"

Write-Host ""
Write-Host "-- Microsoft Purview (leave blank for the unified tenant portal) --"
Set-Prompt "PURVIEW_ACCOUNT_NAME"   "Purview account name (blank if using the unified portal)"

Write-Host ""
Write-Host "-- RBAC --"
Set-Prompt "AT_ADMIN_PRINCIPAL_ID"   "Admin user/group object ID (receives AnswerTrust roles)" $true
Set-Prompt "AT_ADMIN_PRINCIPAL_TYPE" "Admin principal type (User | Group | ServicePrincipal)"
Set-Prompt "FABRIC_PRINCIPAL_ID"     "Fabric workspace identity object ID (blank to skip)"
Set-Prompt "FOUNDRY_PRINCIPAL_ID"    "Foundry project identity object ID (blank to skip)"

Write-Host ""
Write-Host "Saved to the current azd environment."
Write-Host "Next: run 'azd up' to provision the control plane and deploy the Fabric data plane."
