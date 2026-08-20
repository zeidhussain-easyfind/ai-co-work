import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any
from aws_secrets import get_secret
from utils import title_from_property
from .common import image_urls_from_state, load_job

def _graph_api_request(
    path: str,
    access_token: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    url = f"https://graph.facebook.com/{path}"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            result = json.loads(response.read().decode())
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Meta Graph API request to {path} failed: {exc}") from exc

    if result.get("error"):
        raise RuntimeError(f"Meta product operation failed: {result}")
    return result

def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    job = load_job(event)
    from aws_secrets import get_secret_value, get_secret_json
    
    catalog_id = get_secret_value("META_CATALOG_ID")
    access_token = get_secret_value("META_SECRET_ID")
    graph_version = "v20.0"
    
    if not catalog_id or not access_token:
        config = get_secret_json("META_SECRET_ID")
        catalog_id = config.get("catalog_id")
        access_token = config.get("access_token")
        graph_version = config.get("graph_version", "v20.0")
    else:
        config = {"currency": "INR", "graph_version": "v20.0"}
        
    if not catalog_id or not access_token:
        raise RuntimeError("Meta credentials (catalog_id and access_token) are not configured.")

    data = job["property_data"]
    price = data.get("rent")
    if price in (None, ""):
        raise ValueError("Cannot publish a listing without rent")

    product_payload = {
        "access_token": access_token,
        "item_type": "PRODUCT_ITEM",
        "allow_upsert": True,
        "requests": [
            {
                "method": "CREATE",
                "data": {
                    "id": job["property_id"],
                    "title": title_from_property(data),
                    "description": data.get("description", ""),
                    "price": f"{int(price)} {config.get('currency', 'INR')}",
                    "availability": "in stock",
                    "condition": "new",
                    "image_link": (image_urls_from_state(event) or ["https://res.cloudinary.com/demo/image/upload/sample.jpg"])[0],
                    "link": data.get("url") or "https://easyfindprops.com/listings",
                    "brand": "EasyFind"
                }
            }
        ]
    }
    
    path_base = f"{graph_version}/"
    path = f"{path_base}{catalog_id}/items_batch"
    
    result = _graph_api_request(path, access_token, product_payload)
    
    # Store the first batch handle as the reference
    handles = result.get("handles", [])
    catalogue_id = handles[0] if handles else job["property_id"]

    return {**event, "catalogue_id": catalogue_id}
