#!/usr/bin/env bash
# One-time setup for the Cloud Run runtime service account.
#
# Creates `x402-cms-runner@<project>.iam.gserviceaccount.com` and
# binds `roles/datastore.user` so the deployed service can read the
# Firestore-backed digest source. The script is idempotent: re-running
# it does not duplicate the SA or the binding.
set -euo pipefail

PROJECT="${GOOGLE_CLOUD_PROJECT:-my-utilities-490202}"
SA_NAME="x402-cms-runner"
SA_EMAIL="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"

if gcloud iam service-accounts describe "$SA_EMAIL" \
     --project "$PROJECT" >/dev/null 2>&1; then
  echo "SA already exists: $SA_EMAIL"
else
  gcloud iam service-accounts create "$SA_NAME" \
    --project "$PROJECT" \
    --display-name "x402-cms Cloud Run runtime"
fi

gcloud projects add-iam-policy-binding "$PROJECT" \
  --member "serviceAccount:${SA_EMAIL}" \
  --role "roles/datastore.user" \
  --condition=None \
  >/dev/null

echo "Service account ready: $SA_EMAIL"

# `gcloud run deploy --source .` runs Cloud Build under the project's
# default compute service account. New projects do not grant it build
# permissions automatically, so we attach `roles/cloudbuild.builds.builder`
# here. The role is a bundled set covering Artifact Registry writes,
# source-bucket reads, and log writes — the minimum a source-based
# deploy needs.
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"
COMPUTE_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

gcloud projects add-iam-policy-binding "$PROJECT" \
  --member "serviceAccount:${COMPUTE_SA}" \
  --role "roles/cloudbuild.builds.builder" \
  --condition=None \
  >/dev/null

echo "Cloud Build role granted to: $COMPUTE_SA"
