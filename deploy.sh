#!/usr/bin/env bash
# Build the container and deploy it to Cloud Run.
# Secrets come from the local .env and are passed through as shell variables;
# no literal key ever appears in this file or the repository.
set -euo pipefail

if [[ ! -f .env ]]; then
  echo "error: .env not found. Copy .env.example to .env and fill in your keys." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

: "${GCP_PROJECT_ID:?set GCP_PROJECT_ID in .env}"
: "${OPENAI_API_KEY:?set OPENAI_API_KEY in .env}"
: "${TAVILY_API_KEY:?set TAVILY_API_KEY in .env}"

REGION="${GCP_REGION:-us-west1}"
SERVICE="csci599-a1"
IMAGE="gcr.io/${GCP_PROJECT_ID}/${SERVICE}"

echo "==> Building ${IMAGE}"
gcloud builds submit --tag "${IMAGE}" --project "${GCP_PROJECT_ID}"

echo "==> Deploying ${SERVICE} to ${REGION}"
gcloud run deploy "${SERVICE}" \
  --image "${IMAGE}" \
  --project "${GCP_PROJECT_ID}" \
  --platform managed \
  --region "${REGION}" \
  --allow-unauthenticated \
  --memory 512Mi \
  --min-instances 0 \
  --max-instances 1 \
  --set-env-vars "OPENAI_API_KEY=${OPENAI_API_KEY},OPENAI_BASE_URL=${OPENAI_BASE_URL},LLM_MODEL=${LLM_MODEL},TAVILY_API_KEY=${TAVILY_API_KEY},MCP_CONFIG_PATH=/app/mcp_config.json,MCP_FILESYSTEM_ROOT=/app/workspace"

echo "==> Live URL:"
gcloud run services describe "${SERVICE}" \
  --project "${GCP_PROJECT_ID}" --region "${REGION}" --format 'value(status.url)'
