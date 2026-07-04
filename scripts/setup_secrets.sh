#!/usr/bin/env bash
# One-time setup for runtime secrets consumed by Cloud Run.
#
# Provisions three secrets:
#   - `x402-cms-x-bearer`         X API bearer token (read as env var).
#   - `x402-cms-tracked-handles`  Private curated handle list (mounted
#                                 as a file so the indexer reads it the
#                                 same way it reads the local one).
#   - `x402-cms-topics`           Private topic mapping for the glance
#                                 view (mounted as a file the Service
#                                 reads at startup).
#
# No value enters `--set-env-vars` (which is visible in Cloud Audit
# Logs / Cloud Build logs); all land in Secret Manager and are
# attached via `--update-secrets`.
#
# The script is idempotent: re-running adds a new version to an
# existing secret rather than failing. A curated-file secret is
# skipped (with a warning) if the local file does not exist yet — a
# fresh clone with only the OSS example templates can still set up
# the bearer secret.
#
# Prereqs:
#   - gcloud auth login + project set to my-utilities-490202
#   - Secret Manager API enabled
#   - .env contains a non-empty X_BEARER_TOKEN line
#   - (optional) `config/tracked_handles.yaml` / `config/topics.yaml`
#     exist for the curated production inputs
set -euo pipefail

PROJECT="${GOOGLE_CLOUD_PROJECT:-my-utilities-490202}"
BEARER_SECRET="x402-cms-x-bearer"
HANDLES_SECRET="x402-cms-tracked-handles"
HANDLES_FILE="config/tracked_handles.yaml"
TOPICS_SECRET="x402-cms-topics"
TOPICS_FILE="config/topics.yaml"
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

# --- curated files (handles, topics) ----------------------------------

upsert_file_secret() {
  local secret="$1" file="$2"

  if [ ! -f "$file" ]; then
    echo "WARN: $file not found — skipping $secret." >&2
    echo "      The runtime falls back to its degraded default" >&2
    echo "      (example config / empty mapping)." >&2
    return 0
  fi

  if gcloud secrets describe "$secret" --project "$PROJECT" >/dev/null 2>&1; then
    gcloud secrets versions add "$secret" \
      --data-file="$file" \
      --project "$PROJECT" >/dev/null
    echo "New version added to existing secret: $secret"
  else
    gcloud secrets create "$secret" \
      --data-file="$file" \
      --replication-policy=automatic \
      --project "$PROJECT" >/dev/null
    echo "Secret created: $secret"
  fi

  gcloud secrets add-iam-policy-binding "$secret" \
    --project "$PROJECT" \
    --member "serviceAccount:${RUNNER_SA_EMAIL}" \
    --role "roles/secretmanager.secretAccessor" \
    >/dev/null

  echo "Secret accessor role granted to: $RUNNER_SA_EMAIL ($secret)"
}

upsert_file_secret "$HANDLES_SECRET" "$HANDLES_FILE"
upsert_file_secret "$TOPICS_SECRET" "$TOPICS_FILE"
