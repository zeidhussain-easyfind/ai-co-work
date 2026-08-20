import os
import time
from typing import Any
import boto3
from botocore.exceptions import ClientError

_dynamodb = boto3.resource("dynamodb", region_name="ap-south-1")

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
    try:
        jobs_table().update_item(
            Key={"property_id": property_id},
            UpdateExpression="SET #status = :confirming, updated_at = :now",
            ConditionExpression="#status = :pending",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":confirming": "CONFIRMING",
                ":pending": "PENDING_CONFIRMATION",
                ":now": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
            },
        )
        return True
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise

def update_job_status(
    property_id: str,
    status: str,
    *,
    error: str | None = None,
    catalogue_id: str | None = None,
    image_urls: list[str] | None = None,
) -> None:
    names = {"#status": "status", "#updated": "updated_at"}
    values: dict[str, Any] = {":status": status, ":updated": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()}
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
    jobs_table().update_item(
        Key={"property_id": property_id},
        UpdateExpression=expression,
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
    )
