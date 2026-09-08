"""Interactive curses terminal UI for viewing agent original prompts."""

from __future__ import annotations

import base64
import curses
import os
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap
from typing import List, Optional

from extractor import AgentSession, PromptItem, get_session_for_pane, list_all_agent_sessions


def copy_to_clipboard(text: str) -> bool:
    """Copy text to system clipboard using OSC 52, with native utility fallbacks."""
    copied = False
    # OSC 52 escape sequence - works in Herdr, Ghostty, Moshi, xterm, tmux, SSH
    try:
        encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
        osc52 = f"\033]52;c;{encoded}\a"
        sys.stdout.write(osc52)
        sys.stdout.flush()
        copied = True
    except Exception:
        pass

    # Native tools as backup
    if shutil.which("wl-copy"):
        try:
            subprocess.run(["wl-copy"], input=text.encode("utf-8"), check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            copied = True
        except Exception:
            pass
    elif shutil.which("xclip"):
        try:
            subprocess.run(["xclip", "-selection", "clipboard"], input=text.encode("utf-8"), check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            copied = True
        except Exception:
            pass
    elif shutil.which("pbcopy"):
        try:
            subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            copied = True
        except Exception:
            pass

    return copied


def format_path(path_str: str) -> str:
    home = str(Path.home())
    if path_str.startswith(home):
        return "~" + path_str[len(home):]
    return path_str


class PromptViewer:
    def __init__(self, target_pane_id: Optional[str] = None):
        self.target_pane_id = target_pane_id
        self.session: AgentSession = get_session_for_pane(target_pane_id)
        self.all_sessions: List[AgentSession] = []
        self.active_turn_idx: int = 0  # 0 is original prompt
        self.scroll_offset: int = 0
        self.status_message: str = ""
        self.status_is_error: bool = False
        self.wrapped_lines: List[str] = []
        self.selected_other_idx: int = 0

        if not self.session.prompts:
            self.all_sessions = list_all_agent_sessions()

    def reload(self):
        self.session = get_session_for_pane(self.target_pane_id)
        if not self.session.prompts:
            self.all_sessions = list_all_agent_sessions()
        else:
            self.active_turn_idx = min(self.active_turn_idx, max(0, len(self.session.prompts) - 1))
        self.scroll_offset = 0
        self.status_message = "Refreshed."
        self.status_is_error = False

    def wrap_current_prompt(self, max_width: int):
        if not self.session.prompts:
            self.wrapped_lines = []
            return

        idx = min(self.active_turn_idx, len(self.session.prompts) - 1)
        raw_text = self.session.prompts[idx].text
        lines = []
        for paragraph in raw_text.splitlines():
            if not paragraph.strip():
                lines.append("")
            else:
                wrapped = textwrap.wrap(
                    paragraph,
                    width=max_width,
                    replace_whitespace=False,
                    drop_whitespace=False,
                )
                lines.extend(wrapped or [""])
        self.wrapped_lines = lines

    def run(self, stdscr):
        curses.curs_set(0)
        stdscr.keypad(True)
        curses.use_default_colors()

        # Initialize color pairs
        # 1: Title / Accent (Cyan)
        # 2: Success (Green)
        # 3: Warning / Working (Yellow)
        # 4: Error / Blocked (Red)
        # 5: Dim / Border
        # 6: Header badge
        curses.init_pair(1, curses.COLOR_CYAN, -1)
        curses.init_pair(2, curses.COLOR_GREEN, -1)
        curses.init_pair(3, curses.COLOR_YELLOW, -1)
        curses.init_pair(4, curses.COLOR_RED, -1)
        curses.init_pair(5, curses.COLOR_WHITE, -1)
        curses.init_pair(6, curses.COLOR_BLACK, curses.COLOR_CYAN)

        while True:
            height, width = stdscr.getmaxyx()
            if height < 8 or width < 30:
                stdscr.erase()
                try:
                    stdscr.addstr(0, 0, "Terminal too small")
                except curses.error:
                    pass
                stdscr.refresh()
                key = stdscr.getch()
                if key in (ord('q'), ord('Q'), 27):
                    break
                continue

            content_width = max(10, width - 4)
            self.wrap_current_prompt(content_width)

            stdscr.erase()
            if self.session.prompts:
                self.draw_prompt_view(stdscr, height, width)
            else:
                self.draw_empty_view(stdscr, height, width)

            stdscr.refresh()

            try:
                ch = stdscr.getch()
            except KeyboardInterrupt:
                break

            if ch in (ord('q'), ord('Q'), 27):  # 27 = Esc
                break
            elif ch == curses.KEY_RESIZE:
                continue
            elif ch in (ord('r'), ord('R')):
                self.reload()
            elif self.session.prompts:
                self.handle_prompt_key(ch, height)
            else:
                self.handle_empty_key(ch)

    def handle_prompt_key(self, ch: int, height: int):
        num_prompts = len(self.session.prompts)
        body_height = max(1, height - 7)
        max_scroll = max(0, len(self.wrapped_lines) - body_height)

        if ch in (curses.KEY_UP, ord('k'), ord('K')):
            self.scroll_offset = max(0, self.scroll_offset - 1)
        elif ch in (curses.KEY_DOWN, ord('j'), ord('J')):
            self.scroll_offset = min(max_scroll, self.scroll_offset + 1)
        elif ch in (curses.KEY_PPAGE, ord('b'), ord('B'), 2):  # Ctrl+B
            self.scroll_offset = max(0, self.scroll_offset - body_height)
        elif ch in (curses.KEY_NPAGE, ord(' '), 6):  # Space, Ctrl+F
            self.scroll_offset = min(max_scroll, self.scroll_offset + body_height)
        elif ch in (curses.KEY_HOME, ord('g')):
            self.scroll_offset = 0
        elif ch in (curses.KEY_END, ord('G')):
            self.scroll_offset = max_scroll
        elif ch in (ord('n'), ord(']'), 9):  # 9 = Tab -> next turn
            if num_prompts > 1:
                self.active_turn_idx = (self.active_turn_idx + 1) % num_prompts
                self.scroll_offset = 0
                self.status_message = ""
        elif ch in (ord('p'), ord('['), curses.KEY_BTAB):  # prev turn
            if num_prompts > 1:
                self.active_turn_idx = (self.active_turn_idx - 1 + num_prompts) % num_prompts
                self.scroll_offset = 0
                self.status_message = ""
        elif ch == ord('1'):
            self.active_turn_idx = 0
            self.scroll_offset = 0
            self.status_message = "Jumped to original prompt."
        elif ch in (ord('y'), ord('Y'), ord('c'), ord('C'), ord('\n'), ord('\r'), curses.KEY_ENTER):
            active_prompt = self.session.prompts[self.active_turn_idx].text
            success = copy_to_clipboard(active_prompt)
            if success:
                label = "original prompt" if self.active_turn_idx == 0 else f"turn {self.active_turn_idx + 1}"
                self.status_message = f"✓ Copied {label} to clipboard!"
                self.status_is_error = False
            else:
                self.status_message = "Failed to copy to clipboard."
                self.status_is_error = True

    def handle_empty_key(self, ch: int):
        if not self.all_sessions:
            return
        if ch in (curses.KEY_UP, ord('k')):
            self.selected_other_idx = max(0, self.selected_other_idx - 1)
        elif ch in (curses.KEY_DOWN, ord('j')):
            self.selected_other_idx = min(len(self.all_sessions) - 1, self.selected_other_idx + 1)
        elif ch in (ord('\n'), ord('\r'), curses.KEY_ENTER):
            chosen = self.all_sessions[self.selected_other_idx]
            self.target_pane_id = chosen.pane_id
            self.session = chosen
            self.active_turn_idx = 0
            self.scroll_offset = 0
            self.status_message = ""

    def draw_prompt_view(self, stdscr, height: int, width: int):
        cur_item: PromptItem = self.session.prompts[self.active_turn_idx]
        is_orig = (self.active_turn_idx == 0)
        total_turns = len(self.session.prompts)

        # Header box (Rows 0-3)
        # Row 0: Top title bar
        title = " 󰚩 AGENT PROMPT "
        turn_label = f" Turn {self.active_turn_idx + 1}/{total_turns} [ORIGINAL] " if is_orig else f" Turn {self.active_turn_idx + 1}/{total_turns} "
        
        try:
            # Border top
            stdscr.addstr(0, 0, "╭" + ("─" * (width - 2)) + "╮", curses.color_pair(1) | curses.A_BOLD)
            stdscr.addstr(0, 2, title, curses.color_pair(6) | curses.A_BOLD)
            if width > len(title) + len(turn_label) + 6:
                stdscr.addstr(0, width - len(turn_label) - 2, turn_label, curses.color_pair(2 if is_orig else 3) | curses.A_BOLD)

            # Row 1: Agent info
            stdscr.addstr(1, 0, "│", curses.color_pair(1) | curses.A_BOLD)
            stdscr.addstr(1, width - 1, "│", curses.color_pair(1) | curses.A_BOLD)
            agent_badge = f" {self.session.agent_kind.upper()} "
            stdscr.addstr(1, 2, agent_badge, curses.color_pair(6) | curses.A_BOLD)

            info_text = f" name: {self.session.agent_name or 'none'}  status: {self.session.status}  pane: {self.session.pane_id}"
            stdscr.addnstr(1, 2 + len(agent_badge) + 1, info_text, width - len(agent_badge) - 5, curses.color_pair(5))

            # Row 2: Directory & Session
            stdscr.addstr(2, 0, "│", curses.color_pair(1) | curses.A_BOLD)
            stdscr.addstr(2, width - 1, "│", curses.color_pair(1) | curses.A_BOLD)
            meta_text = f"cwd: {format_path(self.session.cwd)}"
            if cur_item.created_at:
                meta_text += f"  time: {cur_item.created_at}"
            stdscr.addnstr(2, 2, meta_text, width - 4, curses.A_DIM)

            # Row 3: Separator
            stdscr.addstr(3, 0, "├" + ("─" * (width - 2)) + "┤", curses.color_pair(1))
        except curses.error:
            pass

        # Body (Rows 4 to height - 4)
        body_top = 4
        body_height = height - 7
        total_lines = len(self.wrapped_lines)

        for i in range(body_height):
            line_idx = self.scroll_offset + i
            y = body_top + i
            try:
                stdscr.addstr(y, 0, "│", curses.color_pair(1))
                stdscr.addstr(y, width - 1, "│", curses.color_pair(1))
                if line_idx < total_lines:
                    text_line = self.wrapped_lines[line_idx]
                    stdscr.addnstr(y, 2, text_line, width - 4)
            except curses.error:
                pass

        # Bottom section (Rows height - 3 to height - 1)
        bottom_sep_y = height - 3
        footer_y = height - 2
        bottom_bar_y = height - 1

        try:
            # Bottom separator
            scroll_pct = 100 if total_lines <= body_height else int((self.scroll_offset / max(1, total_lines - body_height)) * 100)
            scroll_info = f" {scroll_pct}% (Line {self.scroll_offset + 1}/{total_lines}) "
            stdscr.addstr(bottom_sep_y, 0, "├" + ("─" * (width - 2)) + "┤", curses.color_pair(1))
            if width > len(scroll_info) + 6:
                stdscr.addstr(bottom_sep_y, width - len(scroll_info) - 3, scroll_info, curses.A_DIM)

            # Footer status row
            stdscr.addstr(footer_y, 0, "│", curses.color_pair(1))
            stdscr.addstr(footer_y, width - 1, "│", curses.color_pair(1))
            if self.status_message:
                color = curses.color_pair(4 if self.status_is_error else 2) | curses.A_BOLD
                stdscr.addnstr(footer_y, 2, self.status_message, width - 4, color)
            else:
                hints = "[q/Esc] Close   [y/c/Enter] Copy Prompt   [↑/↓/j/k] Scroll   [n/p] Turns"
                stdscr.addnstr(footer_y, 2, hints, width - 4, curses.A_DIM)

            # Bottom bar
            stdscr.addstr(bottom_bar_y, 0, "╰" + ("─" * (width - 2)) + "╯", curses.color_pair(1) | curses.A_BOLD)
        except curses.error:
            pass

    def draw_empty_view(self, stdscr, height: int, width: int):
        try:
            stdscr.addstr(0, 0, "╭" + ("─" * (width - 2)) + "╮", curses.color_pair(1) | curses.A_BOLD)
            stdscr.addstr(0, 2, " Agent Prompt Viewer ", curses.color_pair(6) | curses.A_BOLD)

            stdscr.addstr(1, 0, "│", curses.color_pair(1))
            stdscr.addstr(1, width - 1, "│", curses.color_pair(1))
            stdscr.addstr(1, 2, f"Target pane: {self.session.pane_id or 'unknown'} (cwd: {format_path(self.session.cwd)})", curses.A_BOLD)

            stdscr.addstr(2, 0, "│", curses.color_pair(1))
            stdscr.addstr(2, width - 1, "│", curses.color_pair(1))
            msg = self.session.error or "No active agent session transcript found in this pane."
            stdscr.addnstr(2, 2, msg, width - 4, curses.color_pair(3))

            stdscr.addstr(3, 0, "├" + ("─" * (width - 2)) + "┤", curses.color_pair(1))

            if self.all_sessions:
                stdscr.addstr(4, 2, "Active coding agents running in other panes (select with ↑/↓ and Enter):", curses.A_BOLD)
                row = 5
                for i, s in enumerate(self.all_sessions):
                    if row >= height - 3:
                        break
                    is_sel = (i == self.selected_other_idx)
                    cursor = "▶ " if is_sel else "  "
                    orig_preview = s.original_prompt or "(no transcript)"
                    line = f"{cursor}[{s.pane_id}] {s.agent_kind} ({s.agent_name or 'agent'}) in {format_path(s.cwd)}: {orig_preview}"
                    attr = (curses.color_pair(1) | curses.A_BOLD) if is_sel else curses.A_NORMAL
                    stdscr.addstr(row, 0, "│", curses.color_pair(1))
                    stdscr.addstr(row, width - 1, "│", curses.color_pair(1))
                    stdscr.addnstr(row, 2, line, width - 4, attr)
                    row += 1
            else:
                stdscr.addstr(4, 2, "No other live agents detected in Herdr.", curses.A_DIM)

            for y in range(5 + len(self.all_sessions), height - 2):
                stdscr.addstr(y, 0, "│", curses.color_pair(1))
                stdscr.addstr(y, width - 1, "│", curses.color_pair(1))

            stdscr.addstr(height - 2, 0, "│", curses.color_pair(1))
            stdscr.addstr(height - 2, width - 1, "│", curses.color_pair(1))
            stdscr.addnstr(height - 2, 2, "[q/Esc] Close   [r] Refresh   [Enter] View Selected Agent", width - 4, curses.A_DIM)

            stdscr.addstr(height - 1, 0, "╰" + ("─" * (width - 2)) + "╯", curses.color_pair(1) | curses.A_BOLD)
        except curses.error:
            pass


def start_ui(pane_id: Optional[str] = None):
    viewer = PromptViewer(pane_id)
    curses.wrapper(viewer.run)


if __name__ == "__main__":
    start_ui(sys.argv[1] if len(sys.argv) > 1 else None)
