// Document Intelligence and Azure OpenAI, with key access switched off.
// The developer signs in with az login and gets the two roles below.

param location string
param developerObjectId string

@description('Thousands of tokens per minute for each model deployment.')
param deploymentCapacity int = 50

var suffix = uniqueString(resourceGroup().id)

// Built-in role ids
var cognitiveServicesUser = 'a97b65f3-24c7-4388-baec-2e87135dc908'
var cognitiveServicesOpenAiUser = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'

resource documentIntelligence 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: 'di-intakeflow-${suffix}'
  location: location
  kind: 'FormRecognizer'
  // S0: the free tier reads only the first two pages of a file.
  sku: {
    name: 'S0'
  }
  properties: {
    customSubDomainName: 'di-intakeflow-${suffix}'
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
  }
}

resource openAi 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: 'oai-intakeflow-${suffix}'
  location: location
  kind: 'OpenAI'
  sku: {
    name: 'S0'
  }
  properties: {
    customSubDomainName: 'oai-intakeflow-${suffix}'
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
  }
}

// DataZoneStandard keeps processing inside the EU data zone.
resource classifyModel 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: openAi
  name: 'gpt-4.1-mini'
  sku: {
    name: 'DataZoneStandard'
    capacity: deploymentCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-4.1-mini'
      version: '2025-04-14'
    }
  }
}

resource extractModel 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: openAi
  name: 'gpt-4.1'
  // Deployments on one account are created one at a time.
  dependsOn: [classifyModel]
  sku: {
    name: 'DataZoneStandard'
    capacity: deploymentCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-4.1'
      version: '2025-04-14'
    }
  }
}

resource readerRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: documentIntelligence
  name: guid(documentIntelligence.id, developerObjectId, cognitiveServicesUser)
  properties: {
    principalId: developerObjectId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUser)
  }
}

resource modelRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: openAi
  name: guid(openAi.id, developerObjectId, cognitiveServicesOpenAiUser)
  properties: {
    principalId: developerObjectId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAiUser)
  }
}

output documentIntelligenceEndpoint string = documentIntelligence.properties.endpoint
output openAiEndpoint string = openAi.properties.endpoint
