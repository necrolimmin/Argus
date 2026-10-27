import uuid
from datetime import datetime
from pathlib import Path

from app.config import get_settings


def media_root() -> Path:
    return get_settings().media_dir


def save_bytes(folder: str, data: bytes, when: datetime | None = None, ext: str = "jpg") -> str:
    """Store a file under media_dir and return its relative path.

    Event files go in per-day folders so retention can drop a whole day.
    """
    sub = f"{folder}/{when:%Y-%m-%d}" if when else folder
    rel = f"{sub}/{uuid.uuid4().hex}.{ext}"
    target = media_root() / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return rel


def read_bytes(rel: str) -> bytes:
    return (media_root() / rel).read_bytes()


def delete_file(rel: str) -> None:
    if rel:
        (media_root() / rel).unlink(missing_ok=True)
