"""Resolve app metadata outside Photos, while recognizing older library layouts."""
import os
from pathlib import Path


def metadata_path(photos):
    sibling = photos.parent / ".pi-photos"
    fallback = sibling if sibling.is_dir() else photos / ".pi-photos"
    return Path(os.environ.get("PHOTO_META", fallback)).resolve()
