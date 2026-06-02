// =============================================================================
// AnswerTrust — sentinel.bicep
// Enables Microsoft Sentinel on the M3 Log Analytics workspace and deploys the
// 5 pre-wired M7 analytic rules. KQL bodies live in scripts/sentinel_rules/*.kql
// and are embedded at build time via loadTextContent().
// =============================================================================

@description('Name of the Log Analytics workspace (last segment of its resource ID).')
param logAnalyticsWorkspaceName string

@description('Deploy the 5 scheduled analytic rules. Sentinel validates each rule KQL against existing workspace tables (AppEvents/AppDependencies) at create time; those tables only appear after the data plane ingests its first telemetry. Keep false on the first deploy, flip true after ingestion.')
param deployAnalyticRules bool = false

// --- Existing workspace reference (Sentinel scopes onto it) --------------------
resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: logAnalyticsWorkspaceName
}

// --- Onboard Sentinel ----------------------------------------------------------
resource sentinelOnboarding 'Microsoft.SecurityInsights/onboardingStates@2024-09-01' = {
  scope: workspace
  name: 'default'
  properties: {}
}

// --- Analytic rule definitions -------------------------------------------------
// Each rule: PT1H cadence, P1H lookback, mapped to a MITRE-style tactic.
var rules = [
  {
    id: 'a1f0c001-0001-4001-8001-answerdrift001'
    displayName: 'AnswerTrust — Answer Drift Alarm'
    description: 'Golden-question eval scores have dropped materially below the 14-day baseline.'
    severity: 'Medium'
    tactics: [ 'Impact' ]
    query: loadTextContent('../scripts/sentinel_rules/01_answer_drift_alarm.kql')
  }
  {
    id: 'a1f0c001-0002-4002-8002-toolcallargs002'
    displayName: 'AnswerTrust — Anomalous Tool-Call Arguments'
    description: 'MCP tool invoked with argument shapes deviating sharply from the learned norm.'
    severity: 'High'
    tactics: [ 'Execution' ]
    query: loadTextContent('../scripts/sentinel_rules/02_anomalous_tool_call_args.kql')
  }
  {
    id: 'a1f0c001-0003-4003-8003-labelaccess003'
    displayName: 'AnswerTrust — Anomalous Label Access'
    description: 'User accessed more Confidential rows than their 30-day baseline (label probing).'
    severity: 'High'
    tactics: [ 'Collection' ]
    query: loadTextContent('../scripts/sentinel_rules/03_anomalous_label_access.kql')
  }
  {
    id: 'a1f0c001-0004-4004-8004-oversharing004'
    displayName: 'AnswerTrust — Oversharing Detection'
    description: 'Agent answer returned far more rows than the historical norm for the question category.'
    severity: 'Medium'
    tactics: [ 'Exfiltration' ]
    query: loadTextContent('../scripts/sentinel_rules/04_oversharing_detection.kql')
  }
  {
    id: 'a1f0c001-0005-4005-8005-redteamcorr005'
    displayName: 'AnswerTrust — Red-Team Signal Correlation'
    description: 'AI Red Teaming finding correlated to a live production answer trace.'
    severity: 'High'
    tactics: [ 'InitialAccess' ]
    query: loadTextContent('../scripts/sentinel_rules/05_redteam_signal_correlation.kql')
  }
]

// --- Scheduled analytic rules --------------------------------------------------
resource alertRules 'Microsoft.SecurityInsights/alertRules@2024-09-01' = [
  for rule in (deployAnalyticRules ? rules : []): {
    scope: workspace
    name: rule.id
    kind: 'Scheduled'
    properties: {
      displayName: rule.displayName
      description: rule.description
      severity: rule.severity
      enabled: true
      query: rule.query
      queryFrequency: 'PT1H'
      queryPeriod: 'PT1H'
      triggerOperator: 'GreaterThan'
      triggerThreshold: 0
      suppressionDuration: 'PT1H'
      suppressionEnabled: false
      tactics: rule.tactics
      incidentConfiguration: {
        createIncident: true
        groupingConfiguration: {
          enabled: true
          reopenClosedIncident: false
          lookbackDuration: 'PT5H'
          matchingMethod: 'AllEntities'
        }
      }
    }
    dependsOn: [
      sentinelOnboarding
    ]
  }
]

@description('Display names of the deployed M7 analytic rules (empty until deployAnalyticRules is true).')
output deployedRuleNames array = [for (rule, i) in (deployAnalyticRules ? rules : []): rule.displayName]
