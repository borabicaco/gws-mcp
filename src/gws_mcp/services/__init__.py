"""Google API logic, independent of MCP. Shared helpers for saving downloads."""

from __future__ import annotations

import re
from pathlib import Path

_UNSAFE_CHARS = re.compile(r"[^\w.\- ()\[\]]+", re.UNICODE)


def safe_filename(name: str, fallback: str = "download") -> str:
    """Strip path components and unsafe characters from a remote file name."""
    name = name.replace("\\", "/").split("/")[-1]
    name = _UNSAFE_CHARS.sub("_", name).strip(" .")
    return name[:200] or fallback


def save_download(directory: Path, filename: str, data: bytes) -> Path:
    """Save ``data`` under ``directory`` without ever overwriting an existing file."""
    directory.mkdir(parents=True, exist_ok=True)
    base = safe_filename(filename)
    stem, dot, suffix = base.rpartition(".")
    if not dot:
        stem, suffix = base, ""
    candidate = directory / base
    counter = 1
    while True:
        try:
            # "x" mode fails if the file exists, so nothing is ever overwritten.
            with candidate.open("xb") as fh:
                fh.write(data)
            return candidate
        except FileExistsError:
            counter += 1
            candidate = directory / (
                f"{stem} ({counter}).{suffix}" if suffix else f"{stem} ({counter})"
            )


def truncate(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars], True
