"""Unit tests for Box tools: folder creation, uploads, review tasks."""
import io
from unittest.mock import MagicMock, patch

from pilotlight import box_tools


def _make_box_409(conflict_id: str):
    """Create a BoxAPIError that looks like a 409 conflict."""
    from box_sdk_gen.box.errors import BoxAPIError, RequestInfo, ResponseInfo
    req = RequestInfo(method="POST", url="https://api.box.com/test", query_params={}, headers={}, body="")
    resp = ResponseInfo(status_code=409, headers={}, body={},
                        raw_body="", code="conflict", context_info={"conflicts": {"id": conflict_id}},
                        request_id="", help_url="")
    return BoxAPIError(request_info=req, response_info=resp, message="conflict")


@patch("pilotlight.box_tools.client")
@patch("pilotlight.box_tools.timeline")
class TestCreateIncidentFolder:
    def test_creates_folder(self, mock_tl, mock_client):
        mock_client().folders.create_folder.return_value = MagicMock(id="999")
        fid = box_tools.create_incident_folder("INC-001")
        assert fid == "999"
        mock_tl.add.assert_called_once()

    def test_returns_existing_on_409(self, mock_tl, mock_client):
        err = _make_box_409("888")
        mock_client().folders.create_folder.side_effect = err
        fid = box_tools.create_incident_folder("INC-001")
        assert fid == "888"


@patch("pilotlight.box_tools.client")
class TestUploadText:
    def test_uploads_new_file(self, mock_client):
        mock_entry = MagicMock(id="123")
        mock_client().uploads.upload_file.return_value = MagicMock(entries=[mock_entry])
        fid = box_tools.upload_text("folder1", "test.md", "hello")
        assert fid == "123"

    def test_versions_on_conflict(self, mock_client):
        err = _make_box_409("456")
        mock_client().uploads.upload_file.side_effect = err
        mock_entry = MagicMock(id="456")
        mock_client().uploads.upload_file_version.return_value = MagicMock(entries=[mock_entry])
        fid = box_tools.upload_text("folder1", "test.md", "updated")
        assert fid == "456"
        mock_client().uploads.upload_file_version.assert_called_once()


@patch("pilotlight.box_tools.client")
class TestCreateReviewTask:
    def test_creates_task_and_assigns(self, mock_client):
        mock_task = MagicMock(id="t1")
        mock_client().tasks.create_task.return_value = mock_task
        with patch.object(box_tools, "BOX_REVIEWER_LOGIN", "reviewer@test.com"):
            box_tools.create_review_task("file1", "Review this")
        mock_client().task_assignments.create_task_assignment.assert_called_once()
