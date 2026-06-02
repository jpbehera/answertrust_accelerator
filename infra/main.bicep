// =============================================================================
// AnswerTrust — main.bicep (control-plane orchestration)
//
// Provisions ONLY the AnswerTrust governance/observability control plane:
//   - app-insights.bicep      Log Analytics + Application Insights (M3 trace store)
//   - sentinel.bicep          Microsoft Sentinel + 5 M7 analytic rules
//   - rbac.bicep              least-privilege role assignments
//   - foundry-connection.bicep wires existing Foundry diagnostics into the store
//
// Fabric, Foundry, and Purview are assumed to ALREADY EXIST; their identifiers
// are passed in as parameters for wiring + RBAC only.
//
// Scope: resourceGroup (azd: set resourceGroupName in the environment).
// =============================================================================

targetScope = 'resourceGroup'

@description('Azure region for AnswerTrust control-plane resources.')
param location string = resourceGroup().location

@description('Resource name prefix for all control-plane resources.')
param namePrefix string = 'answertrust'

@description('Tags applied to all resources.')
param tags object = {
  solution: 'AnswerTrust'
  layer: 'control-plane'
}

// --- Existing platform identifiers (wiring only, not provisioned) --------------
@description('Fabric workspace ID that AnswerTrust observes.')
param fabricWorkspaceId string = ''

@description('Foundry project ID hosting the eval / red-team agents.')
param foundryProjectId string = ''

@description('Existing Foundry / Azure AI Services account name (for diagnostics wiring).')
param foundryAccountName string = ''

@description('Purview account name used for label lookups.')
param purviewAccountName string = ''

// --- Principal object IDs for RBAC (empty to skip) -----------------------------
@description('Fabric workspace managed identity object ID.')
param fabricPrincipalId string = ''

@description('Foundry project managed identity object ID.')
param foundryPrincipalId string = ''

@description('Admin user/group object ID for read + respond access.')
param adminPrincipalId string = ''

@description('Principal type of the admin identity.')
@allowed([ 'User', 'Group', 'ServicePrincipal' ])
param adminPrincipalType string = 'User'

@description('Deploy the 5 M7 Sentinel scheduled analytic rules ("true"/"false"). Keep "false" on the FIRST deploy: the rules validate their KQL against the AppEvents/AppDependencies tables, which do not exist until the data plane (notebooks 00->04) ingests its first telemetry. Set to "true" on a SECOND deploy after ingestion has started.')
param deployAnalyticRules string = 'false'

var deployAnalyticRulesBool = toLower(deployAnalyticRules) == 'true'

// --- Trace store: Log Analytics + Application Insights (M3) ---------------------
module appInsights 'app-insights.bicep' = {
  name: 'answertrust-appinsights'
  params: {
    location: location
    namePrefix: namePrefix
    tags: tags
  }
}

// --- Sentinel + M7 analytic rules ----------------------------------------------
module sentinel 'sentinel.bicep' = {
  name: 'answertrust-sentinel'
  params: {
    logAnalyticsWorkspaceName: appInsights.outputs.logAnalyticsWorkspaceName
    deployAnalyticRules: deployAnalyticRulesBool
  }
}

// --- RBAC wiring ---------------------------------------------------------------
module rbac 'rbac.bicep' = {
  name: 'answertrust-rbac'
  params: {
    appInsightsName: appInsights.outputs.appInsightsName
    logAnalyticsWorkspaceName: appInsights.outputs.logAnalyticsWorkspaceName
    fabricPrincipalId: fabricPrincipalId
    foundryPrincipalId: foundryPrincipalId
    adminPrincipalId: adminPrincipalId
    adminPrincipalType: adminPrincipalType
  }
}

// --- Foundry diagnostics → trace store -----------------------------------------
module foundryConnection 'foundry-connection.bicep' = {
  name: 'answertrust-foundry-connection'
  params: {
    foundryAccountName: foundryAccountName
    logAnalyticsWorkspaceId: appInsights.outputs.logAnalyticsWorkspaceId
    appInsightsConnectionString: appInsights.outputs.appInsightsConnectionString
  }
}

// --- Outputs -------------------------------------------------------------------
@description('Log Analytics workspace resource ID (unified trace store).')
output AT_LOG_ANALYTICS_WORKSPACE_ID string = appInsights.outputs.logAnalyticsWorkspaceId

@description('Application Insights connection string for OTel exporters.')
output AT_APPINSIGHTS_CONNECTION_STRING string = appInsights.outputs.appInsightsConnectionString

@description('Echo of the observed Fabric workspace ID.')
output AT_FABRIC_WORKSPACE_ID string = fabricWorkspaceId

@description('Echo of the Foundry project ID.')
output AT_FOUNDRY_PROJECT_ID string = foundryProjectId

@description('Echo of the Purview account name.')
output AT_PURVIEW_ACCOUNT_NAME string = purviewAccountName

@description('Names of the deployed M7 Sentinel analytic rules.')
output AT_SENTINEL_RULES array = sentinel.outputs.deployedRuleNames
