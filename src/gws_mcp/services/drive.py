"""Read-only Google Drive operations. ``service`` is a Drive v3 resource."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from googleapiclient.http import MediaIoBaseDownload

from gws_mcp.services import save_download

MAX_RESULTS_CAP = 100
FILE_FIELDS = (
    "id,name,mimeType,size,createdTime,modifiedTime,webViewLink,parents,shared,"
    "owners(displayName,emailAddress),lastModifyingUser(displayName,emailAddress)"
)
LIST_FIELDS = f"nextPageToken,files({FILE_FIELDS})"
SHARED_DRIVES = {"supportsAllDrives": True}
LIST_SHARED_DRIVES = {"supportsAllDrives": True, "includeItemsFromAllDrives": True}

FOLDER_MIME = "application/vnd.google-apps.folder"
# Google-native formats and the text format they are exported to.
EXPORT_FORMATS = {
    "application/vnd.google-apps.document": ("text/plain", ".txt"),
    "application/vnd.google-apps.spreadsheet": ("text/csv", ".csv"),  # first sheet only
    "application/vnd.google-apps.presentation": ("text/plain", ".txt"),
}
TEXT_LIKE = ("text/", "application/json", "application/xml", "application/csv")


class DriveError(Exception):
    """An anticipated Drive failure with a message safe to show the user."""


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _file_summary(f: dict[str, Any]) -> dict[str, Any]:
    owners = f.get("owners") or []
    return {
        "id": f["id"],
        "name": f.get("name"),
        "mime_type": f.get("mimeType"),
        "size": int(f["size"]) if f.get("size") else None,
        "modified": f.get("modifiedTime"),
        "owner": owners[0].get("emailAddress") if owners else None,
        "link": f.get("webViewLink"),
    }


def search_files(
    service: Any,
    text: str | None = None,
    raw_query: str | None = None,
    max_results: int = 25,
    page_token: str | None = None,
) -> dict[str, Any]:
    """Full-text search (``text``) and/or a Drive query (``raw_query``).

    Example raw_query: "name contains 'budget'".
    """
    clauses = ["trashed = false"]
    if text:
        clauses.append(f"fullText contains '{_escape(text)}'")
    if raw_query:
        clauses.append(f"({raw_query})")
    listing = (
        service.files()
        .list(
            q=" and ".join(clauses),
            pageSize=max(1, min(max_results, MAX_RESULTS_CAP)),
            pageToken=page_token,
            fields=LIST_FIELDS,
            **LIST_SHARED_DRIVES,
        )
        .execute()
    )
    return {
        "files": [_file_summary(f) for f in listing.get("files", [])],
        "next_page_token": listing.get("nextPageToken"),
    }


def recent_files(service: Any, max_results: int = 25) -> list[dict[str, Any]]:
    listing = (
        service.files()
        .list(
            q="trashed = false",
            orderBy="modifiedTime desc",
            pageSize=max(1, min(max_results, MAX_RESULTS_CAP)),
            fields=LIST_FIELDS,
            **LIST_SHARED_DRIVES,
        )
        .execute()
    )
    return [_file_summary(f) for f in listing.get("files", [])]


def get_metadata(service: Any, file_id: str) -> dict[str, Any]:
    f = service.files().get(fileId=file_id, fields=FILE_FIELDS, **SHARED_DRIVES).execute()
    result = _file_summary(f)
    result.update(
        {
            "created": f.get("createdTime"),
            "parents": f.get("parents", []),
            "shared": f.get("shared"),
            "owners": [o.get("emailAddress") for o in f.get("owners") or []],
            "last_modified_by": (f.get("lastModifyingUser") or {}).get("emailAddress"),
        }
    )
    return result


def _download_media(service: Any, file_id: str) -> bytes:
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(
        buffer, service.files().get_media(fileId=file_id, **SHARED_DRIVES)
    )
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buffer.getvalue()


def read_file(
    service: Any, file_id: str, downloads_dir: Path, max_inline_bytes: int
) -> dict[str, Any]:
    """Docs/Sheets/Slides are exported as text; other files are downloaded.

    Text content up to ``max_inline_bytes`` is returned inline. Everything else
    (PDF, images, Office files, ...) is saved to ``downloads_dir`` only.
    """
    meta = service.files().get(fileId=file_id, fields="id,name,mimeType,size", **SHARED_DRIVES)
    meta = meta.execute()
    name, mime_type = meta.get("name") or file_id, meta.get("mimeType") or ""
    result: dict[str, Any] = {"id": file_id, "name": name, "mime_type": mime_type}

    if mime_type == FOLDER_MIME:
        raise DriveError(f"'{name}' is a folder; use drive_search with \"'{file_id}' in parents\"")
    if mime_type in EXPORT_FORMATS:
        export_mime, suffix = EXPORT_FORMATS[mime_type]
        data = service.files().export(fileId=file_id, mimeType=export_mime).execute()
        result["exported_as"] = export_mime
        if mime_type.endswith("spreadsheet"):
            result["note"] = "Only the first sheet is included in CSV export."
        filename = name if name.endswith(suffix) else name + suffix
        text_like = True
    elif mime_type.startswith("application/vnd.google-apps."):
        raise DriveError(f"Google file type {mime_type} cannot be exported as text")
    else:
        data = _download_media(service, file_id)
        filename = name
        text_like = mime_type.startswith(TEXT_LIKE)

    result["size"] = len(data)
    if text_like and len(data) <= max_inline_bytes:
        result["text"] = data.decode("utf-8", errors="replace")
    else:
        result["saved_to"] = str(save_download(downloads_dir, filename, data))
        if text_like:
            result["note"] = f"Content larger than {max_inline_bytes} bytes; saved to disk."
    return result
