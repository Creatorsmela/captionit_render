#!/usr/bin/env python3
"""Verify Remotion Lambda configuration is correct"""

import os
from urllib.parse import urlparse
from app.config import get_settings

settings = get_settings()

print("=" * 70)
print("REMOTION LAMBDA CONFIGURATION VERIFICATION")
print("=" * 70)

# Extract region from serve URL
serve_url = settings.remotion_lambda_serve_url
parsed = urlparse(serve_url)
hostname = parsed.hostname
# Extract region from hostname like: remotionlambda-apsouth1-ysxu1xtptu.s3.ap-south-1.amazonaws.com
# The region is: ap-south-1 (from s3.ap-south-1.amazonaws.com)
url_region = parsed.hostname.split(".s3.")[1].split(".")[0] if ".s3." in parsed.hostname else "UNKNOWN"

print(f"\n1️⃣  BUCKET VERIFICATION")
print(f"   Serve URL: {serve_url}")
print(f"   Extracted bucket: {parsed.hostname.split('.')[0]}")

print(f"\n2️⃣  REGION VERIFICATION")
print(f"   AWS_REGION (env): {settings.aws_region}")
print(f"   REMOTION_LAMBDA_REGION: {settings.remotion_lambda_region}")
print(f"   Region from serve URL: {url_region}")

# Check for mismatches
regions = [settings.aws_region, settings.remotion_lambda_region, url_region]
if len(set(regions)) == 1:
    print(f"   ✅ All regions MATCH: {regions[0]}")
else:
    print(f"   ❌ REGION MISMATCH!")
    print(f"      - AWS_REGION: {settings.aws_region}")
    print(f"      - REMOTION_LAMBDA_REGION: {settings.remotion_lambda_region}")
    print(f"      - Serve URL region: {url_region}")

print(f"\n3️⃣  FUNCTION & BUCKET")
print(f"   Lambda function: {settings.remotion_lambda_function_name}")
print(f"   S3 bucket (general): {settings.aws_s3_bucket}")
print(f"   S3 bucket (remotion): {parsed.hostname.split('.')[0]}")

print(f"\n4️⃣  AWS CREDENTIALS")
print(f"   Access Key ID: {settings.aws_access_key_id[:10]}...{settings.aws_access_key_id[-5:]}")
print(f"   Secret Key: {'***' if settings.aws_secret_access_key else 'NOT SET'}")

print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)

errors = []

# Check regions match
if not (settings.aws_region == settings.remotion_lambda_region == url_region):
    errors.append("❌ Region mismatch")

# Check credentials
if not settings.aws_access_key_id or not settings.aws_secret_access_key:
    errors.append("❌ AWS credentials missing")

# Check serve URL format
if not settings.remotion_lambda_serve_url.startswith("https://"):
    errors.append("❌ Serve URL must start with https://")

if errors:
    print("\n⚠️  ISSUES FOUND:")
    for error in errors:
        print(f"  {error}")
else:
    print("\n✅ All configuration checks PASSED!")

print("=" * 70)
