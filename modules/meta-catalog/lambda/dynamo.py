import os
import time
from datetime import datetime, timezone
from typing import Any
import boto3
from botocore.exceptions import ClientError

_dynamodb = boto3.resource("dynamodb", region_name="ap-south-1")

# The existing workflow uses CONFIRMING as the atomic publish-lock state.
ALLOWED_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "PENDING_CONFIRMATION": ("AWAITING_EDIT", "CONFIRMING", "FAILED"),
    "AWAITING_EDIT": ("PENDING_CONFIRMATION", "FAILED"),
    "CONFIRMING": ("CONFIRMING", "PUBLISHED", "FAILED"),
    "PUBLISHED": (),
    "FAILED": (),
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _condition_failed(exc: ClientError) -> bool:
    return exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException"

def jobs_table():
    return _dynamodb.Table(os.environ["JOBS_TABLE_NAME"])

def events_table():
    return _dynamodb.Table(os.environ["EVENTS_TABLE_NAME"])

def thread_index_table():
    return _dynamodb.Table(os.environ["THREAD_INDEX_TABLE_NAME"])

def claim_event(event_id: str, ttl_seconds: int = 86_400) -> bool:
    try:
        events_table().put_item(
            Item={"event_id": event_id, "ttl": int(time.time()) + ttl_seconds},
            ConditionExpression="attribute_not_exists(event_id)",
        )
        return True
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise

def put_job(job: dict[str, Any]) -> None:
    jobs_table().put_item(Item=job, ConditionExpression="attribute_not_exists(property_id)")
    thread_index_table().put_item(
        Item={
            "slack_thread_ts": job["slack_thread_ts"],
            "property_id": job["property_id"],
            "ttl": int(time.time()) + 86_400,
        },
        ConditionExpression="attribute_not_exists(slack_thread_ts)",
    )

def get_job(property_id: str) -> dict[str, Any] | None:
    return jobs_table().get_item(Key={"property_id": property_id}).get("Item")

def get_job_by_thread(thread_ts: str) -> dict[str, Any] | None:
    index_item = thread_index_table().get_item(Key={"slack_thread_ts": thread_ts}).get("Item")
    if not index_item or not index_item.get("property_id"):
        return None
    return get_job(index_item["property_id"])

def set_awaiting_edit(property_id: str, field: str) -> bool:
    try:
        jobs_table().update_item(
            Key={"property_id": property_id},
            UpdateExpression="SET #status = :awaiting, edit_field = :field, updated_at = :now",
            ConditionExpression="#status = :pending",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":awaiting": "AWAITING_EDIT",
                ":pending": "PENDING_CONFIRMATION",
                ":field": field,
                ":now": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
            },
        )
        return True
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise

def apply_edit(property_id: str, field: str, value: Any) -> dict[str, Any] | None:
    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    response = jobs_table().update_item(
        Key={"property_id": property_id},
        UpdateExpression=(
            "SET property_data.#field = :value, #status = :pending, "
            "edit_field = :empty, updated_at = :now, #version = if_not_exists(#version, :zero) + :one"
        ),
        ConditionExpression="#status = :awaiting AND edit_field = :field",
        ExpressionAttributeNames={"#field": field, "#status": "status", "#version": "version"},
        ExpressionAttributeValues={
            ":value": value,
            ":pending": "PENDING_CONFIRMATION",
            ":awaiting": "AWAITING_EDIT",
            ":field": field,
            ":empty": None,
            ":now": now,
            ":zero": 0,
            ":one": 1,
        },
        ReturnValues="ALL_NEW",
    )
    return response.get("Attributes")

def lock_for_publish(property_id: str) -> bool:
    return transition_job_status(property_id, "PENDING_CONFIRMATION", "CONFIRMING")

def update_job_status(
    property_id: str,
    status: str,
    *,
    expected_current: str | None = None,
    error: str | None = None,
    catalogue_id: str | None = None,
    image_urls: list[str] | None = None,
) -> None:
    """Update a job status with an optional atomic expected-state guard."""
    if status not in ALLOWED_TRANSITIONS:
        raise ValueError(f"Unknown job status: {status}")
    if expected_current is not None and status not in ALLOWED_TRANSITIONS.get(expected_current, ()):
        raise ValueError(f"Illegal transition: {expected_current} -> {status}")

    names = {"#status": "status", "#updated": "updated_at"}
    values: dict[str, Any] = {":status": status, ":updated": _utc_now()}
    expression = "SET #status = :status, #updated = :updated"
    if error is not None:
        expression += ", last_error = :error"
        values[":error"] = error[:2000]
    if catalogue_id is not None:
        expression += ", catalogue_id = :catalogue"
        values[":catalogue"] = catalogue_id
    if image_urls is not None:
        expression += ", image_urls = :images"
        values[":images"] = image_urls

    kwargs: dict[str, Any] = {
        "Key": {"property_id": property_id},
        "UpdateExpression": expression,
        "ExpressionAttributeNames": names,
        "ExpressionAttributeValues": values,
    }
    if expected_current is not None:
        kwargs["ConditionExpression"] = "attribute_exists(property_id) AND #status = :expected"
        values[":expected"] = expected_current
    jobs_table().update_item(**kwargs)


def transition_job_status(property_id: str, expected_current: str, new_status: str, **attrs: Any) -> bool:
    """Return False for a lost race; propagate all other DynamoDB failures."""
    try:
        update_job_status(property_id, new_status, expected_current=expected_current, **attrs)
        return True
    except ClientError as exc:
        if _condition_failed(exc):
            return False
        raise
