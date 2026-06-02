# deploy-fabric-pipeline.ps1 — azd postprovision hook (windows).
#
# Windows equivalent of deploy-fabric-pipeline.sh: uploads AnswerTrust module notebooks
# to the target Fabric workspace, imports the deploy pipeline, and triggers a run.
# Requires: az CLI (logged in). Reads FABRIC_WORKSPACE_ID from the azd environment.
$ErrorActionPreference = "Stop"

$FabricApi = "https://api.fabric.microsoft.com/v1"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir   = Split-Path -Parent $ScriptDir

# ── Resolve workspace id (env -> azd env) ────────────────────────────────────
$WorkspaceId = $env:FABRIC_WORKSPACE_ID
if (-not $WorkspaceId -and (Get-Command azd -ErrorAction SilentlyContinue)) {
  $line = (azd env get-values 2>$null | Select-String '^FABRIC_WORKSPACE_ID=')
  if ($line) { $WorkspaceId = ($line -split '=',2)[1].Trim('"') }
}
if (-not $WorkspaceId) { throw "FABRIC_WORKSPACE_ID is not set (azd env or environment)." }
Write-Host "Target Fabric workspace: $WorkspaceId"

$Token = az account get-access-token --resource "https://api.fabric.microsoft.com" --query accessToken -o tsv
$Headers = @{ Authorization = "Bearer $Token"; "Content-Type" = "application/json" }

function ConvertTo-B64([string]$Path) {
  [Convert]::ToBase64String([IO.File]::ReadAllBytes($Path))
}

function Upsert-Notebook([string]$Path) {
  $name = [IO.Path]::GetFileNameWithoutExtension($Path)
  $payload = ConvertTo-B64 $Path
  $items = Invoke-RestMethod -Method Get -Headers $Headers `
    -Uri "$FabricApi/workspaces/$WorkspaceId/items?type=Notebook"
  $existing = ($items.value | Where-Object { $_.displayName -eq $name } | Select-Object -First 1).id

  if ($existing) {
    Write-Host "  update notebook '$name' ($existing)"
    $body = @{ definition = @{ format = "ipynb"; parts = @(@{ path = "notebook-content.ipynb"; payload = $payload; payloadType = "InlineBase64" }) } } | ConvertTo-Json -Depth 8
    Invoke-RestMethod -Method Post -Headers $Headers -Body $body `
      -Uri "$FabricApi/workspaces/$WorkspaceId/items/$existing/updateDefinition" | Out-Null
  } else {
    Write-Host "  create notebook '$name'"
    $body = @{ displayName = $name; type = "Notebook"; definition = @{ format = "ipynb"; parts = @(@{ path = "notebook-content.ipynb"; payload = $payload; payloadType = "InlineBase64" }) } } | ConvertTo-Json -Depth 8
    Invoke-RestMethod -Method Post -Headers $Headers -Body $body `
      -Uri "$FabricApi/workspaces/$WorkspaceId/items" | Out-Null
  }
}

Write-Host "Uploading module notebooks..."
Get-ChildItem -Path (Join-Path $RootDir "modules") -Filter *.ipynb | ForEach-Object { Upsert-Notebook $_.FullName }

# ── Import the data pipeline ─────────────────────────────────────────────────
$PipelineJson = Join-Path $RootDir "pipelines/AnswerTrust_Deploy_Pipeline.json"
if (Test-Path $PipelineJson) {
  Write-Host "Importing AnswerTrust_Deploy_Pipeline..."
  $plPayload = ConvertTo-B64 $PipelineJson
  $body = @{ displayName = "AnswerTrust_Deploy_Pipeline"; type = "DataPipeline"; definition = @{ parts = @(@{ path = "pipeline-content.json"; payload = $plPayload; payloadType = "InlineBase64" }) } } | ConvertTo-Json -Depth 8
  try {
    Invoke-RestMethod -Method Post -Headers $Headers -Body $body `
      -Uri "$FabricApi/workspaces/$WorkspaceId/items" | Out-Null
  } catch { Write-Warning "Pipeline import skipped: $_" }
}

# ── Trigger a pipeline run ───────────────────────────────────────────────────
$pipelines = Invoke-RestMethod -Method Get -Headers $Headers `
  -Uri "$FabricApi/workspaces/$WorkspaceId/items?type=DataPipeline"
$PipelineId = ($pipelines.value | Where-Object { $_.displayName -eq "AnswerTrust_Deploy_Pipeline" } | Select-Object -First 1).id

if ($PipelineId) {
  Write-Host "Triggering pipeline run ($PipelineId)..."
  Invoke-RestMethod -Method Post -Headers $Headers `
    -Uri "$FabricApi/workspaces/$WorkspaceId/items/$PipelineId/jobs/instances?jobType=Pipeline" | Out-Null
  Write-Host "AnswerTrust data plane deployment triggered."
} else {
  Write-Warning "Pipeline not found; notebooks uploaded but run not triggered."
}
