"""Unit tests for plugin CLI commands."""

import io
import json
import sys
import unittest
from unittest.mock import patch

from extractor import AgentSession, PromptItem
from plugin import cmd_get, cmd_list


class TestCliCommands(unittest.TestCase):
    def setUp(self):
        self.mock_session = AgentSession(
            pane_id="w1:p1",
            agent_kind="agy",
            agent_name="mock-agy",
            session_id="mock-123",
            cwd="/home/jeff/Developer/test",
            status="idle",
            prompts=[
                PromptItem(turn=1, total_turns=2, text="Original mock prompt", is_original=True),
                PromptItem(turn=2, total_turns=2, text="Second turn prompt", is_original=False),
            ],
        )

    def test_cmd_get_text(self):
        with patch("plugin.get_session_for_pane", return_value=self.mock_session):
            captured = io.StringIO()
            with patch("sys.stdout", captured):
                cmd_get(pane_id="w1:p1", as_json=False, turn=1)
            self.assertEqual(captured.getvalue().strip(), "Original mock prompt")

            captured2 = io.StringIO()
            with patch("sys.stdout", captured2):
                cmd_get(pane_id="w1:p1", as_json=False, turn=2)
            self.assertEqual(captured2.getvalue().strip(), "Second turn prompt")

    def test_cmd_get_json(self):
        with patch("plugin.get_session_for_pane", return_value=self.mock_session):
            captured = io.StringIO()
            with patch("sys.stdout", captured):
                cmd_get(pane_id="w1:p1", as_json=True, turn=1)
            data = json.loads(captured.getvalue())
            self.assertEqual(data["agent_kind"], "agy")
            self.assertEqual(data["pane_id"], "w1:p1")
            self.assertEqual(len(data["prompts"]), 2)
            self.assertEqual(data["prompts"][0]["text"], "Original mock prompt")

    def test_cmd_list_text(self):
        with patch("plugin.list_all_agent_sessions", return_value=[self.mock_session]):
            captured = io.StringIO()
            with patch("sys.stdout", captured):
                cmd_list(as_json=False)
            val = captured.getvalue()
            self.assertIn("w1:p1", val)
            self.assertIn("mock-agy", val)
            self.assertIn("Original mock prompt", val)


if __name__ == "__main__":
    unittest.main()
