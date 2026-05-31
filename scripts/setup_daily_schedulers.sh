#!/usr/bin/env bash
# Daily Cloud Scheduler triggers that refresh the IN-PROGRESS week.
#
# The weekly Monday schedulers (setup_scheduler.sh / setup_x_scheduler.sh
# / setup_issue_scheduler.sh) finalise the week that just closed: they
# run each Job with its default args, which resolve to the previous ISO
# week. These daily entries hit the SAME three Jobs every morning but
# override the container args to append `--current`, so the digest for
# the week still in progress is refreshed once a day instead of only
# after it ends.
#
# Args are overridden at execution time through the Cloud Run Admin v2
# `jobs:run` endpoint (`overrides.containerOverrides[].args`), so no
# duplicate Job resources are needed — one Job, two schedules. The
# weekly schedule keeps the Job's baked-in args (previous week); the
# daily schedule swaps in the `--current` variant.
#
# Reuses the existing `x402-cms-scheduler` service account, already
# granted roles/run.invoker on all three Jobs by the weekly setup
# scripts (run.invoker covers both the v1 and v2 :run calls).
#
# Idempotent: re-running updates the existing schedules in place.
#
# Prereqs:
#   - gcloud auth login + project set to my-utilities-490202
#   - the three Jobs exist and run a `--current`-capable image
#     (deploy_job.sh / deploy_issue_job.sh / deploy_x_job.sh)
#   - the weekly setup scripts have run (they create the scheduler SA
#     and the run.invoker bindings this script reuses)
set -euo pipefail

PROJECT="${GOOGLE_CLOUD_PROJECT:-my-utilities-490202}"
REGION="${REGION:-asia-northeast1}"
SCHEDULER_SA_EMAIL="x402-cms-scheduler@${PROJECT}.iam.gserviceaccount.com"
SCHEDULE_CRON="0 9 * * *"
SCHEDULE_TZ="Asia/Tokyo"

# IAM: passing `--current` as a container-arg override needs
# `run.jobs.runWithOverrides`, which roles/run.invoker (used by the
# weekly schedules) does not carry. A least-privilege custom role holds
# exactly run.jobs.run + run.jobs.runWithOverrides, granted per-Job to
# the existing scheduler SA. Both are idempotent.
ROLE_ID="x402cmsJobOverrideRunner"
ROLE="projects/${PROJECT}/roles/${ROLE_ID}"

if gcloud iam roles describe "$ROLE_ID" --project "$PROJECT" >/dev/null 2>&1; then
  echo "custom role $ROLE_ID exists"
else
  gcloud iam roles create "$ROLE_ID" --project "$PROJECT" \
    --title "x402-cms job override runner" \
    --description "Run Cloud Run jobs with arg overrides for daily current-week indexers" \
    --permissions run.jobs.run,run.jobs.runWithOverrides \
    --stage GA >/dev/null
  echo "created custom role $ROLE_ID"
fi

grant_override_role() {
  gcloud run jobs add-iam-policy-binding "$1" \
    --region "$REGION" --project "$PROJECT" \
    --member "serviceAccount:${SCHEDULER_SA_EMAIL}" \
    --role "$ROLE" >/dev/null
  echo "$ROLE_ID granted on $1 to $SCHEDULER_SA_EMAIL"
}

grant_override_role "x402-cms-indexer"
grant_override_role "x402-cms-issue-indexer"
grant_override_role "x402-cms-x-indexer"

upsert_daily() {
  local schedule_job="$1" job="$2" args_json="$3"
  local uri body
  uri="https://run.googleapis.com/v2/projects/${PROJECT}/locations/${REGION}/jobs/${job}:run"
  body="{\"overrides\":{\"containerOverrides\":[{\"args\":${args_json}}]}}"

  if gcloud scheduler jobs describe "$schedule_job" \
       --location "$REGION" --project "$PROJECT" >/dev/null 2>&1; then
    gcloud scheduler jobs update http "$schedule_job" \
      --location "$REGION" --project "$PROJECT" \
      --schedule "$SCHEDULE_CRON" --time-zone "$SCHEDULE_TZ" \
      --uri "$uri" --http-method POST \
      --update-headers "Content-Type=application/json" \
      --message-body "$body" \
      --oauth-service-account-email "$SCHEDULER_SA_EMAIL" >/dev/null
    echo "updated $schedule_job -> $job (--current, daily $SCHEDULE_CRON $SCHEDULE_TZ)"
  else
    gcloud scheduler jobs create http "$schedule_job" \
      --location "$REGION" --project "$PROJECT" \
      --schedule "$SCHEDULE_CRON" --time-zone "$SCHEDULE_TZ" \
      --uri "$uri" --http-method POST \
      --headers "Content-Type=application/json" \
      --message-body "$body" \
      --oauth-service-account-email "$SCHEDULER_SA_EMAIL"
    echo "created $schedule_job -> $job (--current, daily $SCHEDULE_CRON $SCHEDULE_TZ)"
  fi
}

upsert_daily "x402-cms-indexer-daily" "x402-cms-indexer" \
  '["-m","code.indexers.github_indexer","--kind","all","--current"]'
upsert_daily "x402-cms-issue-indexer-daily" "x402-cms-issue-indexer" \
  '["-m","code.indexers.github_issue_indexer","--current"]'
upsert_daily "x402-cms-x-indexer-daily" "x402-cms-x-indexer" \
  '["-m","code.indexers.x_indexer","--handles-config","/secrets/tracked_handles.yaml","--current"]'
