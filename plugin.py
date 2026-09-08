#!/usr/bin/env python3
"""Herdr plugin entrypoint for agent original prompt inspection."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from typing import Optional

from extractor import (
    get_session_for_pane,
    list_all_agent_sessions,
    run_herdr_cmd,
)

PLUGIN_ID = "herdr-agent-prompt"
ENTRYPOINT = "viewer"


def resolve_target_pane_id() -> Optional[str]:
    """Resolve target pane ID from environment context or Herdr query."""
    context_str = os.environ.get("HERDR_PLUGIN_CONTEXT_JSON")
    if context_str:
        try:
            ctx = json.loads(context_str)
            target = ctx.get("focused_pane_id") or ctx.get("pane_id")
            if target:
                return str(target)
        except Exception:
            pass

    env_target = os.environ.get("HERDR_PROMPT_TARGET_PANE_ID") or os.environ.get("HERDR_PANE_ID")
    if env_target:
        return env_target

    curr = run_herdr_cmd(["pane", "current"])
    if curr and "result" in curr and "pane" in curr["result"]:
        return curr["result"]["pane"].get("pane_id")

    return None


def open_overlay():
    """Launch the prompt viewer overlay pane in Herdr."""
    herdr = os.environ.get("HERDR_BIN_PATH", "herdr")
    pane_id = resolve_target_pane_id() or ""

    cmd = [
        herdr,
        "plugin",
        "pane",
        "open",
        "--plugin",
        PLUGIN_ID,
        "--entrypoint",
        ENTRYPOINT,
        "--placement",
        "overlay",
        "--env",
        f"HERDR_PROMPT_TARGET_PANE_ID={pane_id}",
        "--focus",
    ]

    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if res.returncode != 0:
        err = (res.stderr or res.stdout or "Failed to open prompt overlay").strip()
        print(f"Error opening overlay: {err}", file=sys.stderr)
        run_herdr_cmd(["notification", "show", "Prompt Viewer Failed", "--body", err[:200]])
        return res.returncode
    return 0


def cmd_get(pane_id: Optional[str], as_json: bool, turn: int):
    target = pane_id or resolve_target_pane_id()
    session = get_session_for_pane(target)

    if as_json:
        out = {
            "pane_id": session.pane_id,
            "agent_kind": session.agent_kind,
            "agent_name": session.agent_name,
            "session_id": session.session_id,
            "cwd": session.cwd,
            "status": session.status,
            "source_file": session.source_file,
            "error": session.error,
            "prompts": [
                {
                    "turn": p.turn,
                    "is_original": p.is_original,
                    "created_at": p.created_at,
                    "text": p.text,
                }
                for p in session.prompts
            ],
        }
        print(json.dumps(out, indent=2))
        return

    if not session.prompts:
        print(session.error or f"No prompt found for pane {target or 'unknown'}", file=sys.stderr)
        sys.exit(1)

    idx = turn - 1
    if idx < 0 or idx >= len(session.prompts):
        print(f"Invalid turn {turn}. Available turns: 1..{len(session.prompts)}", file=sys.stderr)
        sys.exit(1)

    print(session.prompts[idx].text)


def cmd_list(as_json: bool):
    sessions = list_all_agent_sessions()
    if as_json:
        out = []
        for s in sessions:
            out.append({
                "pane_id": s.pane_id,
                "agent_kind": s.agent_kind,
                "agent_name": s.agent_name,
                "session_id": s.session_id,
                "cwd": s.cwd,
                "status": s.status,
                "source_file": s.source_file,
                "original_prompt": s.original_prompt,
                "turns_count": len(s.prompts),
            })
        print(json.dumps(out, indent=2))
        return

    if not sessions:
        print("No active agent sessions found in Herdr.")
        return

    print(f"{'PANE':<8} {'AGENT':<8} {'NAME':<20} {'STATUS':<10} {'PROMPT (ORIGINAL)'}")
    print("-" * 80)
    for s in sessions:
        orig = (s.original_prompt or s.error or "").replace("\n", " ")
        if len(orig) > 50:
            orig = orig[:47] + "..."
        name = s.agent_name or "none"
        print(f"{s.pane_id:<8} {s.agent_kind:<8} {name:<20} {s.status:<10} {orig}")


def main():
    parser = argparse.ArgumentParser(description="Herdr Agent Original Prompt Viewer")
    subparsers = parser.add_subparsers(dest="command")

    # open: action command for Herdr keybinding
    subparsers.add_parser("open", help="Open the prompt viewer overlay")

    # ui: curses TUI inside the overlay
    p_ui = subparsers.add_parser("ui", help="Run interactive curses UI")
    p_ui.add_argument("--pane", help="Target pane ID")

    # get: print prompt to stdout
    p_get = subparsers.add_parser("get", help="Print agent prompt to stdout")
    p_get.add_argument("pane", nargs="?", help="Target pane ID")
    p_get.add_argument("--json", action="store_true", help="Output as JSON")
    p_get.add_argument("--turn", type=int, default=1, help="Turn number to print (default 1 = original)")

    # list: list all active agents and prompts
    p_list = subparsers.add_parser("list", help="List all active agents and their prompts")
    p_list.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    if args.command == "open":
        sys.exit(open_overlay())
    elif args.command == "ui":
        from ui import start_ui
        pane_id = args.pane or resolve_target_pane_id()
        start_ui(pane_id)
    elif args.command == "get":
        cmd_get(args.pane, args.json, args.turn)
    elif args.command == "list":
        cmd_list(args.json)
    else:
        # Default behavior when invoked without subcommand:
        # If in terminal interactively, launch ui
        if sys.stdin.isatty():
            from ui import start_ui
            pane_id = resolve_target_pane_id()
            start_ui(pane_id)
        else:
            parser.print_help()


if __name__ == "__main__":
    main()
