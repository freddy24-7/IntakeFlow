#!/usr/bin/env bash
# Remove the application (everything tagged part=app) and keep the AI resources,
# which cost nothing while idle. Stops the daily cost of the database and registry.
set -euo pipefail

GROUP="rg-intakeflow-dev"
ids() { az resource list -g "$GROUP" --tag part=app --query "[?type=='$1'].id" -o tsv; }
remove() {
  local found
  found="$(ids "$1")"
  if [[ -n "$found" ]]; then
    echo "Deleting $1"
    # shellcheck disable=SC2086
    az resource delete --ids $found --output none
  fi
}

# Apps before their environment, the environment before the workspace it logs to.
remove Microsoft.App/containerApps
remove Microsoft.App/managedEnvironments
remove Microsoft.DBforPostgreSQL/flexibleServers
remove Microsoft.ContainerRegistry/registries
remove Microsoft.Storage/storageAccounts
remove Microsoft.Insights/components
remove Microsoft.OperationalInsights/workspaces
remove Microsoft.ManagedIdentity/userAssignedIdentities

VAULTS="$(az resource list -g "$GROUP" --tag part=app --query "[?type=='Microsoft.KeyVault/vaults'].name" -o tsv)"
for VAULT in $VAULTS; do
  echo "Deleting and purging key vault"
  az keyvault delete --name "$VAULT" --output none
  az keyvault purge --name "$VAULT" --output none
done

LEFT="$(az resource list -g "$GROUP" --tag part=app --query "length(@)" -o tsv)"
echo "Application removed. Resources still tagged part=app: $LEFT"
