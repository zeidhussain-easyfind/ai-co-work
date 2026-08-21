from __future__ import annotations

from typing import Any


def publish_with_browser(property_id: str, property_data: dict[str, Any]) -> dict[str, Any]:
    """Explicitly disabled until a separately hosted worker is approved."""
    del property_id, property_data
    return {
        "success": False,
        "error": (
            "Browser publishing is disabled. Complete the listing manually or "
            "enable it only after selector, session, and terms verification."
        ),
    }
