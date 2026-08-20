from __future__ import annotations
import json
from typing import Any
import dynamo

def load_job(event: dict[str, Any]) -> dict[str, Any]:
    property_id = event.get("property_id")
    if not property_id:
        raise ValueError("Publish state is missing property_id")
    job = dynamo.get_job(property_id)
    if not job:
        raise ValueError(f"Property job {property_id} was not found")
    return job

def state_property_data(event: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
    return dict(job.get("property_data") or {})

def error_text(event: dict[str, Any]) -> str:
    value = event.get("error", "Unknown publish error")
    if isinstance(value, dict):
        return json.dumps(value, default=str)
    return str(value)

def image_urls_from_state(event: dict[str, Any]) -> list[str]:
    upload_result = event.get("upload_result") or {}
    if isinstance(upload_result, dict):
        payload = upload_result.get("Payload", upload_result)
        if isinstance(payload, dict) and payload.get("image_urls") is not None:
            return list(payload["image_urls"])
    return list(event.get("image_urls") or [])
