"""Helpers for storing media files and exposing them via public links."""

from __future__ import annotations

from pathlib import Path
from typing import Union

from config import PUBLIC_MEDIA_ROOT, PUBLIC_MEDIA_URL

PathLike = Union[str, Path]

_PUBLIC_ROOT_PATH = Path(PUBLIC_MEDIA_ROOT).resolve()
_PUBLIC_ROOT_PATH.mkdir(parents=True, exist_ok=True)


def ensure_within_public_root(path: PathLike) -> Path:
    """Return the absolute path and ensure it resides inside the public root.

    Args:
        path: Absolute or relative filesystem path.

    Returns:
        Path relative to the public root.

    Raises:
        ValueError: If the target path is outside of the configured public root.
    """

    absolute = Path(path).resolve()
    try:
        relative = absolute.relative_to(_PUBLIC_ROOT_PATH)
    except ValueError as exc:  # pragma: no cover - safety net for misconfiguration
        raise ValueError(
            f"Path {absolute} is outside of the public media root {_PUBLIC_ROOT_PATH}"
        ) from exc
    return relative


def build_public_url(path: PathLike) -> str:
    """Convert a filesystem path inside the public root into an HTTP URL."""

    relative = ensure_within_public_root(path)
    base = PUBLIC_MEDIA_URL.rstrip("/")
    return f"{base}/{relative.as_posix()}"


def public_root() -> Path:
    """Expose the resolved public root for callers that need filesystem access."""

    return _PUBLIC_ROOT_PATH

