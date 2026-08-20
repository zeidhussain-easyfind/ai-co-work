from __future__ import annotations
import base64
import os
import urllib.parse
from typing import Any
import boto3
from .common import EXTRACTION_PROMPT, ProviderError, extract_and_validate, http_json

_s3 = boto3.client("s3", region_name="ap-south-1")

def _download_s3_bytes(s3_uri: str) -> tuple[bytes, str]:
    parsed = urllib.parse.urlparse(s3_uri)
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    res = _s3.get_object(Bucket=bucket, Key=key)
    content_type = res["ContentType"] or "image/jpeg"
    return res["Body"].read(), content_type

def extract(text: str, config: dict[str, Any], timeout: float, image_urls: list[str] | None = None) -> dict[str, Any]:
    key = config.get("api_key")
    if not key:
        raise ProviderError("Gemini api_key is not configured")

    models = config.get("models", ["gemini-1.5-flash", "gemini-1.5-pro"])
    base_endpoint = "https://generativelanguage.googleapis.com/v1beta/models/"

    # Prepare multimodal payload parts
    parts = [{"text": EXTRACTION_PROMPT.format(text=text)}]
    
    # Download and Base64-encode S3 images if provided
    for url in (image_urls or []):
        if url.startswith("s3://"):
            try:
                img_bytes, mime_type = _download_s3_bytes(url)
                parts.append({
                    "inlineData": {
                        "mimeType": mime_type,
                        "data": base64.b64encode(img_bytes).decode("utf-8")
                    }
                })
            except Exception as exc:
                print(f"DIAGNOSTIC - S3 download of {url} failed: {exc}")

    # Explicit OpenAPI Schema enforcement for Gemini's structured response MimeType
    response_schema = {
        "type": "OBJECT",
        "properties": {
            "title": {"type": "STRING", "description": "Title of the listing"},
            "bedrooms": {"type": "INTEGER", "description": "Number of bedrooms (BHK)"},
            "bathrooms": {"type": "INTEGER", "description": "Number of bathrooms"},
            "balconies": {"type": "INTEGER", "description": "Number of balconies"},
            "furnishing": {"type": "STRING", "description": "Furnishing status (Furnished, Semi-Furnished, Unfurnished)"},
            "society": {"type": "STRING", "description": "Apartment name, society name, or building name"},
            "locality": {"type": "STRING", "description": "Locality or area name"},
            "city": {"type": "STRING", "description": "City name"},
            "rent": {"type": "INTEGER", "description": "Monthly rent amount (positive integer)"},
            "maintenance": {"type": "INTEGER", "description": "Monthly maintenance fee (positive integer)"},
            "deposit": {"type": "INTEGER", "description": "Security deposit amount (positive integer)"},
            "available_from": {"type": "STRING", "description": "Availability date (as text or ISO date string)"},
            "preferred_tenant": {"type": "STRING", "description": "Preferred tenant details (e.g. Vegetarian family, Bachelors, Anyone)"},
            "pets_allowed": {"type": "STRING", "description": "Pets policy (e.g. Allowed, Not allowed)"},
            "description": {"type": "STRING", "description": "Beautiful, professional summary incorporating all features"}
        },
        "required": ["rent"]
    }

    for model in models:
        endpoint = f"{base_endpoint}{model}:generateContent"
        try:
            response = http_json(
                f"{endpoint}?key={key}",
                {
                    "contents": [{"parts": parts}],
                    "generationConfig": {
                        "temperature": 0,
                        "responseMimeType": "application/json",
                        "responseSchema": response_schema
                    },
                },
                {},
                timeout,
            )
            content = response["candidates"][0]["content"]["parts"][0]["text"]
            return extract_and_validate(content)
        except Exception as exc:
            print(f"DIAGNOSTIC - Model {model} failed: {exc}")
            last_error = exc
            continue

    raise ProviderError(f"Gemini failed for all models: {last_error}")
