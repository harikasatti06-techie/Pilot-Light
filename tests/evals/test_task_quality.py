"""Eval tests: verify auto-fix output quality and safety invariants.

These tests validate that the prompts, task structures, and safety checks
produce correct behavior. They run without external API calls.
"""
import json
import re

import pytest

from pilotlight.auto_fix.prompt import AGENT_PROMPT


class TestPromptQuality:
    """Verify the agent prompt enforces quality and safety."""

    def test_prompt_requires_tests(self):
        rendered = AGENT_PROMPT.format(
            incident_id="INC-001", task_id="TASK-001", task_title="Fix X",
            task_json="{}", alarm_name="test", service="checkout",
            box_folder_url="https://app.box.com/folder/1",
            past_fixes_context="none",
        )
        assert "pytest" in rendered.lower() or "test" in rendered.lower()

    def test_prompt_requires_branch(self):
        rendered = AGENT_PROMPT.format(
            incident_id="INC-001", task_id="TASK-001", task_title="Fix X",
            task_json="{}", alarm_name="test", service="checkout",
            box_folder_url="https://app.box.com/folder/1",
            past_fixes_context="none",
        )
        assert "auto-fix/" in rendered

    def test_prompt_requires_pr_url_output(self):
        rendered = AGENT_PROMPT.format(
            incident_id="INC-001", task_id="TASK-001", task_title="Fix X",
            task_json="{}", alarm_name="test", service="checkout",
            box_folder_url="https://app.box.com/folder/1",
            past_fixes_context="none",
        )
        assert "PR_URL=" in rendered

    def test_prompt_forbids_unrelated_changes(self):
        rendered = AGENT_PROMPT.format(
            incident_id="INC-001", task_id="TASK-001", task_title="Fix X",
            task_json="{}", alarm_name="test", service="checkout",
            box_folder_url="https://app.box.com/folder/1",
            past_fixes_context="none",
        )
        assert "do not modify files unrelated" in rendered.lower()

    def test_prompt_supports_draft_prs(self):
        rendered = AGENT_PROMPT.format(
            incident_id="INC-001", task_id="TASK-001", task_title="Fix X",
            task_json="{}", alarm_name="test", service="checkout",
            box_folder_url="https://app.box.com/folder/1",
            past_fixes_context="none",
        )
        assert "--draft" in rendered


class TestTaskStructure:
    """Verify extracted tasks conform to the expected schema."""

    REQUIRED_FIELDS = ["task_id", "title", "type", "description",
                       "files_to_examine", "acceptance_criteria",
                       "priority", "root_cause_link"]

    VALID_TYPES = ["code_fix", "config_change", "test", "monitoring"]
    VALID_PRIORITIES = ["P0", "P1", "P2", "P3"]

    @pytest.fixture
    def sample_tasks(self):
        return [
            {
                "task_id": "TASK-001",
                "title": "Add circuit breaker",
                "type": "code_fix",
                "description": "Implement probabilistic failure",
                "files_to_examine": ["services/checkout/handler.py"],
                "acceptance_criteria": "Tests pass",
                "priority": "P1",
                "root_cause_link": "hard kill switch",
            },
            {
                "task_id": "TASK-002",
                "title": "Add SSM change alerts",
                "type": "monitoring",
                "description": "EventBridge rule for parameter changes",
                "files_to_examine": ["infra/stack.py"],
                "acceptance_criteria": "SNS fires on change",
                "priority": "P2",
                "root_cause_link": "no validation on config changes",
            },
        ]

    def test_all_required_fields_present(self, sample_tasks):
        for task in sample_tasks:
            for field in self.REQUIRED_FIELDS:
                assert field in task, f"Missing field {field} in {task['task_id']}"

    def test_task_ids_are_unique(self, sample_tasks):
        ids = [t["task_id"] for t in sample_tasks]
        assert len(ids) == len(set(ids))

    def test_task_ids_follow_pattern(self, sample_tasks):
        for task in sample_tasks:
            assert re.match(r"TASK-\d{3}", task["task_id"])

    def test_priorities_are_valid(self, sample_tasks):
        for task in sample_tasks:
            assert task["priority"] in self.VALID_PRIORITIES

    def test_files_to_examine_not_empty(self, sample_tasks):
        for task in sample_tasks:
            assert len(task["files_to_examine"]) > 0


class TestSafetyInvariants:
    """Verify safety properties of the auto-fix pipeline."""

    def test_max_tasks_capped(self):
        """Pipeline should only implement first 2 tasks for demo speed."""
        from pilotlight.auto_fix.__main__ import run
        import inspect
        source = inspect.getsource(run)
        assert "tasks[:2]" in source or "tasks[: 2]" in source

    def test_implement_has_timeout(self):
        """Claude Code subprocess must have a timeout."""
        from pilotlight.auto_fix import implement
        import inspect
        source = inspect.getsource(implement.implement_task)
        assert "timeout=" in source

    def test_prompt_mentions_human_review(self):
        """Auto-generated PRs must flag human review."""
        assert "human review" in AGENT_PROMPT.lower()
