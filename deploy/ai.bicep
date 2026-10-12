// Document Intelligence, Azure OpenAI and Azure AI Search, with key access switched off.
// The developer signs in with az login and gets the two roles below.

param location string
param developerObjectId string

@description('Region for Azure AI Search. Separate, because a region can be out of capacity for it.')
param searchLocation string

@description('Thousands of tokens per minute for each model deployment.')
param deploymentCapacity int = 50

var suffix = uniqueString(resourceGroup().id)

// Built-in role ids
var cognitiveServicesUser = 'a97b65f3-24c7-4388-baec-2e87135dc908'
var cognitiveServicesOpenAiUser = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
// Read and write documents in an index, and create indexes.
var searchIndexDataContributor = '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
var searchServiceContributor = '7ca78c08-252a-4471-8644-bb5ff32d4ba0'

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

// Regional Standard: processing stays in Sweden Central. The subscription has no
// quota for the EU data zone type (DataZoneStandard) for these models.
resource classifyModel 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: openAi
  name: 'gpt-4.1-mini'
  sku: {
    name: 'Standard'
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
    name: 'Standard'
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

// Embeddings for the contract archive (stage 5). Regional, like the chat models.
resource embeddingModel 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: openAi
  name: 'text-embedding-3-large'
  dependsOn: [extractModel]
  sku: {
    name: 'Standard'
    capacity: deploymentCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'text-embedding-3-large'
      version: '1'
    }
  }
}

// Azure AI Search, free tier: one per subscription, 50 MB, no cost.
resource search 'Microsoft.Search/searchServices@2023-11-01' = {
  name: 'srch-intakeflow-${suffix}'
  location: searchLocation
  sku: {
    name: 'free'
  }
  properties: {
    replicaCount: 1
    partitionCount: 1
    hostingMode: 'default'
    // Sign-in through az login only, no keys.
    disableLocalAuth: true
    // The free monthly allowance of the semantic ranker.
    semanticSearch: 'free'
  }
}

resource searchDataRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: search
  name: guid(search.id, developerObjectId, searchIndexDataContributor)
  properties: {
    principalId: developerObjectId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchIndexDataContributor)
  }
}

resource searchServiceRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: search
  name: guid(search.id, developerObjectId, searchServiceContributor)
  properties: {
    principalId: developerObjectId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchServiceContributor)
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
output searchEndpoint string = 'https://${search.name}.search.windows.net'
output documentIntelligenceName string = documentIntelligence.name
output openAiName string = openAi.name
output searchName string = search.name
