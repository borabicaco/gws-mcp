"""Drive write operations: create new files and folders only.

Existing files are never modified: there is no update call anywhere, and the
``drive.file`` scope only lets this app write files it created itself.
"""

from __future__ import annotations

from typing import Any

from googleapiclient.http import MediaInMemoryUpload

from gws_mcp.services.drive import FOLDER_MIME, SHARED_DRIVES

GOOGLE_DOC_MIME = "application/vnd.google-apps.document"
RESULT_FIELDS = "id,name,mimeType,webViewLink,parents"


def _result(f: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": f.get("id"),
        "name": f.get("name"),
        "mime_type": f.get("mimeType"),
        "link": f.get("webViewLink"),
        "parents": f.get("parents", []),
    }


def create_folder(service: Any, name: str, parent_id: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"name": name, "mimeType": FOLDER_MIME}
    if parent_id:
        body["parents"] = [parent_id]
    created = service.files().create(body=body, fields=RESULT_FIELDS, **SHARED_DRIVES).execute()
    return _result(created)


def create_file(
    service: Any,
    name: str,
    content: str,
    mime_type: str = "text/plain",
    parent_id: str | None = None,
    as_google_doc: bool = False,
) -> dict[str, Any]:
    """Create a new file from text. A file with the same name is never overwritten."""
    body: dict[str, Any] = {"name": name}
    if parent_id:
        body["parents"] = [parent_id]
    if as_google_doc:
        body["mimeType"] = GOOGLE_DOC_MIME
    media = MediaInMemoryUpload(content.encode("utf-8"), mimetype=mime_type, resumable=False)
    created = (
        service.files()
        .create(body=body, media_body=media, fields=RESULT_FIELDS, **SHARED_DRIVES)
        .execute()
    )
    return _result(created)
