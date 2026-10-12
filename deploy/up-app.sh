#!/usr/bin/env bash
# Deploy the application to Azure: registry, database, storage, monitoring, then
# the web and worker container apps. Pass --what-if to preview without changing anything.
#
# Three steps, because each needs the one before it:
#   1. resources without the container apps (the registry must exist to hold an image)
#   2. build the image in the registry
#   3. the container apps, with sign-in limited to the person who deploys
#
# The database password is generated here on every deploy and goes straight into
# Key Vault. It is never printed or written to disk.
set -euo pipefail
cd "$(dirname "$0")"

GROUP="rg-intakeflow-dev"
AUTH_APP_NAME="intakeflow-web-signin"
MODE="${1:-}"

DEVELOPER_ID="$(az ad signed-in-user show --query id -o tsv)"
CONTACT_EMAIL="${BUDGET_CONTACT_EMAIL:-$(az account show --query user.name -o tsv)}"
BUDGET_START="$(date +%Y-%m-01)"
# The second form is for machines where the first git on the PATH cannot run.
TAG="$(git rev-parse --short HEAD 2>/dev/null || /usr/bin/git rev-parse --short HEAD)"
# 48 hex characters from the system's random source. Hex only, so it is safe in a URL.
PASSWORD="$(od -An -tx1 -N24 /dev/urandom | tr -d ' \n')"

deploy() {  # deploy <create|what-if> <image tag> <auth client id>
  az deployment sub "$1" \
    --name intakeflow-dev \
    --location swedencentral \
    --template-file main.bicep \
    --parameters developerObjectId="$DEVELOPER_ID" \
                 budgetContactEmail="$CONTACT_EMAIL" \
                 budgetStartDate="$BUDGET_START" \
                 deployApp=true \
                 imageTag="$2" \
                 authClientId="$3" \
                 postgresPassword="$PASSWORD" \
    --output none
}

if [[ "$MODE" == "--what-if" ]]; then
  az deployment sub what-if \
    --name intakeflow-dev --location swedencentral --template-file main.bicep \
    --parameters developerObjectId="$DEVELOPER_ID" budgetContactEmail="$CONTACT_EMAIL" \
                 budgetStartDate="$BUDGET_START" deployApp=true imageTag="$TAG" \
                 authClientId="00000000-0000-0000-0000-000000000000" postgresPassword="$PASSWORD"
  exit 0
fi

for NAMESPACE in Microsoft.App Microsoft.ContainerRegistry Microsoft.DBforPostgreSQL \
                 Microsoft.Storage Microsoft.KeyVault Microsoft.OperationalInsights \
                 Microsoft.Insights Microsoft.ManagedIdentity; do
  az provider register --namespace "$NAMESPACE" --wait
done

echo "1/3 Resources (this takes several minutes, mostly the database)..."
deploy create "" ""
REGISTRY="$(az deployment sub show --name intakeflow-dev --query properties.outputs.registryName.value -o tsv)"
WEB_URL="$(az deployment sub show --name intakeflow-dev --query properties.outputs.webUrl.value -o tsv)"

echo "2/3 Building image $TAG in the registry..."
az acr build --registry "$REGISTRY" --image "intakeflow:$TAG" --file ../Dockerfile .. --output none

echo "3/3 Sign-in registration and container apps..."
AUTH_CLIENT_ID="$(az ad app list --display-name "$AUTH_APP_NAME" --query "[0].appId" -o tsv)"
if [[ -z "$AUTH_CLIENT_ID" ]]; then
  AUTH_CLIENT_ID="$(az ad app create --display-name "$AUTH_APP_NAME" \
    --sign-in-audience AzureADMyOrg --enable-id-token-issuance true \
    --web-redirect-uris "$WEB_URL/.auth/login/aad/callback" --query appId -o tsv)"
else
  az ad app update --id "$AUTH_CLIENT_ID" --enable-id-token-issuance true \
    --web-redirect-uris "$WEB_URL/.auth/login/aad/callback"
fi
deploy create "$TAG" "$AUTH_CLIENT_ID"

echo
echo "Deployed image $TAG."
echo "Web application: $WEB_URL"
echo "Sign in with the Microsoft account you deployed with. Remove everything again with ./deploy/down-app.sh"
