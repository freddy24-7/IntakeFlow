#!/usr/bin/env bash
# Delete the whole IntakeFlow environment, then purge the soft-deleted AI accounts
# so their names and quota are free again.
set -euo pipefail

GROUP="rg-intakeflow-dev"
LOCATION="swedencentral"

if [[ "$(az group exists --name "$GROUP")" != "true" ]]; then
  echo "$GROUP does not exist. Nothing to delete."
  exit 0
fi

ACCOUNTS="$(az cognitiveservices account list --resource-group "$GROUP" --query "[].name" -o tsv)"
az group delete --name "$GROUP" --yes
for ACCOUNT in $ACCOUNTS; do
  az cognitiveservices account purge --name "$ACCOUNT" --resource-group "$GROUP" --location "$LOCATION"
done
echo "Deleted $GROUP."
