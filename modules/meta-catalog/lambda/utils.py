import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

PROPERTY_FIELDS = (
    "title",
    "bedrooms",
    "bathrooms",
    "balconies",
    "furnishing",
    "society",
    "locality",
    "city",
    "rent",
    "maintenance",
    "deposit",
    "available_from",
    "preferred_tenant",
    "pets_allowed",
    "description",
)

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

def generate_property_id(now: datetime | None = None) -> str:
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%d")
    return f"PROP-{stamp}-{uuid.uuid4().hex[:6].upper()}"

def format_inr(value: Any) -> str:
    if value in (None, ""):
        return "—"
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return str(value)
    return f"₹{amount:,.0f}"

def title_from_property(data: dict[str, Any]) -> str:
    furnishing = str(data.get("furnishing") or "Unfurnished").strip().title()
    bedrooms = data.get("bedrooms", "?")
    society = str(data.get("society") or "").strip().title()
    locality = str(data.get("locality") or data.get("city") or "Unknown location").strip()
    
    if society:
        location_label = f"{society}, {locality}" if locality and locality.lower() != society.lower() else society
    else:
        location_label = locality
        
    return f"{furnishing} {bedrooms} BHK - {location_label}"

def parse_edit_value(field: str, text: str) -> Any:
    value = text.strip()
    if not value:
        raise ValueError("The edited value cannot be empty")
    if field in {"bedrooms", "bathrooms", "balconies"}:
        try:
            parsed = int(value)
        except ValueError as exc:
            raise ValueError(f"{field} must be a whole number") from exc
        if parsed < 0:
            raise ValueError(f"{field} cannot be negative")
        return parsed
    if field in {"rent", "maintenance", "deposit"}:
        cleaned = re.sub(r"[₹,\s]", "", value)
        try:
            parsed = int(Decimal(cleaned))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"{field} must be numeric") from exc
        if parsed < 0:
            raise ValueError(f"{field} cannot be negative")
        return parsed
    return value
