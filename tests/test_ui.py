"""Unit tests for UI logic and formatting in herdr-agent-prompt."""

import base64
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from extractor import PromptItem, AgentSession
from ui import PromptViewer, copy_to_clipboard, format_path


class TestUiHelpers(unittest.TestCase):
    def test_format_path_replaces_home(self):
        home = str(Path.home())
        self.assertEqual(format_path(f"{home}/Developer/myrepo"), "~/Developer/myrepo")
        self.assertEqual(format_path("/etc/hosts"), "/etc/hosts")

    def test_copy_to_clipboard_osc52(self):
        captured_stdout = io.StringIO()
        with patch("sys.stdout", captured_stdout):
            res = copy_to_clipboard("Hello, world!")
            self.assertTrue(res)
            output = captured_stdout.getvalue()
            # Verify OSC 52 format \033]52;c;<base64>\a
            self.assertTrue(output.startswith("\033]52;c;"))
            self.assertTrue(output.endswith("\a"))
            encoded = output[len("\033]52;c;"):-1]
            decoded = base64.b64decode(encoded).decode("utf-8")
            self.assertEqual(decoded, "Hello, world!")


class TestPromptViewerLogic(unittest.TestCase):
    def test_wrap_current_prompt(self):
        viewer = PromptViewer.__new__(PromptViewer)
        viewer.target_pane_id = "test:p1"
        viewer.active_turn_idx = 0
        viewer.scroll_offset = 0
        viewer.status_message = ""
        viewer.status_is_error = False

        viewer.session = AgentSession(
            pane_id="test:p1",
            agent_kind="agy",
            agent_name="tester",
            session_id="s123",
            cwd="/home/jeff",
            status="idle",
            prompts=[
                PromptItem(
                    turn=1,
                    total_turns=2,
                    text="This is a long line that needs to wrap properly into multiple terminal lines without cutting words in half.\n\nSecond paragraph here.",
                    is_original=True,
                ),
                PromptItem(
                    turn=2,
                    total_turns=2,
                    text="Turn 2 text.",
                    is_original=False,
                ),
            ],
        )

        viewer.wrap_current_prompt(max_width=40)
        self.assertTrue(len(viewer.wrapped_lines) > 2)
        # Check blank line preserved
        self.assertIn("", viewer.wrapped_lines)
        # Verify word boundary wrapping
        for line in viewer.wrapped_lines:
            self.assertLessEqual(len(line), 40)

        # Switch to turn 2
        viewer.active_turn_idx = 1
        viewer.wrap_current_prompt(max_width=40)
        self.assertEqual(viewer.wrapped_lines, ["Turn 2 text."])


if __name__ == "__main__":
    unittest.main()
