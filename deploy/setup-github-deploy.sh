#!/usr/bin/env bash
# One-time setup so the GitHub Actions deploy workflow can sign in to Azure
# without a stored secret (OpenID Connect). Prints the three values to add as
# repository variables. They are identifiers, not secrets.
set -euo pipefail

REPOSITORY="${1:?usage: setup-github-deploy.sh <owner/repository>}"
GROUP="rg-intakeflow-dev"
NAME="intakeflow-github-deploy"

SUBSCRIPTION="$(az account show --query id -o tsv)"
TENANT="$(az account show --query tenantId -o tsv)"
CLIENT_ID="$(az ad app list --display-name "$NAME" --query "[0].appId" -o tsv)"
if [[ -z "$CLIENT_ID" ]]; then
  CLIENT_ID="$(az ad app create --display-name "$NAME" --query appId -o tsv)"
  az ad sp create --id "$CLIENT_ID" --output none
fi

# Only workflows on the main branch of this repository may sign in.
if [[ -z "$(az ad app federated-credential list --id "$CLIENT_ID" --query "[?name=='main-branch'].name" -o tsv)" ]]; then
  az ad app federated-credential create --id "$CLIENT_ID" --output none --parameters "{
    \"name\": \"main-branch\",
    \"issuer\": \"https://token.actions.githubusercontent.com\",
    \"subject\": \"repo:$REPOSITORY:ref:refs/heads/main\",
    \"audiences\": [\"api://AzureADTokenExchange\"]
  }"
fi

# Limited to the one resource group: build images and update the container apps.
az role assignment create --assignee "$CLIENT_ID" --role Contributor \
  --scope "/subscriptions/$SUBSCRIPTION/resourceGroups/$GROUP" --output none

echo "Add these as repository variables (Settings > Secrets and variables > Actions > Variables):"
echo "  AZURE_CLIENT_ID=$CLIENT_ID"
echo "  AZURE_TENANT_ID=$TENANT"
echo "  AZURE_SUBSCRIPTION_ID=$SUBSCRIPTION"
