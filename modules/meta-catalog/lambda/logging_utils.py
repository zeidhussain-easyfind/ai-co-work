import logging
import sys

logging.basicConfig(stream=sys.stdout, level=logging.INFO)
logger = logging.getLogger("meta_catalog")
logger.setLevel(logging.INFO)

def log_event(event_name: str, **kwargs: any) -> None:
    parts = [f"[{k}] {v}" for k, v in kwargs.items()]
    msg = f"[event:{event_name}] " + " | ".join(parts)
    print(msg)
