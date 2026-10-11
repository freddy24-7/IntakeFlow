// IntakeFlow, stage 2 environment: only what reading and extraction need.
// Everything is pay-per-use. Nothing here costs money while idle.
//
//   ./deploy/up.sh      create or update
//   ./deploy/down.sh    delete everything

targetScope = 'subscription'

@description('Region for all resources. Must be in the EU.')
param location string = 'swedencentral'

@description('Object id of the person who runs the pipeline from a laptop (az login).')
param developerObjectId string

@description('Where budget alerts are sent. Passed at deploy time, never stored in the repository.')
param budgetContactEmail string

@description('Monthly budget in the billing currency of the subscription.')
param monthlyBudget int = 20

@description('First day of the current month, for example 2026-10-01.')
param budgetStartDate string

var resourceGroupName = 'rg-intakeflow-dev'

resource group 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: resourceGroupName
  location: location
  tags: {
    project: 'intakeflow'
    purpose: 'portfolio demo, synthetic data only'
  }
}

module budget 'budget.bicep' = {
  name: 'budget'
  scope: group
  params: {
    amount: monthlyBudget
    contactEmail: budgetContactEmail
    startDate: budgetStartDate
  }
}

module ai 'ai.bicep' = {
  name: 'ai'
  scope: group
  // The budget alert exists before anything that can cost money.
  dependsOn: [budget]
  params: {
    location: location
    developerObjectId: developerObjectId
  }
}

output resourceGroup string = group.name
output documentIntelligenceEndpoint string = ai.outputs.documentIntelligenceEndpoint
output openAiEndpoint string = ai.outputs.openAiEndpoint
