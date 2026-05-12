#!/usr/bin/env bash
# One-time setup for runtime secrets consumed by Cloud Run Jobs.
#
# Currently provisions a single secret, `x402-cms-x-bearer`, which
# holds the X (Twitter) API bearer token the x_indexer job reads as
# `X_BEARER_TOKEN`. The token never enters `--set-env-vars` (which
# is visible in Cloud Audit Logs / Cloud Build logs); it lands in
# Secret Manager and is mounted into the job via `--update-secrets`.
#
# Reads the token from `.env`. The script is idempotent: re-running
# adds a new version to an existing secret rather than failing.
#
# Prereqs:
#   - gcloud auth login + project set to my-utilities-490202
#   - Secret Manager API enabled
#   - .env contains a non-empty X_BEARER_TOKEN line
set -euo pipefail

PROJECT="${GOOGLE_CLOUD_PROJECT:-my-utilities-490202}"
SECRET_NAME="x402-cms-x-bearer"
RUNNER_SA_EMAIL="x402-cms-runner@${PROJECT}.iam.gserviceaccount.com"

cd "$(dirname "$0")/.."

set -a
# shellcheck disable=SC1091
source .env
set +a

if [ -z "${X_BEARER_TOKEN:-}" ]; then
  echo "ERROR: X_BEARER_TOKEN is not set in .env" >&2
  exit 1
fi

if gcloud secrets describe "$SECRET_NAME" --project "$PROJECT" >/dev/null 2>&1; then
  printf '%s' "$X_BEARER_TOKEN" \
    | gcloud secrets versions add "$SECRET_NAME" \
        --data-file=- \
        --project "$PROJECT" >/dev/null
  echo "New version added to existing secret: $SECRET_NAME"
else
  printf '%s' "$X_BEARER_TOKEN" \
    | gcloud secrets create "$SECRET_NAME" \
        --data-file=- \
        --replication-policy=automatic \
        --project "$PROJECT" >/dev/null
  echo "Secret created: $SECRET_NAME"
fi

# The runtime SA reads the secret at startup, so it needs
# `roles/secretmanager.secretAccessor` on this specific secret.
gcloud secrets add-iam-policy-binding "$SECRET_NAME" \
  --project "$PROJECT" \
  --member "serviceAccount:${RUNNER_SA_EMAIL}" \
  --role "roles/secretmanager.secretAccessor" \
  >/dev/null

echo "Secret accessor role granted to: $RUNNER_SA_EMAIL"
