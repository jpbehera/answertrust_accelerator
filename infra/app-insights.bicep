// =============================================================================
// AnswerTrust — app-insights.bicep
// Provisions the single unified trace store for M3 (Unified Trace Fabric):
//   - Log Analytics workspace  (long-term, queryable trace + ledger sink)
//   - Application Insights      (workspace-based, OTel ingestion endpoint)
// =============================================================================

@description('Azure region for the workspace and component.')
param location string = resourceGroup().location

@description('Resource name prefix, e.g. "answertrust".')
param namePrefix string

@description('Tags applied to all resources.')
param tags object = {}

@description('Log Analytics daily ingestion cap in GB. -1 disables the cap.')
param dailyQuotaGb int = -1

@description('Data retention in days for the Log Analytics workspace.')
@minValue(30)
@maxValue(730)
param retentionInDays int = 90

var workspaceName = '${namePrefix}-law'
var appInsightsName = '${namePrefix}-appi'

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: workspaceName
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: retentionInDays
    workspaceCapping: {
      dailyQuotaGb: dailyQuotaGb
    }
    features: {
      enableLogAccessUsingOnlyResourcePermissions: true
    }
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalytics.id
    IngestionMode: 'LogAnalytics'
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
  }
}

@description('Resource ID of the Log Analytics workspace (Sentinel + RBAC bind here).')
output logAnalyticsWorkspaceId string = logAnalytics.id

@description('Name of the Log Analytics workspace.')
output logAnalyticsWorkspaceName string = logAnalytics.name

@description('Name of the Application Insights component.')
output appInsightsName string = appInsights.name

@description('Customer ID (GUID) of the Log Analytics workspace.')
output logAnalyticsCustomerId string = logAnalytics.properties.customerId

@description('Application Insights resource ID.')
output appInsightsId string = appInsights.id

@description('Application Insights connection string (OTel exporters target this).')
output appInsightsConnectionString string = appInsights.properties.ConnectionString

@description('Application Insights instrumentation key.')
output appInsightsInstrumentationKey string = appInsights.properties.InstrumentationKey
