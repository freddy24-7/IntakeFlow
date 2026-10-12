// IntakeFlow environment for stages 2 to 5: reading, extraction and contract search.
// Everything is pay-per-use. Nothing here costs money while idle.
//
//   ./deploy/up.sh          the AI resources (no idle cost)
//   ./deploy/up-app.sh      also the application (costs money while it exists)
//   ./deploy/down-app.sh    remove the application, keep the AI resources
//   ./deploy/down.sh        delete everything

targetScope = 'subscription'

@description('Region for all resources. Must be in the EU.')
param location string = 'swedencentral'

@description('Region for Azure AI Search. Must be in the EU. On 2026-10-12 Sweden Central had no capacity for new search services and West Europe did not accept new customers.')
param searchLocation string = 'northeurope'

@description('Object id of the person who runs the pipeline from a laptop (az login).')
param developerObjectId string

@description('Where budget alerts are sent. Passed at deploy time, never stored in the repository.')
param budgetContactEmail string

@description('Monthly budget in the billing currency of the subscription.')
param monthlyBudget int = 35

@description('Region for the application. On 2026-10-12 Sweden Central had no capacity for the database, so the application runs next to the search service.')
param appLocation string = 'northeurope'

@description('Also create the application: Container Apps, Postgres, storage, registry, monitoring. These cost money while idle.')
param deployApp bool = false

@description('Image tag for the two container apps. Empty creates the application resources without the apps.')
param imageTag string = ''

@secure()
param postgresPassword string = ''

@description('Client id of the Entra app registration for sign-in to the web application.')
param authClientId string = ''

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
    searchLocation: searchLocation
  }
}

module app 'app.bicep' = if (deployApp) {
  name: 'app'
  scope: group
  params: {
    location: appLocation
    developerObjectId: developerObjectId
    imageTag: imageTag
    postgresPassword: postgresPassword
    authClientId: authClientId
    documentIntelligenceName: ai.outputs.documentIntelligenceName
    openAiName: ai.outputs.openAiName
    searchName: ai.outputs.searchName
    documentIntelligenceEndpoint: ai.outputs.documentIntelligenceEndpoint
    openAiEndpoint: ai.outputs.openAiEndpoint
    searchEndpoint: ai.outputs.searchEndpoint
  }
}

output resourceGroup string = group.name
output documentIntelligenceEndpoint string = ai.outputs.documentIntelligenceEndpoint
output openAiEndpoint string = ai.outputs.openAiEndpoint
output searchEndpoint string = ai.outputs.searchEndpoint
output registryName string = app.?outputs.registryName ?? ''
output webUrl string = app.?outputs.webUrl ?? ''
