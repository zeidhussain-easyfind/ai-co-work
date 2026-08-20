from __future__ import annotations
from datetime import date
from typing import Any, List, Optional
from pydantic import BaseModel, Field, field_validator, AliasChoices

class PropertyData(BaseModel):
    title: Optional[str] = Field(None, description="Title of the listing")
    bedrooms: Optional[int] = Field(None, ge=0, description="Number of bedrooms (BHK)")
    bathrooms: Optional[int] = Field(None, ge=0, description="Number of bathrooms")
    balconies: Optional[int] = Field(None, ge=0, description="Number of balconies")
    furnishing: Optional[str] = Field(None, description="Furnishing status")
    society: Optional[str] = Field(None, validation_alias=AliasChoices("society", "apartment_name", "building_name"), description="Society or Apartment Name")
    locality: Optional[str] = Field(None, validation_alias=AliasChoices("locality", "location"), description="Locality or area name")
    city: Optional[str] = Field(None, description="City name")
    rent: int = Field(..., gt=0, description="Monthly rent amount (must be positive)")
    maintenance: Optional[int] = Field(None, ge=0, description="Monthly maintenance fee")
    deposit: Optional[int] = Field(None, ge=0, description="Security deposit amount")
    available_from: Optional[str] = Field(None, description="Availability date (as text or ISO date)")
    preferred_tenant: Optional[str] = Field(None, description="Preferred tenant policy")
    pets_allowed: Optional[str] = Field(None, description="Pets allowed policy")
    description: Optional[str] = Field(None, description="Detailed description of the property")
    image_urls: List[str] = Field(default_factory=list, description="List of image URLs")

    @field_validator("furnishing", mode="before")
    @classmethod
    def normalize_furnishing(cls, v: Any) -> Optional[str]:
        if isinstance(v, str):
            val = v.strip().lower()
            if "semi" in val:
                return "Semi-Furnished"
            if "un" in val:
                return "Unfurnished"
            if "full" in val or val == "furnished":
                return "Furnished"
            return v.strip().title()
        return v

    @field_validator("available_from", mode="before")
    @classmethod
    def normalize_date(cls, v: Any) -> Optional[str]:
        if isinstance(v, (date, str)):
            return str(v).strip()
        return v
