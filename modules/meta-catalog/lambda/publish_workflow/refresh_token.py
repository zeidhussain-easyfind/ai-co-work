import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any
import boto3
from logging_utils import log_event
from aws_secrets import get_secret

_secretsmanager = boto3.client("secretsmanager", region_name="us-east-1")

def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    secret_id = os.environ.get("META_SECRET_ID")
    if not secret_id:
        return {"status": "skipped", "reason": "META_SECRET_ID env var not set"}

    try:
        config = get_secret("META_SECRET_ID")
    except Exception as exc:
        log_event("token_refresh_failed", error=f"Could not load secret: {exc}")
        return {"status": "failed", "reason": str(exc)}

    app_id = config.get("app_id")
    app_secret = config.get("app_secret")
    access_token = config.get("access_token")
    
    if not app_id or not app_secret or not access_token:
        log_event("token_refresh_skipped", reason="app_id, app_secret, or access_token missing from secret")
        return {"status": "skipped", "reason": "App ID and App Secret must be added to the Meta secret to enable rotation."}

    graph_version = config.get("graph_version", "v20.0")
    params = {
        "grant_type": "fb_exchange_token",
        "client_id": app_id,
        "client_secret": app_secret,
        "fb_exchange_token": access_token,
    }
    query = urllib.parse.urlencode(params)
    url = f"https://graph.facebook.com/{graph_version}/oauth/access_token?{query}"

    try:
        request = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(request, timeout=15) as response:
            result = json.loads(response.read().decode())
    except Exception as exc:
        log_event("token_refresh_failed", error=f"Meta Graph API request failed: {exc}")
        return {"status": "failed", "reason": f"API request failed: {exc}"}

    new_token = result.get("access_token")
    if not new_token:
        log_event("token_refresh_failed", error=f"Response did not contain access_token: {result}")
        return {"status": "failed", "reason": "No access_token returned"}

    config["access_token"] = new_token
    try:
        _secretsmanager.put_secret_value(
            SecretId=secret_id,
            SecretString=json.dumps(config, separators=(",", ":")),
        )
        log_event("token_refresh_succeeded")
        return {"status": "success", "new_token_preview": f"{new_token[:8]}..."}
    except Exception as exc:
        log_event("token_refresh_failed", error=f"Failed to update secret in Secrets Manager: {exc}")
        return {"status": "failed", "reason": f"Secrets Manager update failed: {exc}"}
