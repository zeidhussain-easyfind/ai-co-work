import json
import os
from datetime import datetime, timezone
from typing import Any
import boto3
from botocore.exceptions import ClientError

import dynamo
from llm.fallback_chain import extract_property
from logging_utils import log_event
from aws_secrets import get_secret
from slack_client import post_message, review_blocks
from utils import generate_property_id, parse_edit_value

_sfn = boto3.client("stepfunctions", region_name="ap-south-1")

def _slack_token() -> str:
    from aws_secrets import get_secret_value, get_secret_json
    token = get_secret_value("SLACK_SECRET_ID")
    if token and not token.startswith("{"):
        return token
    return get_secret_json("SLACK_SECRET_ID").get("bot_token", "")

def _post(channel: str | None, text: str, *, thread_ts: str | None = None, blocks: list[dict[str, Any]] | None = None) -> None:
    if not channel:
        return
    post_message(_slack_token(), channel, text, thread_ts=thread_ts, blocks=blocks)

def _extract(message: dict[str, Any]) -> None:
    # 1. Asynchronously download images from Slack and upload to S3 in the background worker
    s3_uris = []
    slack_files = message.get("slack_files") or []
    if slack_files:
        from s3_client import upload_slack_image_to_s3
        bucket = os.environ["PROPERTY_IMAGE_BUCKET"]
        token = _slack_token()
        for file in slack_files:
            try:
                uri = upload_slack_image_to_s3(
                    slack_url=file["url"],
                    slack_token=token,
                    bucket=bucket,
                    thread_ts=message["thread_ts"],
                    file_name=file["name"],
                )
                s3_uris.append(uri)
            except Exception as exc:
                log_event("worker_s3_upload_failed", error=str(exc))

    # 2. Execute Multimodal Gemini extraction using S3 images and raw text
    data = extract_property(message["text"], image_urls=s3_uris)
    property_id = generate_property_id()
    now = datetime.now(timezone.utc).isoformat()
    job = {
        "property_id": property_id,
        "status": "PENDING_CONFIRMATION",
        "slack_thread_ts": message["thread_ts"],
        "slack_channel": message.get("channel"),
        "slack_user": message.get("user"),
        "edit_field": None,
        "property_data": data,
        "image_urls": s3_uris,
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    dynamo.put_job(job)
    _post(
        message.get("channel"),
        f"Review listing `{property_id}`. Please confirm or edit each field.",
        thread_ts=message["thread_ts"],
        blocks=review_blocks(job),
    )

def _edit_field(message: dict[str, Any]) -> None:
    property_id = message["property_id"]
    job = dynamo.get_job(property_id)
    if not job:
        return
    field = message.get("field")
    allowed = {
        "rent", "location", "locality", "bedrooms", "bathrooms", "balconies",
        "furnishing", "society", "maintenance", "deposit", "preferred_tenant", "pets_allowed", "available_from", "description",
    }
    if field not in allowed:
        _post(message.get("channel"), "That field cannot be edited from Slack.", thread_ts=job.get("slack_thread_ts"))
        return
    if field == "location":
        field = "locality"
    if not dynamo.set_awaiting_edit(property_id, field):
        _post(message.get("channel"), "This listing is already being edited or published.", thread_ts=job.get("slack_thread_ts"))
        return
    labels = {
        "rent": "monthly rent",
        "society": "apartment or society name",
        "locality": "location",
        "bedrooms": "bedrooms",
        "bathrooms": "bathrooms",
        "balconies": "balconies count",
        "furnishing": "furnishing",
        "maintenance": "maintenance",
        "deposit": "deposit",
        "preferred_tenant": "preferred tenants",
        "pets_allowed": "pets policy",
        "available_from": "availability date",
        "description": "description",
    }
    _post(
        message.get("channel") or job.get("slack_channel"),
        f"Reply in this thread with the new {labels[field]}.",
        thread_ts=job.get("slack_thread_ts"),
    )

def _edit_reply(message: dict[str, Any]) -> None:
    job = dynamo.get_job_by_thread(message.get("thread_ts", ""))
    if not job:
        return
    if job.get("status") != "AWAITING_EDIT" or not job.get("edit_field"):
        _post(message.get("channel") or job.get("slack_channel"), "This thread is not currently awaiting an edit.", thread_ts=job.get("slack_thread_ts"))
        return
    field = job["edit_field"]
    try:
        value = parse_edit_value(field, message["text"])
    except ValueError as exc:
        _post(message.get("channel") or job.get("slack_channel"), str(exc), thread_ts=job.get("slack_thread_ts"))
        return
    updated = dynamo.apply_edit(job["property_id"], field, value)
    if not updated:
        _post(message.get("channel") or job.get("slack_channel"), "This edit is no longer pending.", thread_ts=job.get("slack_thread_ts"))
        return
    _post(
        message.get("channel") or updated.get("slack_channel"),
        f"Updated `{field}`. Please review the listing again.",
        thread_ts=updated.get("slack_thread_ts"),
        blocks=review_blocks(updated),
    )

def _confirm_publish(message: dict[str, Any]) -> None:
    property_id = message["property_id"]
    job = dynamo.get_job(property_id)
    if not job:
        return
    if not dynamo.lock_for_publish(property_id):
        _post(message.get("channel") or job.get("slack_channel"), "This listing is already processing or has been published.", thread_ts=job.get("slack_thread_ts"))
        return
    try:
        execution_input = {"property_id": property_id}
        _sfn.start_execution(
            stateMachineArn=os.environ["PUBLISH_STATE_MACHINE_ARN"],
            name=f"{property_id}-{job.get('version', 1)}",
            input=json.dumps(execution_input),
        )
        _post(message.get("channel") or job.get("slack_channel"), "Publishing started. I’ll post the result here.", thread_ts=job.get("slack_thread_ts"))
    except Exception as exc:
        dynamo.update_job_status(property_id, "FAILED", error=str(exc))
        raise

def handler(event: dict[str, Any], context: Any) -> None:
    for record in event.get("Records", []):
        try:
            body = json.loads(record["body"])
            kind = body.get("kind")
            log_event("worker_processing_record", kind=kind, property_id=body.get("property_id"))
            
            if kind == "EXTRACT":
                _extract(body)
            elif kind == "EDIT_FIELD":
                _edit_field(body)
            elif kind == "EDIT_REPLY":
                _edit_reply(body)
            elif kind == "CONFIRM_PUBLISH":
                _confirm_publish(body)
        except Exception as exc:
            log_event("worker_record_failed", error=str(exc))
            raise
