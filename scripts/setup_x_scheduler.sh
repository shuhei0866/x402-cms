#!/usr/bin/env bash
# One-time setup for the Cloud Scheduler -> Cloud Run Job invocation
# of the X indexer.
#
# Reuses the existing `x402-cms-scheduler` service account (created
# by setup_scheduler.sh for the GitHub indexer); only the
# `roles/run.invoker` binding for this specific Job and a new
# Cloud Scheduler entry are added. Single SA = single audit trail
# across both weekly jobs.
#
# Idempotent: re-running does not duplicate the binding or the
# Scheduler job.
#
# Prereqs:
#   - gcloud auth login + project set to my-utilities-490202
#   - Cloud Run Job `x402-cms-x-indexer` exists (run
#     scripts/deploy_x_job.sh first)
#   - `x402-cms-scheduler` SA exists (run scripts/setup_scheduler.sh
#     first for the GitHub indexer; that one creates the SA)
#   - Cloud Scheduler API enabled
set -euo pipefail

PROJECT="${GOOGLE_CLOUD_PROJECT:-my-utilities-490202}"
REGION="${REGION:-asia-northeast1}"
JOB="x402-cms-x-indexer"
SCHEDULER_SA_EMAIL="x402-cms-scheduler@${PROJECT}.iam.gserviceaccount.com"
SCHEDULE_JOB="x402-cms-x-indexer-weekly"
SCHEDULE_CRON="0 9 * * MON"
SCHEDULE_TZ="Asia/Tokyo"

# 1. Allow the existing scheduler SA to invoke this specific Job.
gcloud run jobs add-iam-policy-binding "$JOB" \
  --project "$PROJECT" \
  --region "$REGION" \
  --member "serviceAccount:${SCHEDULER_SA_EMAIL}" \
  --role "roles/run.invoker" \
  >/dev/null

echo "run.invoker granted on job $JOB to $SCHEDULER_SA_EMAIL"

# 2. Cloud Scheduler entry — same time slot as the GitHub indexer so
#    both digests reflect the same ISO week boundary.
JOB_URI="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT}/jobs/${JOB}:run"

if gcloud scheduler jobs describe "$SCHEDULE_JOB" \
     --location "$REGION" \
     --project "$PROJECT" >/dev/null 2>&1; then
  gcloud scheduler jobs update http "$SCHEDULE_JOB" \
    --location "$REGION" \
    --project "$PROJECT" \
    --schedule "$SCHEDULE_CRON" \
    --time-zone "$SCHEDULE_TZ" \
    --uri "$JOB_URI" \
    --http-method POST \
    --oauth-service-account-email "$SCHEDULER_SA_EMAIL" \
    >/dev/null
  echo "Scheduler job updated: $SCHEDULE_JOB (cron='$SCHEDULE_CRON' tz=$SCHEDULE_TZ)"
else
  gcloud scheduler jobs create http "$SCHEDULE_JOB" \
    --location "$REGION" \
    --project "$PROJECT" \
    --schedule "$SCHEDULE_CRON" \
    --time-zone "$SCHEDULE_TZ" \
    --uri "$JOB_URI" \
    --http-method POST \
    --oauth-service-account-email "$SCHEDULER_SA_EMAIL"
  echo "Scheduler job created: $SCHEDULE_JOB (cron='$SCHEDULE_CRON' tz=$SCHEDULE_TZ)"
fi
