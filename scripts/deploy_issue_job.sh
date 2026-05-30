#!/usr/bin/env bash
# Deploy x402-cms-issue-indexer Cloud Run Job from local source.
#
# Cloud Run Job (not Service) — runs
# `python -m code.indexers.github_issue_indexer` once per invocation.
# Cloud Scheduler triggers a fresh execution every Monday morning so
# the weekly digest reflects last week's active issue discussion
# (design RFCs, bug reports) alongside the merged / active / new PRs.
#
# Like the GitHub PR indexer Job, it calls the GitHub Search API
# unauthenticated (no secret attachments) and writes to Firestore
# through the x402-cms-runner service account.
#
# Prereqs:
#   - gcloud auth login + project set to my-utilities-490202
#   - scripts/setup_sa.sh has been run (x402-cms-runner exists with
#     roles/datastore.user; the indexer only needs Firestore write)
#
# Usage:
#   ./scripts/deploy_issue_job.sh
#
# To run the job once manually after deploy:
#   gcloud run jobs execute x402-cms-issue-indexer --region asia-northeast1
set -euo pipefail

PROJECT="${GOOGLE_CLOUD_PROJECT:-my-utilities-490202}"
REGION="${REGION:-asia-northeast1}"
JOB="x402-cms-issue-indexer"
SA_EMAIL="x402-cms-runner@${PROJECT}.iam.gserviceaccount.com"

cd "$(dirname "$0")/.."

gcloud run jobs deploy "$JOB" \
  --source . \
  --project "$PROJECT" \
  --region "$REGION" \
  --service-account "$SA_EMAIL" \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=${PROJECT}" \
  --command python \
  --args="-m,code.indexers.github_issue_indexer" \
  --max-retries 1 \
  --task-timeout 300s \
  --memory 512Mi \
  --cpu 1
