#!/usr/bin/env bash
# Create or update the IntakeFlow environment. Pass --what-if to preview without changing anything.
set -euo pipefail
cd "$(dirname "$0")"

MODE="create"
if [[ "${1:-}" == "--what-if" ]]; then MODE="what-if"; fi

# The signed-in account. Nothing personal is written to the repository.
DEVELOPER_ID="$(az ad signed-in-user show --query id -o tsv)"
CONTACT_EMAIL="${BUDGET_CONTACT_EMAIL:-$(az account show --query user.name -o tsv)}"
BUDGET_START="$(date +%Y-%m-01)"

if [[ "$MODE" == "create" ]]; then
  # Free, and needed once per subscription before the first AI resource.
  az provider register --namespace Microsoft.CognitiveServices --wait
  az provider register --namespace Microsoft.Consumption --wait
  az provider register --namespace Microsoft.Search --wait
fi

az deployment sub "$MODE" \
  --name intakeflow-dev \
  --location swedencentral \
  --template-file main.bicep \
  --parameters developerObjectId="$DEVELOPER_ID" \
               budgetContactEmail="$CONTACT_EMAIL" \
               budgetStartDate="$BUDGET_START"

if [[ "$MODE" == "create" ]]; then
  echo
  echo "Put these in .env:"
  output() {
    az deployment sub show --name intakeflow-dev --query "properties.outputs.$1.value" -o tsv
  }
  echo "AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT=$(output documentIntelligenceEndpoint)"
  echo "AZURE_OPENAI_ENDPOINT=$(output openAiEndpoint)"
  echo "AZURE_SEARCH_ENDPOINT=$(output searchEndpoint)"
fi
