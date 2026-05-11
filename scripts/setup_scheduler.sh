#!/usr/bin/env bash
# One-time setup for the Cloud Scheduler -> Cloud Run Job invocation.
#
# Creates `x402-cms-scheduler@<project>.iam.gserviceaccount.com`,
# grants it `roles/run.invoker` on the indexer Job, then creates (or
# updates) a Cloud Scheduler HTTP job that POSTs to the Job's `:run`
# endpoint every Monday 09:00 JST. The OAuth token Cloud Scheduler
# attaches identifies the scheduler SA, and Cloud Run accepts the
# invocation because that SA holds the invoker role on the Job.
#
# Idempotent: re-running the script does not duplicate the SA, the
# binding, or the Scheduler job (update is used when it already
# exists).
#
# Prereqs:
#   - gcloud auth login + project set to my-utilities-490202
#   - The Cloud Run Job `x402-cms-indexer` already exists
#     (run scripts/deploy_job.sh first)
#   - Cloud Scheduler API enabled
set -euo pipefail

PROJECT="${GOOGLE_CLOUD_PROJECT:-my-utilities-490202}"
REGION="${REGION:-asia-northeast1}"
JOB="x402-cms-indexer"
SCHEDULER_SA_NAME="x402-cms-scheduler"
SCHEDULER_SA_EMAIL="${SCHEDULER_SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
SCHEDULE_JOB="x402-cms-indexer-weekly"
SCHEDULE_CRON="0 9 * * MON"
SCHEDULE_TZ="Asia/Tokyo"

# 1. Scheduler SA — minted only to call Cloud Run Jobs admin endpoints.
if gcloud iam service-accounts describe "$SCHEDULER_SA_EMAIL" \
     --project "$PROJECT" >/dev/null 2>&1; then
  echo "Scheduler SA already exists: $SCHEDULER_SA_EMAIL"
else
  gcloud iam service-accounts create "$SCHEDULER_SA_NAME" \
    --project "$PROJECT" \
    --display-name "x402-cms Cloud Scheduler invoker"
fi

# 2. Allow the scheduler SA to invoke this specific Cloud Run Job only.
gcloud run jobs add-iam-policy-binding "$JOB" \
  --project "$PROJECT" \
  --region "$REGION" \
  --member "serviceAccount:${SCHEDULER_SA_EMAIL}" \
  --role "roles/run.invoker" \
  >/dev/null

echo "run.invoker granted on job $JOB to $SCHEDULER_SA_EMAIL"

# 3. Cloud Scheduler API uses Cloud Run Admin v1 namespaces endpoint
#    for the :run RPC; that is the same one the gcloud docs reference.
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
