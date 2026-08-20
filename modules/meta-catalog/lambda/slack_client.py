import hashlib
import hmac
import json
import time
import urllib.error
import urllib.request
from typing import Any

def header(headers: dict[str, str] | None, name: str) -> str:
    for key, value in (headers or {}).items():
        if key.lower() == name.lower():
            return value
    return ""

def verify_signature(
    headers: dict[str, str] | None,
    body: str,
    signing_secret: str,
    now: int | None = None,
) -> bool:
    timestamp = header(headers, "X-Slack-Request-Timestamp")
    received = header(headers, "X-Slack-Signature")
    if not timestamp or not received or not signing_secret:
        return False
    try:
        timestamp_int = int(timestamp)
    except ValueError:
        return False
    if abs(int(now if now is not None else time.time()) - timestamp_int) > 300:
        return False
    base = f"v0:{timestamp}:{body}".encode()
    expected = "v0=" + hmac.new(signing_secret.encode(), base, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, received)

def post_message(token: str, channel: str, text: str, *, thread_ts: str | None = None, blocks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"channel": channel, "text": text}
    if thread_ts:
        payload["thread_ts"] = thread_ts
    if blocks:
        payload["blocks"] = blocks
    request = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            result = json.loads(response.read().decode())
    except Exception as exc:
        raise RuntimeError("Slack API request failed") from exc
    if not result.get("ok"):
        raise RuntimeError(f"Slack API error: {result.get('error', 'unknown_error')}")
    return result

def review_blocks(job: dict[str, Any]) -> list[dict[str, Any]]:
    from utils import format_inr, title_from_property

    data = job.get("property_data", {})
    property_id = job["property_id"]

    lines = [
        f"*{title_from_property(data)}*",
        f"Rent: {format_inr(data.get('rent'))}",
        f"Society: {data.get('society') or '—'}",
        f"Location: {data.get('locality') or data.get('city') or '—'}",
        f"Bedrooms: {data.get('bedrooms', '—')}  |  Bathrooms: {data.get('bathrooms', '—')}  |  Balconies: {data.get('balconies', '—')}",
        f"Furnishing: {data.get('furnishing', '—')}",
        f"Maintenance: {format_inr(data.get('maintenance'))}  |  Deposit: {format_inr(data.get('deposit'))}",
        f"Tenant Pref: {data.get('preferred_tenant') or '—'}  |  Pets Policy: {data.get('pets_allowed') or '—'}",
        f"Available: {data.get('available_from', '—')}",
        f"Description: {data.get('description', '—')}",
    ]
    blocks: list[dict[str, Any]] = [{"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}}]
    
    if job.get("status") == "PUBLISHED":
        published_elements = [
            {
                "type": "button",
                "action_id": "unpublish",
                "text": {"type": "plain_text", "text": "UNPUBLISH"},
                "style": "danger",
                "value": property_id,
                "confirm": {
                    "title": {"type": "plain_text", "text": "Are you sure?"},
                    "text": {"type": "mrkdwn", "text": f"This will remove `{property_id}` from the Meta catalogue."},
                    "confirm": {"type": "plain_text", "text": "Unpublish"},
                    "deny": {"type": "plain_text", "text": "Cancel"},
                },
            }
        ]
        blocks.append({"type": "actions", "elements": published_elements})

    buttons = [
        ("confirm_publish", "CONFIRM & PUBLISH", "primary", None),
        ("edit_field:rent", "Edit rent", "normal", "rent"),
        ("edit_field:society", "Edit society", "normal", "society"),
        ("edit_field:locality", "Edit location", "normal", "locality"),
        ("edit_field:bedrooms", "Edit bedrooms", "normal", "bedrooms"),
        ("edit_field:bathrooms", "Edit bathrooms", "normal", "bathrooms"),
        ("edit_field:balconies", "Edit balconies", "normal", "balconies"),
        ("edit_field:furnishing", "Edit furnishing", "normal", "furnishing"),
        ("edit_field:maintenance", "Edit maintenance", "normal", "maintenance"),
        ("edit_field:deposit", "Edit deposit", "normal", "deposit"),
        ("edit_field:preferred_tenant", "Edit tenant pref", "normal", "preferred_tenant"),
        ("edit_field:pets_allowed", "Edit pets policy", "normal", "pets_allowed"),
        ("edit_field:available_from", "Edit available date", "normal", "available_from"),
        ("edit_field:description", "Edit description", "normal", "description"),
    ]
    
    if job.get("status") != "PUBLISHED":
        for start in range(0, len(buttons), 5):
            elements = []
            for action_id, label, style, field in buttons[start : start + 5]:
                element = {
                    "type": "button",
                    "action_id": action_id,
                    "text": {"type": "plain_text", "text": label},
                    "value": property_id if field is None else f"{property_id}:{field}",
                }
                if style != "normal":
                    element["style"] = style
                elements.append(element)
            blocks.append({"type": "actions", "elements": elements})
            
    return blocks
