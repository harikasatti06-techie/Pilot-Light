"""Unit tests for the auto-fix implementation step."""
from unittest.mock import MagicMock, patch, call

from pilotlight.auto_fix.implement import _find_pr_url, implement_task


class TestFindPrUrl:
    def test_finds_pr_url_marker(self):
        output = "Some output\nPR_URL=https://github.com/org/repo/pull/42\nDone"
        assert _find_pr_url(output) == "https://github.com/org/repo/pull/42"

    def test_finds_github_url_fallback(self):
        output = "Created https://github.com/org/repo/pull/7 successfully"
        assert _find_pr_url(output) == "https://github.com/org/repo/pull/7"

    def test_returns_none_when_no_url(self):
        assert _find_pr_url("no urls here") is None

    def test_returns_none_on_empty(self):
        assert _find_pr_url("") is None


class TestImplementTask:
    @patch("pilotlight.auto_fix.implement.box_tools")
    @patch("pilotlight.auto_fix.implement.subprocess.run")
    @patch("pilotlight.auto_fix.implement._run")
    def test_creates_branch_and_runs_claude(self, mock_git, mock_subprocess, mock_box, tmp_path):
        mock_subprocess.return_value = MagicMock(
            returncode=0,
            stdout="PR_URL=https://github.com/org/repo/pull/99\n",
            stderr="",
        )
        mock_box.upload_text.return_value = "file1"

        task = {
            "task_id": "TASK-001",
            "title": "Add circuit breaker",
            "type": "code_fix",
            "description": "desc",
            "alarm_name": "test-alarm",
        }
        url = implement_task("INC-001", task, str(tmp_path), "folder1")
        assert url == "https://github.com/org/repo/pull/99"

        # Verify git branch creation calls
        git_calls = [c[0][0] for c in mock_git.call_args_list]
        assert ["git", "checkout", "main"] in git_calls
        assert ["git", "checkout", "-b", "auto-fix/inc-001/task-001"] in git_calls

    @patch("pilotlight.auto_fix.implement.box_tools")
    @patch("pilotlight.auto_fix.implement.subprocess.run")
    @patch("pilotlight.auto_fix.implement._run")
    def test_returns_none_on_no_pr(self, mock_git, mock_subprocess, mock_box, tmp_path):
        mock_subprocess.return_value = MagicMock(
            returncode=1,
            stdout="Error occurred",
            stderr="",
        )
        task = {"task_id": "TASK-002", "title": "Fix thing", "type": "code_fix",
                "description": "d", "alarm_name": "a"}
        url = implement_task("INC-001", task, str(tmp_path), "folder1")
        assert url is None
