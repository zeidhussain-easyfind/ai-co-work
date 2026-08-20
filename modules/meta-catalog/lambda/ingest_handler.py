import base64
import json
import os
import urllib.parse
from typing import Any
import boto3

from dynamo import claim_event
from logging_utils import log_event
from routing import classify_message
from aws_secrets import get_secret
from slack_client import header, verify_signature

_sqs = boto3.client("sqs", region_name="ap-south-1")

def _response(status_code: int, body: dict[str, Any] | str = "") -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body) if not isinstance(body, str) else body,
    }

def _raw_body(event: dict[str, Any]) -> str:
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        return base64.b64decode(body).decode()
    return body

def _slack_credentials() -> dict[str, Any]:
    from aws_secrets import get_secret_value, get_secret_json
    signing_secret = get_secret_value("SLACK_SIGNING_SECRET_ID")
    bot_token = get_secret_value("SLACK_SECRET_ID")
    if signing_secret and bot_token:
        return {"signing_secret": signing_secret, "bot_token": bot_token}
    return get_secret_json("SLACK_SECRET_ID")

def _allowed(payload: dict[str, Any]) -> bool:
    configured_channel = os.environ.get("SLACK_CHANNEL_ID")
    message = payload.get("event", payload)
    message_channel = message.get("channel")
    if isinstance(message_channel, dict):
        message_channel = message_channel.get("id")
    payload_channel = payload.get("channel")
    if isinstance(payload_channel, dict):
        payload_channel = payload_channel.get("id")
    channel = message_channel or payload_channel
    if configured_channel and channel != configured_channel:
        return False
    allowed_users = {x.strip() for x in os.environ.get("ALLOWED_SLACK_USER_IDS", "").split(",") if x.strip()}
    user = message.get("user") or (payload.get("user") or {}).get("id")
    return not allowed_users or user in allowed_users

def _enqueue(message: dict[str, Any], group_id: str) -> None:
    _sqs.send_message(
        QueueUrl=os.environ["EVENT_QUEUE_URL"],
        MessageBody=json.dumps(message, separators=(",", ":")),
        MessageGroupId=group_id,
    )

def _parse_payload(raw: str, content_type: str) -> tuple[dict[str, Any], bool]:
    if "application/x-www-form-urlencoded" in content_type or raw.startswith("payload="):
        values = urllib.parse.parse_qs(raw)
        payload = json.loads(values.get("payload", ["{}"])[0])
        return payload, True
    return json.loads(raw or "{}"), False

def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    try:
        raw = _raw_body(event)
        
        try:
            content_type = header(event.get("headers"), "content-type")
            payload, _ = _parse_payload(raw, content_type)
            if payload.get("type") == "url_verification":
                return {
                    "statusCode": 200,
                    "headers": {"Content-Type": "text/plain"},
                    "body": payload.get("challenge", ""),
                }
        except Exception:
            pass

        credentials = _slack_credentials()
        if not verify_signature(
            event.get("headers"),
            raw,
            credentials.get("signing_secret", ""),
        ):
            return _response(401, {"error": "invalid Slack signature"})

        payload, is_interaction = _parse_payload(raw, header(event.get("headers"), "content-type"))
        
        slack_event = payload.get("event") or {}
        channel = slack_event.get("channel") or payload.get("channel") or {}
        channel_id = channel.get("id") if isinstance(channel, dict) else channel
        log_event("slack_incoming_request", channel_id=channel_id, type=payload.get("type"), event_type=slack_event.get("type"))

        if not _allowed(payload):
            return _response(200, "")

        if is_interaction:
            trigger_id = payload.get("trigger_id")
            if not trigger_id:
                return _response(200, "")
            if not claim_event(f"interaction:{trigger_id}"):
                return _response(200, "")
            actions = payload.get("actions") or []
            action = actions[0] if actions else {}
            action_id = str(action.get("action_id", ""))
            value = str(action.get("value", ""))
            property_id, _, field = value.partition(":")
            
            kind = None
            if action_id.startswith("edit_field:"):
                kind = "EDIT_FIELD"
            elif action_id == "confirm_publish":
                kind = "CONFIRM_PUBLISH"
            elif action_id == "unpublish":
                kind = "UNPUBLISH"
                
            if kind and property_id:
                _enqueue(
                    {
                        "kind": kind,
                        "property_id": property_id,
                        "field": field or None,
                        "channel": (payload.get("channel") or {}).get("id"),
                        "user": (payload.get("user") or {}).get("id"),
                    },
                    group_id=property_id,
                )
            return _response(200, "")

        slack_event = payload.get("event") or {}
        if slack_event.get("type") != "message":
            return _response(200, "")
        event_id = payload.get("event_id") or f"message:{slack_event.get('ts')}:{slack_event.get('user')}"
        if not claim_event(event_id):
            return _response(200, "")

        classification = classify_message(slack_event)
        if classification == "EXTRACT":
            from s3_client import upload_slack_image_to_s3

            s3_uris = []
            files = slack_event.get("files") or []
            bucket = os.environ["PROPERTY_IMAGE_BUCKET"]
            token = credentials.get("bot_token", "")
            thread_ts = slack_event.get("ts")
            for i, file in enumerate(files):
                if file.get("mimetype", "").startswith("image/") and file.get("url_private_download"):
                    try:
                        uri = upload_slack_image_to_s3(
                            slack_url=file["url_private_download"],
                            slack_token=token,
                            bucket=bucket,
                            thread_ts=thread_ts,
                            file_name=file.get("name", f"image_{i}"),
                        )
                        s3_uris.append(uri)
                    except Exception as exc:
                        log_event("s3_upload_failed", error=str(exc), file_url=file["url_private_download"])

            message_text = slack_event.get("text", "")
            attachments = slack_event.get("attachments") or []
            for att in attachments:
                attachment_parts = []
                if att.get("title"):
                    attachment_parts.append(att["title"])
                if att.get("text"):
                    attachment_parts.append(att["text"])
                if att.get("fallback"):
                    attachment_parts.append(att["fallback"])
                if attachment_parts:
                    message_text += "\n" + "\n".join(attachment_parts)

            _enqueue(
                {
                    "kind": "EXTRACT",
                    "event_id": event_id,
                    "channel": slack_event.get("channel"),
                    "user": slack_event.get("user"),
                    "text": message_text,
                    "thread_ts": thread_ts,
                    "image_urls": s3_uris,
                },
                group_id=thread_ts,
            )
        elif classification == "EDIT_OR_THREAD_REPLY":
            _enqueue(
                {
                    "kind": "EDIT_REPLY",
                    "event_id": event_id,
                    "channel": slack_event.get("channel"),
                    "user": slack_event.get("user"),
                    "text": slack_event.get("text", ""),
                    "thread_ts": slack_event.get("thread_ts"),
                },
                group_id=slack_event.get("thread_ts"),
            )
        log_event("slack_ingest", classification=classification, event_id=event_id)
        return _response(200, "")
    except Exception as e:
        log_event("ingest_handler_crashed", error=str(e), traceback="".join(__import__("traceback").format_exception(e)))
        return _response(500, "Internal Server Error")
