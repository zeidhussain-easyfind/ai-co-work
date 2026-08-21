import os
import sys

import pytest
from pydantic import ValidationError

sys.path.append(os.path.join(os.path.dirname(__file__), "../lambda"))

from publish_browser import publish_with_browser
from validation import parse_property_prompt


def valid_prompt() -> str:
    return "|".join([
        "2 BHK Home", "2", "2", "1", "semi-furnished", "Prestige", "Whitefield",
        "Bengaluru", "45,000", "3,000", "90,000", "2026-09-01", "Family", "No",
        "Bright home near transit",
    ])


def test_parse_property_prompt_validates_and_normalizes():
    result = parse_property_prompt(valid_prompt())
    assert result.rent == 45000
    assert result.maintenance == 3000
    assert result.furnishing == "Semi-Furnished"


def test_parse_property_prompt_rejects_wrong_field_count():
    with pytest.raises(ValueError, match="exactly 15"):
        parse_property_prompt("rent|45000")


def test_parse_property_prompt_rejects_invalid_date():
    parts = valid_prompt().split("|")
    parts[11] = "tomorrow"
    with pytest.raises(ValidationError, match="YYYY-MM-DD"):
        parse_property_prompt("|".join(parts))


def test_parse_property_prompt_rejects_invalid_rent():
    parts = valid_prompt().split("|")
    parts[8] = "free"
    with pytest.raises(ValueError, match="rent"):
        parse_property_prompt("|".join(parts))


def test_browser_publisher_never_claims_success():
    result = publish_with_browser("PROP-1", {"rent": 45000})
    assert result["success"] is False
    assert "disabled" in result["error"]
