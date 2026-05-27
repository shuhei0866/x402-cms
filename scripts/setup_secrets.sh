#!/usr/bin/env bash
# One-time setup for runtime secrets consumed by Cloud Run Jobs.
#
# Provisions two secrets:
#   - `x402-cms-x-bearer`         X API bearer token (read as env var).
#   - `x402-cms-tracked-handles`  Private curated handle list (mounted
#                                 as a file so the indexer reads it the
#                                 same way it reads the local one).
#
# Neither value enters `--set-env-vars` (which is visible in Cloud
# Audit Logs / Cloud Build logs); both land in Secret Manager and are
# attached to the job via `--update-secrets`.
#
# The script is idempotent: re-running adds a new version to an
# existing secret rather than failing. The handles secret is skipped
# (with a warning) if the local file does not exist yet — a fresh
# clone with only the OSS example template can still set up the
# bearer secret.
#
# Prereqs:
#   - gcloud auth login + project set to my-utilities-490202
#   - Secret Manager API enabled
#   - .env contains a non-empty X_BEARER_TOKEN line
#   - (optional) `config/tracked_handles.yaml` exists for the
#     curated production handle list
set -euo pipefail

PROJECT="${GOOGLE_CLOUD_PROJECT:-my-utilities-490202}"
BEARER_SECRET="x402-cms-x-bearer"
HANDLES_SECRET="x402-cms-tracked-handles"
HANDLES_FILE="config/tracked_handles.yaml"
RUNNER_SA_EMAIL="x402-cms-runner@${PROJECT}.iam.gserviceaccount.com"

cd "$(dirname "$0")/.."

set -a
# shellcheck disable=SC1091
source .env
set +a

# --- bearer token -----------------------------------------------------

if [ -z "${X_BEARER_TOKEN:-}" ]; then
  echo "ERROR: X_BEARER_TOKEN is not set in .env" >&2
  exit 1
fi

if gcloud secrets describe "$BEARER_SECRET" --project "$PROJECT" >/dev/null 2>&1; then
  printf '%s' "$X_BEARER_TOKEN" \
    | gcloud secrets versions add "$BEARER_SECRET" \
        --data-file=- \
        --project "$PROJECT" >/dev/null
  echo "New version added to existing secret: $BEARER_SECRET"
else
  printf '%s' "$X_BEARER_TOKEN" \
    | gcloud secrets create "$BEARER_SECRET" \
        --data-file=- \
        --replication-policy=automatic \
        --project "$PROJECT" >/dev/null
  echo "Secret created: $BEARER_SECRET"
fi

gcloud secrets add-iam-policy-binding "$BEARER_SECRET" \
  --project "$PROJECT" \
  --member "serviceAccount:${RUNNER_SA_EMAIL}" \
  --role "roles/secretmanager.secretAccessor" \
  >/dev/null

echo "Secret accessor role granted to: $RUNNER_SA_EMAIL ($BEARER_SECRET)"

# --- curated handle list ---------------------------------------------

if [ ! -f "$HANDLES_FILE" ]; then
  echo "WARN: $HANDLES_FILE not found — skipping $HANDLES_SECRET." >&2
  echo "      The Cloud Run Job will fall back to whatever path its" >&2
  echo "      --handles-config points at (the OSS example, by default)." >&2
  exit 0
fi

if gcloud secrets describe "$HANDLES_SECRET" --project "$PROJECT" >/dev/null 2>&1; then
  gcloud secrets versions add "$HANDLES_SECRET" \
    --data-file="$HANDLES_FILE" \
    --project "$PROJECT" >/dev/null
  echo "New version added to existing secret: $HANDLES_SECRET"
else
  gcloud secrets create "$HANDLES_SECRET" \
    --data-file="$HANDLES_FILE" \
    --replication-policy=automatic \
    --project "$PROJECT" >/dev/null
  echo "Secret created: $HANDLES_SECRET"
fi

gcloud secrets add-iam-policy-binding "$HANDLES_SECRET" \
  --project "$PROJECT" \
  --member "serviceAccount:${RUNNER_SA_EMAIL}" \
  --role "roles/secretmanager.secretAccessor" \
  >/dev/null

echo "Secret accessor role granted to: $RUNNER_SA_EMAIL ($HANDLES_SECRET)"
