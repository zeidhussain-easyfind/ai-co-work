import sys
import os
import pytest
from datetime import datetime, timezone, date
from pydantic import ValidationError

# Append lambda folder to path to import modules
sys.path.append(os.path.join(os.path.dirname(__file__), '../lambda'))

from utils import format_inr, generate_property_id, title_from_property, parse_edit_value
from schemas import PropertyData
from slack_client import header, verify_signature, review_blocks
from routing import classify_message
from llm.providers.common import extract_and_validate, ProviderError

# ---------------------------------------------------------------------------
# Test Cases 1-5: utils.format_inr()
# ---------------------------------------------------------------------------

def test_01_format_inr_none():
    assert format_inr(None) == "—"

def test_02_format_inr_empty():
    assert format_inr("") == "—"

def test_03_format_inr_int():
    assert format_inr(50000) == "₹50,000"

def test_04_format_inr_float():
    # Decimal or float rounding-to-even formatting
    assert format_inr(12500.50) == "₹12,500"

def test_05_format_inr_invalid():
    assert format_inr("not-a-number") == "not-a-number"

# ---------------------------------------------------------------------------
# Test Cases 6-9: Property ID and Title generation
# ---------------------------------------------------------------------------

def test_06_generate_property_id():
    now = datetime(2026, 8, 20, tzinfo=timezone.utc)
    prop_id = generate_property_id(now)
    assert prop_id.startswith("PROP-20260820-")
    assert len(prop_id) == 20

def test_07_title_furnished_bhk_society():
    data = {
        "furnishing": "Fully Furnished",
        "bedrooms": 3,
        "society": "Prestige Green Gables",
        "locality": "Kadubeesanahalli"
    }
    assert title_from_property(data) == "Fully Furnished 3 BHK - Prestige Green Gables, Kadubeesanahalli"

def test_08_title_unfurnished_bhk_no_society():
    data = {
        "furnishing": "unfurnished",
        "bedrooms": 2,
        "locality": "Bellandur"
    }
    assert title_from_property(data) == "Unfurnished 2 BHK - Bellandur"

def test_09_title_locality_fallback():
    data = {
        "bedrooms": 1,
        "city": "Mumbai"
    }
    assert title_from_property(data) == "Unfurnished 1 BHK - Mumbai"

# ---------------------------------------------------------------------------
# Test Cases 10-15: utils.parse_edit_value()
# ---------------------------------------------------------------------------

def test_10_parse_edit_value_bedrooms_valid():
    assert parse_edit_value("bedrooms", " 3 ") == 3

def test_11_parse_edit_value_bedrooms_invalid():
    with pytest.raises(ValueError) as exc:
        parse_edit_value("bedrooms", "three")
    assert "must be a whole number" in str(exc.value)

def test_12_parse_edit_value_bedrooms_negative():
    with pytest.raises(ValueError) as exc:
        parse_edit_value("bedrooms", "-2")
    assert "cannot be negative" in str(exc.value)

def test_13_parse_edit_value_rent_valid():
    assert parse_edit_value("rent", " ₹50,000 ") == 50000

def test_14_parse_edit_value_rent_invalid():
    with pytest.raises(ValueError) as exc:
        parse_edit_value("rent", "free")
    assert "must be numeric" in str(exc.value)

def test_15_parse_edit_value_rent_negative():
    with pytest.raises(ValueError) as exc:
        parse_edit_value("rent", " -₹15,000 ")
    assert "cannot be negative" in str(exc.value)

# ---------------------------------------------------------------------------
# Test Cases 16-21: schemas.PropertyData & normalizers
# ---------------------------------------------------------------------------

def test_16_pydantic_schema_valid():
    model = PropertyData(rent=45000, locality="Whitefield", city="Bangalore")
    assert model.rent == 45000
    assert model.locality == "Whitefield"

def test_17_pydantic_schema_missing_rent():
    with pytest.raises(ValidationError):
        PropertyData(locality="Whitefield")

