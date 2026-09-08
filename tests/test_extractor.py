"""Unit tests for agent prompt extractor."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from extractor import (
    AgentSession,
    PromptItem,
    clean_xml_tags,
    extract_agy_prompts,
    extract_claude_prompts,
    extract_codex_prompts,
    extract_pi_prompts,
    resolve_session_prompts,
)


class TestXmlCleaning(unittest.TestCase):
    def test_clean_user_request_wrapper(self):
        raw = "<USER_REQUEST>\nFix the database connection leak\n</USER_REQUEST>\n<ADDITIONAL_METADATA>\ntime: 1234\n</ADDITIONAL_METADATA>"
        cleaned = clean_xml_tags(raw)
        self.assertEqual(cleaned, "Fix the database connection leak")

    def test_clean_caveats(self):
        raw = "<local-command-caveat>resumed</local-command-caveat>\nDo some refactoring."
        cleaned = clean_xml_tags(raw)
        self.assertEqual(cleaned, "Do some refactoring.")


class TestAgyExtraction(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.brain_dir = Path(self.temp_dir.name)
        os.environ["AGY_BRAIN_DIR"] = str(self.brain_dir)

    def tearDown(self):
        self.temp_dir.cleanup()
        os.environ.pop("AGY_BRAIN_DIR", None)

    def test_extract_agy_single_and_multi_turn(self):
        sid = "test-session-123"
        session_folder = self.brain_dir / sid / ".system_generated/logs"
        session_folder.mkdir(parents=True)
        t_file = session_folder / "transcript.jsonl"

        lines = [
            {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "created_at": "2026-09-01T10:00:00Z", "content": "<USER_REQUEST>\nFirst task prompt\n</USER_REQUEST>"},
            {"step_index": 1, "source": "MODEL", "type": "PLANNER_RESPONSE", "content": "Working..."},
            {"step_index": 2, "source": "USER_EXPLICIT", "type": "USER_INPUT", "created_at": "2026-09-01T10:05:00Z", "content": "<USER_REQUEST>\nSecond followup prompt\n</USER_REQUEST>"},
        ]
        with open(t_file, "w") as f:
            for item in lines:
                f.write(json.dumps(item) + "\n")

        prompts, src = extract_agy_prompts(sid)
        self.assertEqual(len(prompts), 2)
        self.assertTrue(prompts[0].is_original)
        self.assertEqual(prompts[0].turn, 1)
        self.assertEqual(prompts[0].text, "First task prompt")
        self.assertFalse(prompts[1].is_original)
        self.assertEqual(prompts[1].turn, 2)
        self.assertEqual(prompts[1].text, "Second followup prompt")
        self.assertEqual(src, str(t_file))


class TestClaudeExtraction(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.claude_dir = Path(self.temp_dir.name)
        os.environ["CLAUDE_CONFIG_DIR"] = str(self.claude_dir)

    def tearDown(self):
        self.temp_dir.cleanup()
        os.environ.pop("CLAUDE_CONFIG_DIR", None)

    def test_extract_claude_slash_command(self):
        sid = "claude-test-456"
        cwd = "/home/jeff/Developer/myrepo"
        slug = "-home-jeff-Developer-myrepo"
        proj_dir = self.claude_dir / "projects" / slug
        proj_dir.mkdir(parents=True)
        t_file = proj_dir / f"{sid}.jsonl"

        lines = [
            {"type": "user", "timestamp": "2026-09-01T11:00:00Z", "message": "<command-name>/goal</command-name>\n<command-args>Implement user authentication with JWT</command-args>"},
            {"type": "user", "message": "<local-command-stdout>Goal set</local-command-stdout>"},
            {"type": "user", "message": "A session-scoped Stop hook is now active"},
            {"type": "user", "timestamp": "2026-09-01T11:15:00Z", "message": "Also add refresh token rotation."},
        ]
        with open(t_file, "w") as f:
            for item in lines:
                f.write(json.dumps(item) + "\n")

        prompts, src = extract_claude_prompts(sid, cwd)
        self.assertEqual(len(prompts), 2)
        self.assertTrue(prompts[0].is_original)
        self.assertEqual(prompts[0].text, "/goal Implement user authentication with JWT")
        self.assertEqual(prompts[1].text, "Also add refresh token rotation.")

    def test_extract_claude_skips_clear_when_prompt_follows(self):
        sid = "claude-clear-test"
        cwd = "/home/jeff/Developer/test"
        slug = "-home-jeff-Developer-test"
        proj_dir = self.claude_dir / "projects" / slug
        proj_dir.mkdir(parents=True)
        t_file = proj_dir / f"{sid}.jsonl"

        lines = [
            {"type": "user", "message": "<command-name>/clear</command-name>"},
            {"type": "user", "message": "Please refactor the API router."},
        ]
        with open(t_file, "w") as f:
            for item in lines:
                f.write(json.dumps(item) + "\n")

        prompts, src = extract_claude_prompts(sid, cwd)
        self.assertEqual(len(prompts), 1)
        self.assertTrue(prompts[0].is_original)
        self.assertEqual(prompts[0].text, "Please refactor the API router.")


class TestPiExtraction(unittest.TestCase):
    def test_extract_pi_blocks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / ".pi/agent/sessions/--test--"
            root.mkdir(parents=True)
            t_file = root / "2026-09-01_pi-session-789.jsonl"

            lines = [
                {"type": "message", "message": {"role": "user", "content": [{"type": "text", "text": "Fix flaky tests in auth_spec"}]}},
                {"type": "message", "message": {"role": "assistant", "content": [{"type": "text", "text": "Sure thing"}]}},
            ]
            with open(t_file, "w") as f:
                for item in lines:
                    f.write(json.dumps(item) + "\n")

            with patch("pathlib.Path.home", return_value=Path(temp_dir)):
                prompts, src = extract_pi_prompts("pi-session-789", "/test")
                self.assertEqual(len(prompts), 1)
                self.assertEqual(prompts[0].text, "Fix flaky tests in auth_spec")


class TestCodexExtraction(unittest.TestCase):
    def test_extract_codex_from_history(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / ".codex"
            root.mkdir(parents=True)
            hist = root / "history.jsonl"

            lines = [
                {"session_id": "codex-1", "ts": 1786451798, "text": "Initial setup of dev server"},
                {"session_id": "codex-2", "ts": 1786452000, "text": "Unrelated session"},
                {"session_id": "codex-1", "ts": 1786453000, "text": "Second command in session 1"},
            ]
            with open(hist, "w") as f:
                for item in lines:
                    f.write(json.dumps(item) + "\n")

            with patch("pathlib.Path.home", return_value=Path(temp_dir)):
                prompts, src = extract_codex_prompts("codex-1")
                self.assertEqual(len(prompts), 2)
                self.assertTrue(prompts[0].is_original)
                self.assertEqual(prompts[0].text, "Initial setup of dev server")
                self.assertEqual(prompts[1].text, "Second command in session 1")


if __name__ == "__main__":
    unittest.main()
