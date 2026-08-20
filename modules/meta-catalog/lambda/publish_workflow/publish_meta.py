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
    method: str = "GET",
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    params = params or {}
    url = f"https://graph.facebook.com/{path}"
    data = None
    if method in ("POST", "DELETE"):
        params["access_token"] = access_token
        data = urllib.parse.urlencode(params).encode()
        full_url = url
    else:
        params["access_token"] = access_token
        full_url = f"{url}?{urllib.parse.urlencode(params)}"

    request = urllib.request.Request(full_url, data=data, method=method)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            result = json.loads(response.read().decode())
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Meta Graph API {method} request to {path} failed: {exc}") from exc

    if result.get("error"):
        raise RuntimeError(f"Meta product operation failed: {result}")
    return result

def _find_existing_product(catalog_id: str, retailer_id: str, token: str) -> str | None:
    response = _graph_api_request(
        f"{catalog_id}/products",
        token,
        params={"filter": json.dumps({"retailer_id": {"eq": retailer_id}})},
    )
    products = response.get("data", [])
    return products[0]["id"] if products else None

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

    product_data = {
        "name": title_from_property(data),
        "description": data.get("description", ""),
        "price": f"{int(price)} {config.get('currency', 'INR')}",
        "availability": "in stock",
        "condition": "new",
        "image_url": (image_urls_from_state(event) or [None])[0],
        "url": data.get("url", "https://easyfindprops.com/listings"),
        "retailer_id": job["property_id"],
    }
    product_data = {key: value for key, value in product_data.items() if value not in (None, "")}
    
    path_base = f"{graph_version}/"
    existing_id = _find_existing_product(f"{path_base}{catalog_id}", job["property_id"], access_token)

    if existing_id:
        path = f"{path_base}{existing_id}"
        result = _graph_api_request(path, access_token, "POST", product_data)
        catalogue_id = existing_id
    else:
        path = f"{path_base}{catalog_id}/products"
        result = _graph_api_request(path, access_token, "POST", product_data)
        if not result.get("id"):
            raise RuntimeError(f"Meta product creation failed: {result}")
        catalogue_id = result["id"]

    return {**event, "catalogue_id": catalogue_id}
