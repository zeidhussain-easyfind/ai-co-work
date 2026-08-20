import json
import os
from functools import lru_cache
from typing import Any
import boto3

_sm = boto3.client("secretsmanager", region_name="ap-south-1")

@lru_cache(maxsize=32)
def _get_secret_string(secret_id: str) -> str:
    if not secret_id:
        raise RuntimeError("Secrets Manager secret ID is not configured")
    response = _sm.get_secret_value(SecretId=secret_id)
    raw = response.get("SecretString")
    if raw is None:
        raise RuntimeError(f"Secret {secret_id} does not contain SecretString")
    return raw.strip()

def get_secret_value(env_name: str) -> str:
    try:
        return _get_secret_string(os.environ.get(env_name, ""))
    except Exception:
        return ""

def get_secret_json(env_name: str) -> dict[str, Any]:
    raw = get_secret_value(env_name)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}

def get_secret(env_name: str) -> dict[str, Any]:
    return get_secret_json(env_name)
