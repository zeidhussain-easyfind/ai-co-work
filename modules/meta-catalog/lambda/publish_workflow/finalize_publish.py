from functools import lru_cache
from typing import Any
import json
import dynamo
from logging_utils import log_event
from aws_secrets import get_secret
from slack_client import post_message
from utils import format_inr, title_from_property
from .common import error_text, image_urls_from_state, load_job

@lru_cache(maxsize=1)
def _sheets_service(credentials_json: str):
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    credentials = service_account.Credentials.from_service_account_info(
        json.loads(credentials_json),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return build("sheets", "v4", credentials=credentials, cache_discovery=False)

def _write_to_sheet(job: dict[str, Any], event: dict[str, Any]) -> None:
    try:
        config = get_secret("GOOGLE_SECRET_ID")
        spreadsheet_id = config.get("spreadsheet_id")
        service_account_json = config.get("service_account_json")
        if not spreadsheet_id or not service_account_json:
            raise RuntimeError("Google secret is not fully configured")

        data = job["property_data"]
        row = [
            job["property_id"],
            title_from_property(data),
            data.get("locality") or data.get("city", ""),
            data.get("bedrooms", ""),
            data.get("bathrooms", ""),
            data.get("furnishing", ""),
            format_inr(data.get("rent")),
            format_inr(data.get("maintenance")),
            format_inr(data.get("deposit")),
            data.get("available_from", ""),
            data.get("description", ""),
            ",".join(image_urls_from_state(event)),
        ]
        _sheets_service(service_account_json).spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=f"{config.get('tab_name', 'Live Inventory')}!A:L",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]},
        ).execute()
        log_event("sheet_write_succeeded", property_id=job["property_id"])
    except Exception as exc:
        log_event("sheet_write_failed", property_id=job["property_id"], error=str(exc))

def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    job = load_job(event)
    success = event.get("finalize_status") == "PUBLISHED"
    if success:
        catalogue_id = event.get("catalogue_id", "")
        dynamo.update_job_status(
            job["property_id"],
            "PUBLISHED",
            expected_current="CONFIRMING",
            catalogue_id=catalogue_id,
            image_urls=event.get("image_urls", []),
        )
        text = f"Submitted `{job['property_id']}` for review. It should appear in the catalogue shortly. Meta id: `{catalogue_id}`"
        log_event("publish_succeeded", property_id=job["property_id"], catalogue_id=catalogue_id)
        _write_to_sheet(job, event)
    else:
        error = error_text(event)
        dynamo.update_job_status(job["property_id"], "FAILED", expected_current="CONFIRMING", error=error)
        text = f"Publishing `{job['property_id']}` failed. Please fix the issue and retry: {error}"
        log_event("publish_failed", property_id=job["property_id"], error=error)

    from aws_secrets import get_secret_value, get_secret_json
    token = get_secret_value("SLACK_SECRET_ID")
    if token and token.startswith("{"):
        token = get_secret_json("SLACK_SECRET_ID").get("bot_token", "")
        
    if job.get("slack_channel") and token:
        post_message(token, job["slack_channel"], text, thread_ts=job.get("slack_thread_ts"))
        
    return {"property_id": job["property_id"], "status": "PUBLISHED" if success else "FAILED"}
