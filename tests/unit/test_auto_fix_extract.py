"""Unit tests for the auto-fix task extraction pipeline."""
import json
from unittest.mock import MagicMock, patch

from pilotlight.auto_fix.extract import _bedrock_extract, extract_tasks


class TestBedrockExtract:
    """Verify Bedrock response is parsed into structured tasks."""

    @patch("pilotlight.auto_fix.extract.br")
    def test_extracts_tasks_from_bedrock(self, mock_br):
        tasks = [{"task_id": "TASK-001", "title": "Add circuit breaker", "type": "code_fix",
                  "description": "desc", "files_to_examine": ["handler.py"],
                  "acceptance_criteria": "test passes", "priority": "P1",
                  "root_cause_link": "hard kill switch"}]
        mock_br.converse.return_value = {
            "output": {"message": {"content": [{"text": json.dumps({"tasks": tasks})}]}}
        }
        result = _bedrock_extract("postmortem", "transcript", "analysis")
        assert len(result) == 1
        assert result[0]["task_id"] == "TASK-001"
        assert result[0]["title"] == "Add circuit breaker"

    @patch("pilotlight.auto_fix.extract.br")
    def test_strips_markdown_fences(self, mock_br):
        tasks = [{"task_id": "T1", "title": "Fix", "type": "code_fix",
                  "description": "d", "files_to_examine": [], "acceptance_criteria": "a",
                  "priority": "P1", "root_cause_link": "r"}]
        fenced = f"```json\n{json.dumps({'tasks': tasks})}\n```"
        mock_br.converse.return_value = {
            "output": {"message": {"content": [{"text": fenced}]}}
        }
        result = _bedrock_extract("p", "t", "a")
        assert len(result) == 1


class TestExtractTasks:
    """Integration of Box AI + Bedrock extraction."""

    @patch("pilotlight.auto_fix.extract._bedrock_extract")
    @patch("pilotlight.auto_fix.extract.client")
    @patch("pilotlight.auto_fix.extract._box_ai_analyze")
    @patch("pilotlight.auto_fix.extract._find_past_incidents", return_value=[])
    def test_full_pipeline(self, mock_past, mock_ai, mock_client, mock_bedrock):
        mock_ai.return_value = {"answer": "Root cause is X", "citations": []}
        mock_client().downloads.download_file.return_value = MagicMock(
            read=lambda: b"postmortem text"
        )
        mock_bedrock.return_value = [
            {"task_id": "TASK-001", "title": "Fix X"}
        ]

        tasks, analysis = extract_tasks(
            incident_id="INC-001",
            postmortem_file_id="pm1",
            transcript_file_id="tr1",
            runbook_file_id=None,
            alarm_name="test-alarm",
        )
        assert len(tasks) == 1
        assert analysis["answer"] == "Root cause is X"
        mock_ai.assert_called_once()
        mock_bedrock.assert_called_once()
