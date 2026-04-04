"""
Lambda: captionit-render-get-job
Trigger: API Gateway GET /jobs/{job_id}

Returns the current status of a render job from DynamoDB.
"""

import json
import logging
import os
from typing import Any

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

DYNAMODB_TABLE = os.environ["DYNAMODB_TABLE"]
API_KEY = os.environ["API_KEY"]

dynamodb = boto3.resource("dynamodb")


def _response(status_code: int, body: Any) -> dict:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def lambda_handler(event: dict, context) -> dict:
    # 1. Verify Bearer token
    auth_header = (event.get("headers") or {}).get("authorization", "")
    if not auth_header.startswith("Bearer ") or auth_header[7:] != API_KEY:
        return _response(401, {"detail": "Unauthorized"})

    # 2. Get job_id from path
    job_id = (event.get("pathParameters") or {}).get("job_id")
    if not job_id:
        return _response(400, {"detail": "Missing job_id"})

    # 3. Fetch from DynamoDB
    table = dynamodb.Table(DYNAMODB_TABLE)
    result = table.get_item(Key={"job_id": job_id})
    item = result.get("Item")

    if not item:
        return _response(404, {"detail": "Job not found"})

    # Remove internal TTL field before returning
    item.pop("ttl", None)

    return _response(200, item)
