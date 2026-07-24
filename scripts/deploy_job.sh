#!/usr/bin/env bash
# Deploy x402-cms-indexer Cloud Run Job from local source.
#
# Cloud Run Job (not Service) — runs
# `python -m code.indexers.github_indexer --kind all` once per
# invocation, fanning the repo into the merged / active / new Search
# qualifiers. Cloud Scheduler triggers a fresh execution every Monday
# morning so the weekly digest reflects last week's PR activity.
#
# The image is built from the same Dockerfile as the serving image but
# kept as a separate Job resource so the indexer code path is isolated
# from request handling at run time.
#
# Prereqs:
#   - gcloud auth login + project set to my-utilities-490202
#   - scripts/setup_sa.sh has been run (x402-cms-runner exists with
#     roles/datastore.user; the indexer only needs Firestore write)
#   - the GitHub token secret exists and the runner SA can read it.
#     Enrichment (touched paths + maintainer activity, issue #17) calls
#     the core REST API 1-3 times per PR; the unauthenticated quota
#     (60/hr) dies on a normal weekly batch, so the token is required:
#       printf '%s' "$GITHUB_TOKEN" | gcloud secrets create \
#         x402-github-indexer-token --data-file=-
#       gcloud secrets add-iam-policy-binding x402-github-indexer-token \
#         --member "serviceAccount:x402-cms-runner@my-utilities-490202.iam.gserviceaccount.com" \
#         --role roles/secretmanager.secretAccessor
#
# Usage:
#   ./scripts/deploy_job.sh
#
# To run the job once manually after deploy:
#   gcloud run jobs execute x402-cms-indexer --region asia-northeast1
set -euo pipefail

PROJECT="${GOOGLE_CLOUD_PROJECT:-my-utilities-490202}"
REGION="${REGION:-asia-northeast1}"
JOB="x402-cms-indexer"
SA_EMAIL="x402-cms-runner@${PROJECT}.iam.gserviceaccount.com"

cd "$(dirname "$0")/.."

gcloud run jobs deploy "$JOB" \
  --source . \
  --project "$PROJECT" \
  --region "$REGION" \
  --service-account "$SA_EMAIL" \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=${PROJECT}" \
  --set-secrets "GITHUB_TOKEN=x402-github-indexer-token:latest" \
  --command python \
  --args="-m,code.indexers.github_indexer,--kind,all" \
  --max-retries 1 \
  --task-timeout 900s \
  --memory 512Mi \
  --cpu 1
