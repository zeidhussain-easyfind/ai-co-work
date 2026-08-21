import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any
import boto3
import dynamo
from logging_utils import log_event
from aws_secrets import get_secret
from .common import load_job

_s3 = boto3.client("s3", region_name="ap-south-1")

def _multipart(fields: dict[str, str], name: str, content: bytes, content_type: str) -> tuple[bytes, str]:
    boundary = f"----PropertyBot{hashlib.sha1(str(time.time()).encode()).hexdigest()[:16]}"
    chunks: list[bytes] = []
    for key, value in fields.items():
        chunks.extend([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode(),
            str(value).encode(),
            b"\r\n",
        ])
    chunks.extend([
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="{name}"; filename="listing-image"\r\n'.encode(),
        f"Content-Type: {content_type}\r\n\r\n".encode(),
        content,
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ])
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"

def _download_from_s3(s3_uri: str) -> tuple[bytes, str]:
    parsed_uri = urllib.parse.urlparse(s3_uri)
    bucket = parsed_uri.netloc
    key = parsed_uri.path.lstrip("/")
    response = _s3.get_object(Bucket=bucket, Key=key)
    content_type = response["ContentType"] or "image/jpeg"
    data = response["Body"].read()
    return data, content_type

def _upload_to_cloudinary(data: bytes, content_type: str, config: dict[str, Any]) -> str:
    cloud_name = config.get("cloud_name")
    api_key = config.get("api_key")
    api_secret = config.get("api_secret")
    if not cloud_name or not api_key or not api_secret:
        raise RuntimeError("Cloudinary secret must include cloud_name, api_key, and api_secret")

    timestamp = str(int(time.time()))
    to_sign = f"timestamp={timestamp}{api_secret}".encode()
    signature = hashlib.sha1(to_sign).hexdigest()

    body, content_header = _multipart(
        {"api_key": api_key, "timestamp": timestamp, "signature": signature},
        "file",
        data,
        content_type,
    )
    request = urllib.request.Request(
        f"https://api.cloudinary.com/v1_1/{cloud_name}/image/upload",
        data=body,
        headers={"Content-Type": content_header},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            result = json.loads(response.read().decode())
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        raise RuntimeError("Cloudinary upload failed") from exc
    if not result.get("secure_url"):
        raise RuntimeError(f"Cloudinary upload failed: {result}")
    return result["secure_url"]

def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    job = load_job(event)
    s3_uris = list(job.get("image_urls") or [])
    if not s3_uris:
        return {**event, "image_urls": []}

    from aws_secrets import get_secret_value, get_secret_json
    
    cloud_name = get_secret_value("CLOUDINARY_CLOUD_NAME_ID")
    api_key = get_secret_value("CLOUDINARY_API_KEY_ID")
    if api_key and api_key.startswith("{"):
        api_key = get_secret_json("CLOUDINARY_API_KEY_ID").get("api_key", "")
        
    api_secret = get_secret_value("CLOUDINARY_SECRET_ID")
    
    if cloud_name and api_key and api_secret:
        config = {"cloud_name": cloud_name, "api_key": api_key, "api_secret": api_secret}
    else:
        config = get_secret_json("CLOUDINARY_SECRET_ID")
        
    output_urls: list[str] = []
    for uri in s3_uris:
        if uri.startswith("s3://"):
            try:
                data, content_type = _download_from_s3(uri)
                output_urls.append(_upload_to_cloudinary(data, content_type, config))
            except Exception as exc:
                log_event("cloudinary_upload_failed", error=str(exc), s3_uri=uri)
        elif "res.cloudinary.com" in uri:
            output_urls.append(uri)
        
    dynamo.update_job_status(job["property_id"], "CONFIRMING", expected_current="CONFIRMING", image_urls=output_urls)
    log_event("images_uploaded", property_id=job["property_id"], count=len(output_urls))
    return {**event, "image_urls": output_urls}
