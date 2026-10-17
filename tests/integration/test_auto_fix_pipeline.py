"""Integration tests for the auto-fix pipeline using mocked AWS and Box."""
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def incident_state(tmp_path):
    """Create a local incident state file."""
    incidents_dir = tmp_path / "incidents"
    incidents_dir.mkdir()
    rec = {
        "incident_id": "INC-INT-001",
        "service": "checkout-api",
        "alarm_name": "pilotlight-checkout-5xx",
        "status": "resolved",
        "box_folder_id": "test-folder-123",
        "runbook_file_id": "",
    }
    (incidents_dir / "INC-INT-001.json").write_text(json.dumps(rec))
    return tmp_path


class TestAutoFixPipelineIntegration:
    """Test the full pipeline with mocked external services."""

    @patch("pilotlight.auto_fix.__main__.implement_task")
    @patch("pilotlight.auto_fix.__main__.extract_tasks")
    @patch("pilotlight.auto_fix.__main__._find_file_in_folder")
    @patch("pilotlight.auto_fix.__main__.box_tools")
    @patch("pilotlight.auto_fix.__main__.client")
    def test_pipeline_runs_end_to_end(self, mock_client, mock_box, mock_find,
                                       mock_extract, mock_implement, incident_state):
        # Setup: file finder returns postmortem and transcript
        mock_find.side_effect = lambda fid, name: {
            "postmortem.md": "pm-file-1",
            "transcript.md": "tr-file-1",
        }.get(name)

        # Setup: extract returns 2 tasks
        mock_extract.return_value = (
            [
                {"task_id": "TASK-001", "title": "Fix A", "type": "code_fix",
                 "description": "d", "priority": "P1", "root_cause_link": "r"},
                {"task_id": "TASK-002", "title": "Fix B", "type": "code_fix",
                 "description": "d", "priority": "P2", "root_cause_link": "r"},
            ],
            {"answer": "Root cause analysis", "citations": []},
        )

        # Setup: implement returns PR URLs
        mock_implement.side_effect = [
            "https://github.com/org/repo/pull/10",
            "https://github.com/org/repo/pull/11",
        ]
        mock_box.upload_text.return_value = "summary-file-id"

        # Patch STATE_DIR to use our temp directory
        with patch("pilotlight.auto_fix.__main__.STATE_DIR", str(incident_state)):
            from pilotlight.auto_fix.__main__ import run
            urls = run("INC-INT-001")

        assert len(urls) == 2
        assert "pull/10" in urls[0]
        assert "pull/11" in urls[1]
        mock_extract.assert_called_once()
        assert mock_implement.call_count == 2
        mock_box.create_review_task.assert_called_once()

    @patch("pilotlight.auto_fix.__main__._find_file_in_folder")
    @patch("pilotlight.auto_fix.__main__.box_tools")
    @patch("pilotlight.auto_fix.__main__.client")
    def test_pipeline_stops_without_postmortem(self, mock_client, mock_box,
                                                mock_find, incident_state):
        mock_find.return_value = None  # No postmortem found

        with patch("pilotlight.auto_fix.__main__.STATE_DIR", str(incident_state)):
            from pilotlight.auto_fix.__main__ import run
            urls = run("INC-INT-001")

        assert urls == []

    def test_pipeline_stops_for_missing_incident(self, incident_state):
        with patch("pilotlight.auto_fix.__main__.STATE_DIR", str(incident_state)):
            from pilotlight.auto_fix.__main__ import run
            urls = run("INC-DOES-NOT-EXIST")

        assert urls == []
