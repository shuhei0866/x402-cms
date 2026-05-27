#!/usr/bin/env bash
# Deploy x402-cms-x-indexer Cloud Run Job from local source.
#
# Cloud Run Job (not Service) — runs `python -m code.indexers.x_indexer`
# once per invocation. Cloud Scheduler triggers a fresh execution
# every Monday morning so the weekly digest reflects last week's
# tweets from the tracked X handles.
#
# Shares the same Dockerfile as the serving image, just with a
# different entrypoint and two secret attachments:
#   - X_BEARER_TOKEN          env var  (x402-cms-x-bearer)
#   - /secrets/tracked_handles.yaml
#                             file     (x402-cms-tracked-handles)
# The handle list ships as a Secret-Manager-mounted file so the
# scheduled run uses the curated private list — the gitignored
# `config/tracked_handles.yaml` — instead of the small OSS example
# template baked into the image. The indexer reads
# `--handles-config <path>` regardless of whether the file came from
# the image or a secret mount.
#
# Prereqs:
#   - gcloud auth login + project set to my-utilities-490202
#   - scripts/setup_sa.sh has been run (x402-cms-runner exists with
#     roles/datastore.user)
#   - scripts/setup_secrets.sh has been run (both secrets exist and
#     x402-cms-runner has secretAccessor on each)
#
# Usage:
#   ./scripts/deploy_x_job.sh
#
# To run the job once manually after deploy:
#   gcloud run jobs execute x402-cms-x-indexer --region asia-northeast1
set -euo pipefail

PROJECT="${GOOGLE_CLOUD_PROJECT:-my-utilities-490202}"
REGION="${REGION:-asia-northeast1}"
JOB="x402-cms-x-indexer"
SA_EMAIL="x402-cms-runner@${PROJECT}.iam.gserviceaccount.com"
BEARER_SECRET="x402-cms-x-bearer"
HANDLES_SECRET="x402-cms-tracked-handles"
HANDLES_PATH="/secrets/tracked_handles.yaml"

cd "$(dirname "$0")/.."

gcloud run jobs deploy "$JOB" \
  --source . \
  --project "$PROJECT" \
  --region "$REGION" \
  --service-account "$SA_EMAIL" \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=${PROJECT}" \
  --update-secrets "X_BEARER_TOKEN=${BEARER_SECRET}:latest,${HANDLES_PATH}=${HANDLES_SECRET}:latest" \
  --command python \
  --args="-m,code.indexers.x_indexer,--handles-config,${HANDLES_PATH}" \
  --max-retries 1 \
  --task-timeout 300s \
  --memory 512Mi \
  --cpu 1
