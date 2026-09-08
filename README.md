# Herdr Agent Prompt Viewer (`herdr-agent-prompt`)

A Herdr plugin that shows the active coding agent's original prompt in an interactive overlay on shortcut press.

Supports **Antigravity (agy)**, **Claude Code**, **Pi**, and **Codex**, plus fallback detection for other agent panes.

## Features

- **Shortcut Access:** Press `prefix+p` from any agent pane to immediately view its original prompt in an overlay.
- **Multi-Turn Navigation:** Displays the original prompt by default (`Turn 1/N [ORIGINAL]`). Cycle between turns with `[` / `]` or `p` / `n`, or press `1` to return to the original prompt.
- **One-Key Clipboard Copy:** Press `y`, `c`, or `Enter` to copy the prompt to your clipboard via OSC 52 (works over SSH, Moshi, Ghostty, and local terminals) with native clipboard fallbacks (`wl-copy`, `xclip`, `pbcopy`).
- **Smooth Text Scrolling:** Word-wrapped prompt text with full arrow, vi (`j`/`k`), page (`Space`/`b`), and boundary (`g`/`G`) navigation.
- **Cross-Pane Diagnostics:** If triggered on a pane without an agent (e.g. a plain shell), displays a list of all live agents across other panes, allowing you to select and inspect any agent.
- **CLI & Scripting Support:** Run `plugin.py list` or `plugin.py get [pane]` directly from the shell or terminal scripts.

## Requirements

- Herdr 0.7.0 or newer on Linux or macOS.
- Python 3 on `PATH` as `python3` (3.11+ for `install.py`, which uses the standard-library `tomllib`). The plugin has no third-party dependencies.
- Optional clipboard helpers for terminals without OSC 52: `wl-copy`, `xclip`, or `pbcopy`.

## Installation

### From the Herdr marketplace

```bash
herdr plugin install jeffbking/herdr-agent-prompt
```

Then bind the action to a shortcut in `~/.config/herdr/config.toml`:

```toml
[[keys.command]]
key = "prefix+p"
type = "plugin_action"
command = "herdr-agent-prompt.open"
description = "show agent original prompt"
```

Reload the running server so the binding takes effect:

```bash
herdr server reload-config
```

Or let the installer add the binding for you (it backs up `config.toml` first and skips the link step since the plugin is already installed):

```bash
python3 ~/.config/herdr/plugins/github/herdr-agent-prompt-*/install.py --no-link
```

To pin a release: `herdr plugin install jeffbking/herdr-agent-prompt --ref v0.1.0`.

### From a local checkout (development)

```bash
git clone https://github.com/jeffbking/herdr-agent-prompt.git
cd herdr-agent-prompt
python3 install.py
```

The installer:
1. Links the plugin into Herdr (`herdr plugin link ... --enabled`).
2. Configures the shortcut in `~/.config/herdr/config.toml` (default: `prefix+p`).
3. Creates a timestamped backup before touching `config.toml`.
4. Reloads the running Herdr server configuration (`herdr server reload-config`).

### Custom Shortcut

To bind a different shortcut (for example `prefix+P`):

```bash
python3 install.py --key "prefix+P"
```

If `prefix+p` is already bound to another command, the installer refuses and tells you which command holds it; pick another key with `--key`.

## Keybindings (Inside the Overlay)

| Key | Action |
| --- | --- |
| `q`, `Esc` | Close overlay and return to active pane |
| `y`, `c`, `Enter` | Copy prompt to clipboard (OSC 52) |
| `↑`, `k` | Scroll up 1 line |
| `↓`, `j` | Scroll down 1 line |
| `PgUp`, `b`, `Ctrl+B` | Page up |
| `PgDn`, `Space`, `Ctrl+F` | Page down |
| `g`, `Home` | Scroll to top |
| `G`, `End` | Scroll to bottom |
| `n`, `]`, `Tab` | Next turn (if agent had follow-up prompts) |
| `p`, `[`, `Shift+Tab` | Previous turn |
| `1` | Jump to original prompt (Turn 1) |
| `r` | Reload transcript from disk |

## CLI Usage

List all live agents and their original prompts:

```bash
python3 plugin.py list
# Or with JSON output:
python3 plugin.py list --json
```

Print the original prompt for a specific pane (or active pane):

```bash
python3 plugin.py get w1B:p3
python3 plugin.py get w1B:p3 --turn 2
python3 plugin.py get w1B:p3 --json
```

## Supported Agents & Transcripts

- **Antigravity (`agy`)**: Reads `~/.gemini/antigravity-cli/brain/<session_id>/.system_generated/logs/transcript.jsonl`. Extracts clean user request text.
- **Claude Code (`claude`)**: Reads `~/.claude/projects/<slug>/<session_id>.jsonl`. Resolves user requests and `/goal`, `/task` slash commands with arguments while skipping caveat and stop hook noise.
- **Pi (`pi`)**: Reads `~/.pi/agent/sessions/<slug>/*.jsonl`. Parses user text message blocks.
- **Codex (`codex`)**: Reads `~/.codex/history.jsonl` by session ID, with fallback to rollout sessions and session index.
- **Generic / Other**: Reads pane metadata, terminal titles, and scrollback.

## Testing

Run the test suite:

```bash
./tests/run.sh
```
