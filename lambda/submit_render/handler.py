"""
Lambda: captionit-render-submit
Trigger: API Gateway POST /jobs

Receives a render job request, validates it, writes it to DynamoDB,
and enqueues it on SQS. Returns the job_id immediately.
"""

import json
import logging
import os
import time
import uuid
from typing import Any

import boto3
from pydantic import BaseModel, ValidationError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

DYNAMODB_TABLE = os.environ["DYNAMODB_TABLE"]
SQS_QUEUE_URL = os.environ["SQS_QUEUE_URL"]
API_KEY = os.environ["API_KEY"]
TTL_DAYS = 7

dynamodb = boto3.resource("dynamodb")
sqs = boto3.client("sqs")


class RenderRequest(BaseModel):
    project_id: str
    video_url: str
    video_s3_key: str
    caption_data: dict
    callback_url: str
    callback_secret: str | None = None
    max_height: int | None = None
    quality: str = "1080p"


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

    # 2. Parse + validate request body
    try:
        body = json.loads(event.get("body") or "{}")
        request = RenderRequest(**body)
    except (json.JSONDecodeError, ValidationError) as e:
        return _response(422, {"detail": str(e)})

    # 3. Create job
    job_id = str(uuid.uuid4())
    now = int(time.time())
    ttl = now + TTL_DAYS * 86400

    table = dynamodb.Table(DYNAMODB_TABLE)
    table.put_item(Item={
        "job_id": job_id,
        "project_id": request.project_id,
        "status": "queued",
        "created_at": now,
        "ttl": ttl,
    })

    # 4. Enqueue on SQS
    sqs.send_message(
        QueueUrl=SQS_QUEUE_URL,
        MessageBody=json.dumps({
            "job_id": job_id,
            "request": request.model_dump(),
        }),
    )

    logger.info(f"Queued job {job_id} for project {request.project_id}")
    return _response(202, {"job_id": job_id, "status": "queued"})
