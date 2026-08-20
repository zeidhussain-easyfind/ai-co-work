import mimetypes
import os
import urllib.request
from typing import Any
import boto3

_s3 = boto3.client("s3", region_name="ap-south-1")

def _download_from_slack(url: str, slack_token: str) -> tuple[bytes, str]:
    headers = {"Authorization": f"Bearer {slack_token}"}
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=8) as response:
        content_type = response.headers.get_content_type()
        max_bytes = int(os.environ.get("MAX_IMAGE_BYTES", "8388608"))
        data = response.read(max_bytes + 1)

    if len(data) > max_bytes:
        raise ValueError(f"Image at {url} exceeds max size of {max_bytes} bytes")

    allowed_types = {"image/jpeg", "image/png", "image/webp", "image/gif"}
    if content_type not in allowed_types:
        raise ValueError(f"Unsupported image type '{content_type}' for URL {url}")

    return data, content_type

def upload_slack_image_to_s3(
    slack_url: str,
    slack_token: str,
    bucket: str,
    thread_ts: str,
    file_name: str,
) -> str:
    content, content_type = _download_from_slack(slack_url, slack_token)
    key = f"raw/{thread_ts}/{file_name}"

    _s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=content,
        ContentType=content_type,
    )
    return f"s3://{bucket}/{key}"
