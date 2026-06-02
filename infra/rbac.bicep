// =============================================================================
// AnswerTrust — rbac.bicep
// Least-privilege role assignments wiring the existing Fabric / Foundry
// identities to the AnswerTrust control plane (App Insights + Log Analytics +
// Sentinel). All assignments are conditional on a non-empty principal ID so the
// module is safe to deploy incrementally.
// =============================================================================

@description('Name of the Application Insights component (from app-insights.bicep).')
param appInsightsName string

@description('Name of the Log Analytics workspace (from app-insights.bicep).')
param logAnalyticsWorkspaceName string

@description('Object ID of the Fabric workspace managed identity. Empty to skip.')
param fabricPrincipalId string = ''

@description('Object ID of the Foundry project managed identity. Empty to skip.')
param foundryPrincipalId string = ''

@description('Object ID of the admin user/group for read + respond access. Empty to skip.')
param adminPrincipalId string = ''

@description('Principal type for the admin assignment.')
@allowed([ 'User', 'Group', 'ServicePrincipal' ])
param adminPrincipalType string = 'User'

// --- Built-in role definition IDs ---------------------------------------------
var roleMonitoringMetricsPublisher = '3913510d-42f4-4e42-8a64-420c390055eb'
var roleLogAnalyticsReader         = '73c42c96-874c-492b-b04d-ab87d138a893'
var roleSentinelResponder          = '3e150937-b8fe-4cfb-8069-0eaf05ecd056'

resource appInsights 'Microsoft.Insights/components@2020-02-02' existing = {
  name: appInsightsName
}

resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: logAnalyticsWorkspaceName
}

// --- Fabric MI → Monitoring Metrics Publisher on App Insights ------------------
resource fabricPublisher 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(fabricPrincipalId)) {
  name: guid(appInsights.id, fabricPrincipalId, roleMonitoringMetricsPublisher)
  scope: appInsights
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleMonitoringMetricsPublisher)
    principalId: fabricPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// --- Foundry MI → Monitoring Metrics Publisher on App Insights -----------------
resource foundryPublisher 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(foundryPrincipalId)) {
  name: guid(appInsights.id, foundryPrincipalId, roleMonitoringMetricsPublisher)
  scope: appInsights
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleMonitoringMetricsPublisher)
    principalId: foundryPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// --- Admin → Log Analytics Reader on workspace ---------------------------------
resource adminReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(adminPrincipalId)) {
  name: guid(workspace.id, adminPrincipalId, roleLogAnalyticsReader)
  scope: workspace
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleLogAnalyticsReader)
    principalId: adminPrincipalId
    principalType: adminPrincipalType
  }
}

// --- Admin → Microsoft Sentinel Responder on workspace -------------------------
resource adminResponder 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(adminPrincipalId)) {
  name: guid(workspace.id, adminPrincipalId, roleSentinelResponder)
  scope: workspace
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleSentinelResponder)
    principalId: adminPrincipalId
    principalType: adminPrincipalType
  }
}
