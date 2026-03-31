import logging
import os

import boto3

from app.config import Settings

logger = logging.getLogger(__name__)


def get_s3_client(settings: Settings):
    kwargs = dict(
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )
    if settings.aws_endpoint_url:
        kwargs["endpoint_url"] = settings.aws_endpoint_url
    return boto3.client("s3", **kwargs)


def upload_video(local_path: str, s3_key: str, settings: Settings) -> int:
    """Upload rendered video to S3. Returns file size in bytes."""
    client = get_s3_client(settings)
    client.upload_file(local_path, settings.aws_s3_bucket, s3_key)
    size = os.path.getsize(local_path)
    logger.info(f"Uploaded {local_path} → s3://{settings.aws_s3_bucket}/{s3_key} ({size} bytes)")
    return size
