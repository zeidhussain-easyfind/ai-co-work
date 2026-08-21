from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PropertyPromptData(BaseModel):
    """Validated property fields accepted at the ingestion boundary."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=200)
    bedrooms: int | None = Field(default=None, ge=0)
    bathrooms: int | None = Field(default=None, ge=0)
    balconies: int | None = Field(default=None, ge=0)
    furnishing: str | None = Field(default=None, max_length=50)
    society: str | None = Field(default=None, max_length=200)
    locality: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=100)
    rent: int = Field(gt=0)
    maintenance: int | None = Field(default=None, ge=0)
    deposit: int | None = Field(default=None, ge=0)
    available_from: str | None = Field(default=None, max_length=32)
    preferred_tenant: str | None = Field(default=None, max_length=100)
    pets_allowed: str | None = Field(default=None, max_length=50)
    description: str | None = Field(default=None, max_length=2000)
    image_urls: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("available_from")
    @classmethod
    def validate_available_from(cls, value: str | None) -> str | None:
        if value:
            try:
                datetime.strptime(value, "%Y-%m-%d")
            except ValueError as exc:
                raise ValueError("available_from must use YYYY-MM-DD format") from exc
        return value

    @field_validator("furnishing", mode="before")
    @classmethod
    def normalize_furnishing(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        normalized = value.strip().lower()
        if "semi" in normalized:
            return "Semi-Furnished"
        if "un" in normalized:
            return "Unfurnished"
        if "full" in normalized or normalized == "furnished":
            return "Furnished"
        return value.strip().title()


def parse_property_prompt(prompt: str) -> PropertyPromptData:
    """Parse the documented pipe-delimited catalog format.

    Fields are ordered as: title, bedrooms, bathrooms, balconies, furnishing,
    society, locality, city, rent, maintenance, deposit, available_from,
    preferred_tenant, pets_allowed, description.
    Empty optional fields are represented by empty segments. Image URLs are
    intentionally supplied through the existing Slack attachment flow.
    """
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("property prompt cannot be empty")
    parts = [part.strip() for part in prompt.split("|")]
    if len(parts) != 15:
        raise ValueError("expected exactly 15 pipe-delimited property fields")

    def optional_int(value: str, field: str) -> int | None:
        if not value:
            return None
        try:
            return int(value.replace(",", ""))
        except ValueError as exc:
            raise ValueError(f"{field} must be a whole number") from exc

    def _required_int(value: str, field: str) -> int:
        try:
            return int(value.replace(",", ""))
        except ValueError as exc:
            raise ValueError(f"{field} must be a whole number") from exc

    try:
        return PropertyPromptData(
            title=parts[0] or None,
            bedrooms=optional_int(parts[1], "bedrooms"),
            bathrooms=optional_int(parts[2], "bathrooms"),
            balconies=optional_int(parts[3], "balconies"),
            furnishing=parts[4] or None,
            society=parts[5] or None,
            locality=parts[6] or None,
            city=parts[7] or None,
            rent=_required_int(parts[8], "rent"),
            maintenance=optional_int(parts[9], "maintenance"),
            deposit=optional_int(parts[10], "deposit"),
            available_from=parts[11] or None,
            preferred_tenant=parts[12] or None,
            pets_allowed=parts[13] or None,
            description=parts[14] or None,
        )
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"invalid property prompt: {exc}") from exc
