// =============================================================================
// AnswerTrust — foundry-connection.bicep
// Wires the EXISTING Microsoft Foundry account into the AnswerTrust trace store
// so M6 continuous-eval + safety telemetry land in the same Log Analytics
// workspace as the M3 trace fabric. Foundry itself is not provisioned here.
// =============================================================================

@description('Name of the existing Foundry / Azure AI Services account. Empty to skip wiring.')
param foundryAccountName string = ''

@description('Resource ID of the Log Analytics workspace (from app-insights.bicep).')
param logAnalyticsWorkspaceId string

@description('Application Insights connection string the Foundry project should export to.')
param appInsightsConnectionString string

// --- Existing Foundry account reference ----------------------------------------
resource foundry 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = if (!empty(foundryAccountName)) {
  name: foundryAccountName
}

// --- Route Foundry diagnostics into the unified trace store --------------------
resource foundryDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (!empty(foundryAccountName)) {
  name: 'answertrust-foundry-diag'
  scope: foundry
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    logs: [
      {
        categoryGroup: 'allLogs'
        enabled: true
      }
    ]
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
      }
    ]
  }
}

@description('Connection string M6 eval / red-team agents export OTel spans to. Surface in the Foundry project as APPLICATIONINSIGHTS_CONNECTION_STRING.')
output foundryTelemetryConnectionString string = appInsightsConnectionString

@description('Whether Foundry diagnostics were wired into Log Analytics.')
output foundryWired bool = !empty(foundryAccountName)
