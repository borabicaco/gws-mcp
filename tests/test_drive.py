from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from gws_mcp.services import drive


@pytest.fixture
def service():
    return MagicMock()


def set_meta(service, mime_type, name="File"):
    service.files.return_value.get.return_value.execute.return_value = {
        "id": "f1",
        "name": name,
        "mimeType": mime_type,
    }


def test_search_builds_query_with_escaping(service):
    service.files.return_value.list.return_value.execute.return_value = {"files": []}
    drive.search_files(service, text="Bora's plan", raw_query="mimeType = 'application/pdf'")
    kwargs = service.files.return_value.list.call_args.kwargs
    assert kwargs["q"] == (
        "trashed = false and fullText contains 'Bora\\'s plan' and (mimeType = 'application/pdf')"
    )
    assert kwargs["includeItemsFromAllDrives"] is True and kwargs["supportsAllDrives"] is True


def test_recent_files_ordering_and_mapping(service):
    service.files.return_value.list.return_value.execute.return_value = {
        "files": [
            {
                "id": "f1",
                "name": "a.pdf",
                "mimeType": "application/pdf",
                "size": "42",
                "owners": [{"emailAddress": "me@x.com"}],
            },
        ]
    }
    result = drive.recent_files(service, max_results=1000)
    kwargs = service.files.return_value.list.call_args.kwargs
    assert kwargs["orderBy"] == "modifiedTime desc" and kwargs["pageSize"] == 100
    assert result == [
        {
            "id": "f1",
            "name": "a.pdf",
            "mime_type": "application/pdf",
            "size": 42,
            "modified": None,
            "owner": "me@x.com",
            "link": None,
        }
    ]


def test_read_google_doc_exports_text_inline(service, tmp_path):
    set_meta(service, "application/vnd.google-apps.document", "Notes")
    service.files.return_value.export.return_value.execute.return_value = b"Merhaba"
    result = drive.read_file(service, "f1", tmp_path, max_inline_bytes=1000)
    service.files.return_value.export.assert_called_once_with(fileId="f1", mimeType="text/plain")
    assert result["text"] == "Merhaba" and "saved_to" not in result


def test_read_sheet_exports_csv_with_note(service, tmp_path):
    set_meta(service, "application/vnd.google-apps.spreadsheet")
    service.files.return_value.export.return_value.execute.return_value = b"a,b\n1,2"
    result = drive.read_file(service, "f1", tmp_path, max_inline_bytes=1000)
    assert result["exported_as"] == "text/csv" and "first sheet" in result["note"]


def test_read_large_export_is_saved_to_disk(service, tmp_path):
    set_meta(service, "application/vnd.google-apps.document", "Big")
    service.files.return_value.export.return_value.execute.return_value = b"x" * 50
    result = drive.read_file(service, "f1", tmp_path, max_inline_bytes=10)
    assert "text" not in result and result["saved_to"].endswith("Big.txt")


def test_read_pdf_is_downloaded_not_inlined(service, tmp_path):
    set_meta(service, "application/pdf", "invoice.pdf")
    with patch.object(drive, "_download_media", return_value=b"%PDF-1.7"):
        result = drive.read_file(service, "f1", tmp_path, max_inline_bytes=1000)
    assert "text" not in result
    assert (tmp_path / "invoice.pdf").read_bytes() == b"%PDF-1.7"


def test_read_folder_is_an_error(service, tmp_path):
    set_meta(service, drive.FOLDER_MIME, "Projects")
    with pytest.raises(drive.DriveError, match="is a folder"):
        drive.read_file(service, "f1", tmp_path, max_inline_bytes=1000)


def test_downloaded_filename_cannot_escape_folder(service, tmp_path):
    set_meta(service, "text/plain", "../../etc/passwd")
    with patch.object(drive, "_download_media", return_value=b"x" * 20):
        result = drive.read_file(service, "f1", tmp_path / "dl", max_inline_bytes=1)
    assert result["saved_to"] == str(tmp_path / "dl" / "passwd")