def test_18_pydantic_schema_negative_rent():
    with pytest.raises(ValidationError):
        PropertyData(rent=-5000, locality="Whitefield")

def test_19_normalize_furnishing_semi():
    model = PropertyData(rent=10000, furnishing="semi-furnished")
    assert model.furnishing == "Semi-Furnished"

def test_20_normalize_furnishing_un():
    model = PropertyData(rent=10000, furnishing="UNFURNISHED")
    assert model.furnishing == "Unfurnished"

def test_21_normalize_furnishing_full():
    model = PropertyData(rent=10000, furnishing="fully-furnished")
    assert model.furnishing == "Furnished"

# ---------------------------------------------------------------------------
# Test Cases 22-25: slack_client security & headers
# ---------------------------------------------------------------------------

def test_22_header_case_insensitive():
    headers = {"Content-Type": "application/json", "X-Slack-Signature": "sig123"}
    assert header(headers, "content-type") == "application/json"
    assert header(headers, "x-slack-signature") == "sig123"

def test_23_verify_signature_valid():
    import hmac
    import hashlib
    signing_secret = "secret123"
    timestamp = "1700000000"
    body = "payload_body"
    base = f"v0:{timestamp}:{body}".encode()
    sig = "v0=" + hmac.new(signing_secret.encode(), base, hashlib.sha256).hexdigest()
    
    headers = {
        "X-Slack-Request-Timestamp": timestamp,
        "X-Slack-Signature": sig
    }
    assert verify_signature(headers, body, signing_secret, now=1700000100) is True

def test_24_verify_signature_invalid():
    headers = {
        "X-Slack-Request-Timestamp": "1700000000",
        "X-Slack-Signature": "v0=invalid_sig_value"
    }
    assert verify_signature(headers, "body", "secret", now=1700000100) is False

def test_25_verify_signature_stale():
    # If clock difference > 300s, verification should fail
    headers = {
        "X-Slack-Request-Timestamp": "1700000000",
        "X-Slack-Signature": "sig"
    }
    assert verify_signature(headers, "body", "secret", now=1700001000) is False

# ---------------------------------------------------------------------------
# Test Cases 26-29: routing.classify_message()
# ---------------------------------------------------------------------------

def test_26_classify_bot():
    event = {"bot_id": "B12345", "text": "Some text long enough to be an extract"}
    assert classify_message(event) == "IGNORE"

def test_27_classify_thread_reply():
    event = {"thread_ts": "1700000000.0001", "ts": "1700000100.0002", "text": " rent is 40000 "}
    assert classify_message(event) == "EDIT_OR_THREAD_REPLY"

def test_28_classify_new_extract():
    event = {"ts": "1700000000.0001", "text": "This is a new listing detailing a lovely 3bhk in Prestige Green Gables for rent."}
    assert classify_message(event) == "EXTRACT"

def test_29_classify_ignore_short():
    event = {"ts": "1700000000.0001", "text": "Short message."}
    assert classify_message(event) == "IGNORE"

# ---------------------------------------------------------------------------
# Test Cases 30-32: common.extract_and_validate()
# ---------------------------------------------------------------------------

def test_30_extract_and_validate_markdown_fence():
    raw_markdown = "```json\n{\"rent\": 35000, \"locality\": \"Indiranagar\"}\n```"
    result = extract_and_validate(raw_markdown)
    assert result["rent"] == 35000
    assert result["locality"] == "Indiranagar"

def test_31_extract_and_validate_missing_location():
    raw_json = '{"rent": 25000}'
    with pytest.raises(ProviderError) as exc:
        extract_and_validate(raw_json)
    assert "locality or city is required" in str(exc.value)

def test_32_extract_and_validate_valid_dict():
    raw_dict = {
        "rent": 60000,
        "locality": "HSR Layout",
        "bedrooms": 2,
        "furnishing": "semi-furnished"
    }
    result = extract_and_validate(raw_dict)
    assert result["rent"] == 60000
    assert result["locality"] == "HSR Layout"
    assert result["furnishing"] == "Semi-Furnished"
