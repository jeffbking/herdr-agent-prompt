"""Extractor for AI coding agent original prompts from session transcripts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import glob
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, List, Optional


@dataclass
class PromptItem:
    turn: int  # 1-indexed (1 is original prompt)
    total_turns: int
    text: str
    created_at: Optional[str] = None
    is_original: bool = False


@dataclass
class AgentSession:
    pane_id: str
    agent_kind: str
    agent_name: str
    session_id: str
    cwd: str
    status: str
    terminal_title: str = ""
    source_file: Optional[str] = None
    prompts: List[PromptItem] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def original_prompt(self) -> Optional[str]:
        if self.prompts:
            return self.prompts[0].text
        return None


def run_herdr_cmd(args: list[str]) -> Optional[dict]:
    herdr = os.environ.get("HERDR_BIN_PATH", "herdr")
    try:
        proc = subprocess.run(
            [herdr] + args,
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return None
        return json.loads(proc.stdout)
    except Exception:
        return None


def clean_xml_tags(text: str) -> str:
    """Strip top-level XML-like wrapper tags while preserving user text."""
    # Strip <USER_REQUEST>...</USER_REQUEST> wrapper if present
    m = re.search(r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>", text, re.DOTALL)
    if m:
        text = m.group(1)
    
    # Strip metadata blocks
    text = re.sub(r"<ADDITIONAL_METADATA>.*?</ADDITIONAL_METADATA>", "", text, flags=re.DOTALL)
    text = re.sub(r"<USER_SETTINGS_CHANGE>.*?</USER_SETTINGS_CHANGE>", "", text, flags=re.DOTALL)
    text = re.sub(r"<local-command-caveat>.*?</local-command-caveat>", "", text, flags=re.DOTALL)
    text = re.sub(r"<local-command-stdout>.*?</local-command-stdout>", "", text, flags=re.DOTALL)
    text = re.sub(r"<task-notification>.*?</task-notification>", "", text, flags=re.DOTALL)
    return text.strip()


def extract_agy_prompts(session_id: str, cwd: Optional[str] = None) -> tuple[list[PromptItem], Optional[str]]:
    """Extract prompt items for Antigravity (agy)."""
    brain_dir = Path(os.environ.get("AGY_BRAIN_DIR", Path.home() / ".gemini/antigravity-cli/brain"))
    target = None
    if session_id:
        p = brain_dir / session_id / ".system_generated/logs/transcript.jsonl"
        if p.is_file():
            target = p
        else:
            # Fallback to transcript_full.jsonl
            pf = brain_dir / session_id / ".system_generated/logs/transcript_full.jsonl"
            if pf.is_file():
                target = pf

    if not target and brain_dir.is_dir():
        # Look for most recent transcript matching or in brain dir
        candidates = sorted(
            brain_dir.glob("*/.system_generated/logs/transcript.jsonl"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        if candidates:
            target = candidates[0]

    if not target or not target.is_file():
        return [], None

    prompts: list[PromptItem] = []
    with open(target, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("type") == "USER_INPUT" and d.get("source") == "USER_EXPLICIT":
                raw = d.get("content", "")
                cleaned = clean_xml_tags(raw)
                if cleaned:
                    ts = d.get("created_at")
                    prompts.append(
                        PromptItem(
                            turn=len(prompts) + 1,
                            total_turns=0,
                            text=cleaned,
                            created_at=ts,
                            is_original=(len(prompts) == 0),
                        )
                    )

    for p in prompts:
        p.total_turns = len(prompts)
    return prompts, str(target)


def extract_claude_prompts(session_id: str, cwd: Optional[str] = None) -> tuple[list[PromptItem], Optional[str]]:
    """Extract prompt items for Claude Code."""
    root = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")) / "projects"
    target = None

    if cwd and session_id:
        slug = re.sub(r"[^a-zA-Z0-9]", "-", cwd)
        candidate = root / slug / f"{session_id}.jsonl"
        if candidate.is_file():
            target = candidate

    if not target and session_id and root.is_dir():
        matches = list(root.glob(f"*/{session_id}.jsonl"))
        if matches:
            target = matches[0]

    if not target and cwd and root.is_dir():
        slug = re.sub(r"[^a-zA-Z0-9]", "-", cwd)
        candidates = sorted((root / slug).glob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)
        if candidates:
            target = candidates[0]

    if not target or not target.is_file():
        return [], None

    prompts: list[PromptItem] = []
    with open(target, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("type") == "user":
                msg = d.get("message")
                content = msg.get("content") if isinstance(msg, dict) else msg
                if isinstance(content, list):
                    texts = [
                        b.get("text", "")
                        for b in content
                        if isinstance(b, dict) and b.get("type") == "text"
                    ]
                    content = " ".join(texts)
                content = str(content or "").strip()
                if not content:
                    continue

                if "<local-command-caveat>" in content or "<local-command-stdout>" in content:
                    continue
                if "A session-scoped Stop hook" in content or "[{'tool_use_id'" in content:
                    continue

                # Check slash command with args
                cmd_match = re.search(
                    r"<command-name>(.*?)</command-name>\s*(?:<command-message>.*?</command-message>\s*)?<command-args>(.*?)</command-args>",
                    content,
                    re.DOTALL,
                )
                if cmd_match:
                    cname = cmd_match.group(1).strip()
                    cargs = cmd_match.group(2).strip()
                    prompt_text = f"{cname} {cargs}".strip()
                else:
                    cmd_single = re.search(r"<command-name>(.*?)</command-name>", content)
                    if cmd_single:
                        prompt_text = cmd_single.group(1).strip()
                    else:
                        prompt_text = clean_xml_tags(content)

                if prompt_text:
                    ts = d.get("timestamp") or d.get("created_at")
                    prompts.append(
                        PromptItem(
                            turn=len(prompts) + 1,
                            total_turns=0,
                            text=prompt_text,
                            created_at=ts,
                            is_original=(len(prompts) == 0),
                        )
                    )

    # Filter out a leading trivial command like /clear if a substantive prompt followed
    if len(prompts) > 1 and prompts[0].text in ("/clear", "/init", "/exit", "clear", "exit"):
        prompts = prompts[1:]
        for i, p in enumerate(prompts):
            p.turn = i + 1
            p.is_original = (i == 0)

    for p in prompts:
        p.total_turns = len(prompts)
    return prompts, str(target)


def extract_pi_prompts(session_id: str, cwd: Optional[str] = None) -> tuple[list[PromptItem], Optional[str]]:
    """Extract prompt items for Pi agent."""
    root = Path.home() / ".pi/agent/sessions"
    target = None

    if session_id and root.is_dir():
        matches = list(root.glob(f"*/*{session_id}*.jsonl"))
        if matches:
            target = matches[0]

    if not target and cwd and root.is_dir():
        slug = f"--{re.sub(r'[^a-zA-Z0-9]', '-', cwd)}--"
        folder = root / slug
        if folder.is_dir():
            candidates = sorted(folder.glob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)
            if candidates:
                target = candidates[0]

    if not target and root.is_dir():
        candidates = sorted(root.glob("*/*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)
        if candidates:
            target = candidates[0]

    if not target or not target.is_file():
        return [], None

    prompts: list[PromptItem] = []
    with open(target, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("type") == "message" and d.get("message", {}).get("role") == "user":
                content = d.get("message", {}).get("content", [])
                if isinstance(content, list):
                    texts = [
                        b.get("text", "")
                        for b in content
                        if isinstance(b, dict) and b.get("type") == "text"
                    ]
                    content = " ".join(texts)
                content = str(content or "").strip()
                if not content or content.startswith("["):
                    continue

                ts = d.get("timestamp") or d.get("created_at")
                prompts.append(
                    PromptItem(
                        turn=len(prompts) + 1,
                        total_turns=0,
                        text=content,
                        created_at=ts,
                        is_original=(len(prompts) == 0),
                    )
                )

    for p in prompts:
        p.total_turns = len(prompts)
    return prompts, str(target)


def extract_codex_prompts(session_id: str, cwd: Optional[str] = None) -> tuple[list[PromptItem], Optional[str]]:
    """Extract prompt items for Codex agent."""
    root = Path.home() / ".codex"
    history_file = root / "history.jsonl"
    prompts: list[PromptItem] = []
    source_file = None

    if history_file.is_file() and session_id:
        with open(history_file, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if d.get("session_id") == session_id:
                    txt = d.get("text", "").strip()
                    if txt:
                        ts_val = d.get("ts")
                        ts_str = None
                        if ts_val:
                            try:
                                ts_str = datetime.fromtimestamp(ts_val).isoformat()
                            except Exception:
                                pass
                        prompts.append(
                            PromptItem(
                                turn=len(prompts) + 1,
                                total_turns=0,
                                text=txt,
                                created_at=ts_str,
                                is_original=(len(prompts) == 0),
                            )
                        )
        if prompts:
            source_file = str(history_file)

    if not prompts and session_id and (root / "sessions").is_dir():
        # Search rollout files
        matches = list((root / "sessions").glob(f"**/*{session_id}*.jsonl"))
        if matches:
            target = matches[0]
            source_file = str(target)
            with open(target, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    payload = d.get("payload", {})
                    if isinstance(payload, dict) and payload.get("role") == "user":
                        c = payload.get("content", [])
                        if isinstance(c, list):
                            texts = [
                                item.get("text", "")
                                for item in c
                                if isinstance(item, dict) and item.get("type") == "input_text"
                            ]
                            c = " ".join(texts)
                        c = clean_xml_tags(str(c or ""))
                        if c and not c.startswith("# AGENTS.md instructions"):
                            prompts.append(
                                PromptItem(
                                    turn=len(prompts) + 1,
                                    total_turns=0,
                                    text=c,
                                    created_at=d.get("timestamp"),
                                    is_original=(len(prompts) == 0),
                                )
                            )

    if not prompts and session_id and (root / "session_index.jsonl").is_file():
        with open(root / "session_index.jsonl", "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if d.get("id") == session_id:
                    name = d.get("thread_name", "").strip()
                    if name:
                        prompts.append(
                            PromptItem(
                                turn=1,
                                total_turns=1,
                                text=name,
                                created_at=d.get("updated_at"),
                                is_original=True,
                            )
                        )
                        source_file = str(root / "session_index.jsonl")
                        break

    for p in prompts:
        p.total_turns = len(prompts)
    return prompts, source_file


def extract_generic_prompts(pane_id: str, agent_kind: str, session_id: str, cwd: Optional[str] = None) -> tuple[list[PromptItem], Optional[str]]:
    """Fallback prompt extraction using Herdr pane information."""
    data = run_herdr_cmd(["pane", "get", pane_id])
    if data and "result" in data and "pane" in data["result"]:
        pane = data["result"]["pane"]
        title = pane.get("terminal_title_stripped") or pane.get("terminal_title")
        if title and title not in ("bash", "zsh", "sh"):
            return [
                PromptItem(
                    turn=1,
                    total_turns=1,
                    text=f"[Terminal Title]: {title}",
                    is_original=True,
                )
            ], None
    return [], None


def resolve_session_prompts(
    pane_id: str,
    agent_kind: str,
    agent_name: str,
    session_id: str,
    cwd: str,
    status: str,
    terminal_title: str = "",
) -> AgentSession:
    """Resolve all prompts for an agent session."""
    prompts: list[PromptItem] = []
    source_file: Optional[str] = None

    norm_kind = (agent_kind or "").lower()
    if norm_kind in ("agy", "antigravity"):
        prompts, source_file = extract_agy_prompts(session_id, cwd)
    elif norm_kind in ("claude", "claude-code"):
        prompts, source_file = extract_claude_prompts(session_id, cwd)
    elif norm_kind in ("pi",):
        prompts, source_file = extract_pi_prompts(session_id, cwd)
    elif norm_kind in ("codex",):
        prompts, source_file = extract_codex_prompts(session_id, cwd)

    if not prompts and pane_id:
        prompts, source_file = extract_generic_prompts(pane_id, agent_kind, session_id, cwd)

    error = None
    if not prompts:
        error = f"No prompt transcript found for {agent_kind or 'unknown'} (session: {session_id or 'none'})"

    return AgentSession(
        pane_id=pane_id,
        agent_kind=agent_kind or "unknown",
        agent_name=agent_name or "",
        session_id=session_id or "",
        cwd=cwd or "",
        status=status or "unknown",
        terminal_title=terminal_title or "",
        source_file=source_file,
        prompts=prompts,
        error=error,
    )


def get_session_for_pane(target_pane_id: Optional[str] = None) -> AgentSession:
    """Retrieve session and prompt information for a specific pane or the active focused pane."""
    pane_id = target_pane_id
    if not pane_id:
        curr = run_herdr_cmd(["pane", "current"])
        if curr and "result" in curr and "pane" in curr["result"]:
            pane_id = curr["result"]["pane"].get("pane_id")

    if not pane_id:
        return AgentSession(
            pane_id="",
            agent_kind="none",
            agent_name="",
            session_id="",
            cwd="",
            status="none",
            error="Could not determine active Herdr pane.",
        )

    # Query pane details
    pane_data = run_herdr_cmd(["pane", "get", pane_id])
    pane_info = {}
    if pane_data and "result" in pane_data and "pane" in pane_data["result"]:
        pane_info = pane_data["result"]["pane"]

    # Query agent details
    agent_data = run_herdr_cmd(["agent", "get", pane_id])
    agent_info = {}
    if agent_data and "result" in agent_data and "agent" in agent_data["result"]:
        agent_info = agent_data["result"]["agent"]

    agent_kind = agent_info.get("agent") or pane_info.get("agent")
    agent_session = agent_info.get("agent_session") or pane_info.get("agent_session") or {}
    session_id = agent_session.get("value") or ""
    agent_name = agent_info.get("name") or pane_info.get("name") or ""
    cwd = agent_info.get("cwd") or pane_info.get("foreground_cwd") or pane_info.get("cwd") or ""
    status = agent_info.get("agent_status") or pane_info.get("agent_status") or "unknown"
    terminal_title = agent_info.get("terminal_title_stripped") or pane_info.get("terminal_title_stripped") or ""

    if not agent_kind or not session_id:
        # Cross-reference with agent.list
        agent_list_data = run_herdr_cmd(["agent", "list"])
        if agent_list_data and "result" in agent_list_data and "agents" in agent_list_data["result"]:
            for a in agent_list_data["result"]["agents"]:
                if a.get("pane_id") == pane_id:
                    agent_kind = agent_kind or a.get("agent")
                    agent_name = agent_name or a.get("name")
                    session_id = session_id or a.get("agent_session", {}).get("value") or ""
                    cwd = cwd or a.get("cwd") or a.get("foreground_cwd") or ""
                    status = a.get("agent_status") or status
                    terminal_title = terminal_title or a.get("terminal_title_stripped") or ""
                    break

    if not agent_kind:
        return AgentSession(
            pane_id=pane_id,
            agent_kind="none",
            agent_name="",
            session_id="",
            cwd=cwd,
            status=status,
            terminal_title=terminal_title,
            error=f"No active agent detected in pane {pane_id}.",
        )

    return resolve_session_prompts(
        pane_id=pane_id,
        agent_kind=agent_kind,
        agent_name=agent_name,
        session_id=session_id,
        cwd=cwd,
        status=status,
        terminal_title=terminal_title,
    )


def list_all_agent_sessions() -> list[AgentSession]:
    """List all active agent sessions across all Herdr workspaces and panes."""
    agent_list_data = run_herdr_cmd(["agent", "list"])
    if not agent_list_data or "result" not in agent_list_data:
        return []

    agents = agent_list_data["result"].get("agents", [])
    results: list[AgentSession] = []
    for a in agents:
        pane_id = a.get("pane_id", "")
        agent_kind = a.get("agent", "")
        agent_name = a.get("name", "")
        session_id = a.get("agent_session", {}).get("value", "")
        cwd = a.get("cwd") or a.get("foreground_cwd") or ""
        status = a.get("agent_status", "")
        terminal_title = a.get("terminal_title_stripped") or a.get("terminal_title") or ""

        session = resolve_session_prompts(
            pane_id=pane_id,
            agent_kind=agent_kind,
            agent_name=agent_name,
            session_id=session_id,
            cwd=cwd,
            status=status,
            terminal_title=terminal_title,
        )
        results.append(session)
    return results
