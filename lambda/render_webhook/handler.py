"""
Lambda: captionit-render-webhook
Trigger: API Gateway POST /webhook/remotion-complete

Called by Remotion Lambda when a render finishes (success/error/timeout).
Verifies HMAC, looks up the job by render_id, copies the output file to
our S3 bucket, updates DynamoDB, and fires the backend callback.
"""

import hashlib
import hmac
import json
import logging
import os
import time
from urllib.parse import urlparse

import boto3
import httpx

logger = logging.getLogger()
logger.setLevel(logging.INFO)

DYNAMODB_TABLE = os.environ["DYNAMODB_TABLE"]
CALLBACK_HMAC_SECRET = os.environ["CALLBACK_HMAC_SECRET"]
AWS_S3_BUCKET = os.environ["AWS_S3_BUCKET"]
AWS_REGION = os.environ.get("AWS_REGION", "ap-south-1")

dynamodb = boto3.resource("dynamodb")
s3 = boto3.client("s3", region_name=AWS_REGION)


def _response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def _verify_remotion_signature(body_bytes: bytes, received_sig: str) -> bool:
    """Verify Remotion webhook HMAC-SHA512 signature.
    Remotion sends the header as: X-Remotion-Signature: sha512=<hex>
    """
    digest = hmac.new(
        CALLBACK_HMAC_SECRET.encode(),
        body_bytes,
        hashlib.sha512,
    ).hexdigest()
    expected = f"sha512={digest}"
    try:
        return hmac.compare_digest(received_sig, expected)
    except Exception:
        return False


def _lookup_job_by_render_id(render_id: str) -> dict | None:
    """Query the render_id-index GSI to find the job."""
    table = dynamodb.Table(DYNAMODB_TABLE)
    result = table.query(
        IndexName="render_id-index",
        KeyConditionExpression="render_id = :rid",
        ExpressionAttributeValues={":rid": render_id},
        Limit=1,
    )
    items = result.get("Items", [])
    return items[0] if items else None


def _update_job(job_id: str, patch: dict):
    table = dynamodb.Table(DYNAMODB_TABLE)
    set_parts = ", ".join(f"#{k} = :{k}" for k in patch)
    table.update_item(
        Key={"job_id": job_id},
        UpdateExpression=f"SET {set_parts}",
        ExpressionAttributeNames={f"#{k}": k for k in patch},
        ExpressionAttributeValues={f":{k}": v for k, v in patch.items()},
    )


def _fire_callback(job: dict, s3_key: str | None, error: str | None):
    """POST completion result to the backend callback URL."""
    callback_url = job.get("callback_url")
    if not callback_url:
        logger.warning(f"No callback_url on job {job.get('job_id')} — skipping callback")
        return

    payload = {
        "job_id": job["job_id"],
        "project_id": job["project_id"],
        "status": "success" if s3_key else "failed",
        "render_s3_key": s3_key,
        "file_size_bytes": None,
        "error": error,
    }
    body = json.dumps(payload).encode()
    secret = (job.get("callback_secret") or CALLBACK_HMAC_SECRET).encode()
    sig = hmac.new(secret, body, hashlib.sha256).hexdigest()

    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(
                callback_url,
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Render-Signature": f"sha256={sig}",
                },
            )
            resp.raise_for_status()
            logger.info(f"Callback fired → {resp.status_code}")
    except Exception as e:
        logger.error(f"Callback failed (non-fatal): {e}")


def lambda_handler(event: dict, context) -> dict:
    # 1. Parse body
    body_str = event.get("body") or ""
    body_bytes = body_str.encode() if isinstance(body_str, str) else body_str

    # 2. Verify Remotion HMAC signature
    received_sig = (event.get("headers") or {}).get("x-remotion-signature", "")
    if not _verify_remotion_signature(body_bytes, received_sig):
        logger.warning("Webhook: invalid HMAC signature")
        return _response(401, {"detail": "Invalid signature"})

    try:
        payload = json.loads(body_str)
    except json.JSONDecodeError:
        return _response(400, {"detail": "Invalid JSON"})

    webhook_type = payload.get("type")  # "success" | "error" | "timeout"
    render_id = payload.get("renderId")

    logger.info(f"Webhook received: type={webhook_type}, render_id={render_id}")

    # 3. Look up job by render_id
    job = _lookup_job_by_render_id(render_id)
    if not job:
        logger.error(f"No job found for render_id={render_id}")
        # Return 200 so Remotion doesn't retry indefinitely
        return _response(200, {"ok": True, "warning": "job not found"})

    job_id = job["job_id"]
    project_id = job["project_id"]
    now = int(time.time())

    # 4. Handle success
    if webhook_type == "success":
        output_url = payload.get("outputFile", "")
        quality = job.get("quality", "1080p")
        dest_key = f"renders/{project_id}/{quality}.mp4"

        try:
            parsed = urlparse(output_url)
            path_parts = parsed.path.lstrip("/").split("/", 1)
            src_bucket = path_parts[0]
            src_key = path_parts[1] if len(path_parts) > 1 else ""

            logger.info(f"Copying s3://{src_bucket}/{src_key} → s3://{AWS_S3_BUCKET}/{dest_key}")
            s3.copy_object(
                CopySource={"Bucket": src_bucket, "Key": src_key},
                Bucket=AWS_S3_BUCKET,
                Key=dest_key,
            )
            logger.info(f"Copy complete → s3://{AWS_S3_BUCKET}/{dest_key}")
        except Exception as copy_err:
            logger.error(f"S3 copy failed: {copy_err}", exc_info=True)
            error_msg = f"S3 copy failed: {copy_err}"
            _update_job(job_id, {"status": "failed", "error": error_msg, "completed_at": now})
            _fire_callback(job, None, error_msg)
            return _response(200, {"ok": True})

        _update_job(job_id, {
            "status": "success",
            "s3_key": dest_key,
            "completed_at": now,
        })
        _fire_callback(job, dest_key, None)

    # 5. Handle error / timeout
    else:
        errors = payload.get("errors", [])
        error_msg = errors[0].get("message", webhook_type) if errors else webhook_type
        logger.error(f"Render {webhook_type} for job {job_id}: {error_msg}")
        _update_job(job_id, {"status": "failed", "error": error_msg, "completed_at": now})
        _fire_callback(job, None, error_msg)

    return _response(200, {"ok": True})
