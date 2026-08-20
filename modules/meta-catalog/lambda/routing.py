from typing import Any

def classify_message(event: dict[str, Any]) -> str:
    if event.get("bot_id"):
        return "IGNORE"
    
    subtype = event.get("subtype")
    if subtype and subtype != "file_share":
        return "IGNORE"
        
    thread_ts = event.get("thread_ts")
    if thread_ts and thread_ts != event.get("ts"):
        return "EDIT_OR_THREAD_REPLY"
    if len((event.get("text") or "").strip()) >= 30:
        return "EXTRACT"
    return "IGNORE"
