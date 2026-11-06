#!/usr/bin/env bash
# Rebuild the presentation data and publish it to AWS Amplify (manual deploy).
# Usage: ./deploy_presentation.sh   (needs the AWS CLI logged in to the account that owns the app)
set -euo pipefail

APP_ID="d2rlekfkelg009"
BRANCH="main"
ROOT="$(cd "$(dirname "$0")" && pwd)"
ZIP="$(mktemp -d)/site.zip"

python3 "$ROOT/presentation/build_data.py"
(cd "$ROOT/presentation" && zip -q "$ZIP" index.html data.js)

read -r JOB URL <<< "$(aws amplify create-deployment --app-id "$APP_ID" --branch-name "$BRANCH" \
  --query '[jobId,zipUploadUrl]' --output text)"
curl -sf -X PUT -H "Content-Type: application/zip" --data-binary @"$ZIP" "$URL"
aws amplify start-deployment --app-id "$APP_ID" --branch-name "$BRANCH" --job-id "$JOB" > /dev/null

for _ in $(seq 1 30); do
  STATUS=$(aws amplify get-job --app-id "$APP_ID" --branch-name "$BRANCH" --job-id "$JOB" \
    --query job.summary.status --output text)
  echo "Deploy $JOB: $STATUS"
  [[ "$STATUS" == "SUCCEED" || "$STATUS" == "FAILED" ]] && break
  sleep 5
done

echo "Live at https://$BRANCH.$APP_ID.amplifyapp.com"
