# Changelog

All notable changes to this plugin are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-09-07

### Added
- `prefix+p` overlay showing the focused agent pane's original prompt.
- Multi-turn navigation (`[` / `]`, `p` / `n`, `1` for the original prompt).
- Clipboard copy via OSC 52 with `wl-copy`, `xclip`, and `pbcopy` fallbacks.
- Transcript readers for Antigravity (`agy`), Claude Code, Pi, and Codex, plus a generic pane fallback.
- Cross-pane agent picker when the overlay is opened on a non-agent pane.
- `plugin.py list` / `plugin.py get` CLI for scripting.
- `install.py` helper that links the plugin and binds the shortcut in `~/.config/herdr/config.toml` (`--no-link` for marketplace installs).
- MIT license, changelog, and marketplace install instructions.
