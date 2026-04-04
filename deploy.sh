#!/bin/bash
# Deploy captionit_render_serverless — fully isolated from the existing Docker app.
# The existing captionit_render container keeps running unchanged.
#
# Prerequisites:
#   - AWS CLI configured: aws configure
#   - SAM CLI installed: pip install aws-sam-cli
#   - Node.js 22+ installed (for process_render Lambda)
#
# First deploy (interactive, creates S3 bucket for artifacts):
#   ./deploy.sh --guided
#
# Subsequent deploys:
#   ./deploy.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "==> Building Lambda packages..."
sam build --parallel --cached

echo "==> Deploying to AWS (stack: captionit-render-serverless)..."
sam deploy "$@"

echo ""
echo "==> Deployment complete!"
echo "==> Copy the ApiUrl output value and set it as RENDER_SERVICE_URL in CaptionIT-Backend/.env"
echo "==> The existing captionit_render Docker app is unaffected."
