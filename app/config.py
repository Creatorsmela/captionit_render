from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    port: int = 8001
    environment: str = "development"

    # Auth — callers must send this as Bearer token
    api_key: str = ""

    # Queue
    redis_url: str = ""                  # empty = Layer 1 (local), set = Layer 2 (Redis)
    max_concurrent_renders: int = 2      # worker count per container
    max_queue_size: int = 200            # max waiting jobs before 429

    # AWS S3
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_s3_bucket: str = ""
    aws_region: str = "ap-south-1"
    aws_endpoint_url: str = ""           # LocalStack only — leave empty for real AWS

    # HMAC — shared with captionit-backend for callback verification
    callback_hmac_secret: str = ""

    # Remotion Lambda
    remotion_lambda_function_name: str = ""            # e.g. remotion-render-3-3-96-mem3009mb-disk2048mb-900sec
    remotion_lambda_serve_url: str = ""                # S3 site URL from: npx remotion lambda sites create
    remotion_lambda_region: str = "ap-south-1"
    remotion_lambda_frames_per_lambda: int = 500

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()
