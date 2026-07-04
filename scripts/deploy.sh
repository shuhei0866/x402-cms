#!/usr/bin/env bash
# Deploy x402-cms to Cloud Run from the local source.
#
# Service-side counterpart to scripts/deploy_x_job.sh. Mounts the
# curated handle list from Secret Manager so the renderer can surface
# cluster-grouped sections (e.g. the Japan community spotlight)
# using the same source of truth the indexer Job uses.
#
# Prereqs:
#   - gcloud auth login + project set to my-utilities-490202
#   - scripts/setup_sa.sh has been run once
#   - scripts/setup_secrets.sh has been run (x402-cms-tracked-handles
#     secret exists and x402-cms-runner has secretAccessor on it)
#   - EVM_ADDRESS exported in the calling shell. The address is public
#     (it is the payee), not a secret, but it is per-developer so we
#     do not bake it into the script.
#
# Usage:
#   EVM_ADDRESS=0xYourAddr ./scripts/deploy.sh
#
# `--source .` triggers Cloud Build, which reads Dockerfile +
# .dockerignore from the repo root.
set -euo pipefail

PROJECT="${GOOGLE_CLOUD_PROJECT:-my-utilities-490202}"
REGION="${REGION:-asia-northeast1}"
SERVICE="x402-cms"
SA_EMAIL="x402-cms-runner@${PROJECT}.iam.gserviceaccount.com"
HANDLES_SECRET="x402-cms-tracked-handles"
HANDLES_PATH="/secrets/tracked_handles.yaml"
TOPICS_SECRET="x402-cms-topics"
TOPICS_PATH="/secrets/topics.yaml"

if [ -z "${EVM_ADDRESS:-}" ]; then
  echo "ERROR: EVM_ADDRESS must be exported before running deploy." >&2
  echo "Hint: set -a; source .env; set +a; ./scripts/deploy.sh" >&2
  exit 1
fi

FACILITATOR_URL="${FACILITATOR_URL:-https://x402.org/facilitator}"

cd "$(dirname "$0")/.."

gcloud run deploy "$SERVICE" \
  --source . \
  --project "$PROJECT" \
  --region "$REGION" \
  --service-account "$SA_EMAIL" \
  --allow-unauthenticated \
  --min-instances 1 \
  --memory 512Mi \
  --cpu 1 \
  --timeout 60s \
  --set-env-vars "EVM_ADDRESS=${EVM_ADDRESS},FACILITATOR_URL=${FACILITATOR_URL},GOOGLE_CLOUD_PROJECT=${PROJECT}" \
  --update-secrets "${HANDLES_PATH}=${HANDLES_SECRET}:latest,${TOPICS_PATH}=${TOPICS_SECRET}:latest"
