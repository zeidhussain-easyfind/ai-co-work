import logging

logger = logging.getLogger("meta_catalog")
logger.setLevel(logging.INFO)

def log_event(event_name: str, **kwargs: any) -> None:
    parts = [f"[{k}] {v}" for k, v in kwargs.items()]
    logger.info("[event:%s] %s", event_name, " | ".join(parts))
