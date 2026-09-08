#!/usr/bin/env python3
"""Installer and config updater for herdr-agent-prompt."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import tomllib

PLUGIN_COMMAND = "herdr-agent-prompt.open"
DEFAULT_KEY = "prefix+p"


def install(key: str = DEFAULT_KEY, herdr_bin: str = "herdr", dry_run: bool = False, link: bool = True):
    root = Path(__file__).resolve().parent
    herdr = os.environ.get("HERDR_BIN_PATH", herdr_bin)
    config_path = Path(os.environ.get("HERDR_CONFIG_PATH", Path.home() / ".config/herdr/config.toml"))

    original = config_path.read_text("utf-8") if config_path.exists() else ""
    parsed = tomllib.loads(original) if original else {}
    bindings = parsed.get("keys", {}).get("command", [])

    existing = next((b for b in bindings if b.get("command") == PLUGIN_COMMAND), None)
    active_key = existing.get("key") if existing else key

    if not existing:
        key_conflict = next((b for b in bindings if b.get("key") == active_key), None)
        if key_conflict:
            raise SystemExit(
                f"Shortcut '{active_key}' is already assigned to '{key_conflict.get('command')}' in {config_path}. "
                "Specify a different shortcut with --key, e.g. --key prefix+P"
            )

    addition = f'\n\n[[keys.command]]\nkey = "{active_key}"\ntype = "plugin_action"\ncommand = "{PLUGIN_COMMAND}"\ndescription = "show agent original prompt"\n'
    updated = original if existing else original.rstrip() + addition

    # Validate TOML syntax of updated content
    tomllib.loads(updated)

    if dry_run:
        if link:
            print("[Dry Run] Would link plugin at:", root)
        print(f"[Dry Run] Would configure keybinding '{active_key}' in: {config_path}")
        return

    # Link plugin into Herdr (skipped for marketplace installs, which are already registered)
    if link:
        print(f"Linking plugin in Herdr: {herdr} plugin link {root} --enabled")
        subprocess.run([herdr, "plugin", "link", str(root), "--enabled"], check=True)

    # Update config.toml if needed
    if updated != original:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        mode = stat.S_IMODE(config_path.stat().st_mode) if config_path.exists() else 0o600
        if config_path.exists():
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup = config_path.with_name(f"{config_path.name}.before-prompt-{stamp}")
            shutil.copy2(config_path, backup)
            print(f"Config backup created at: {backup}")

        with tempfile.NamedTemporaryFile(mode="w", dir=config_path.parent, delete=False, encoding="utf-8") as temp_file:
            temp_file.write(updated)
            os.fchmod(temp_file.fileno(), mode)
            temp_path = Path(temp_file.name)

        if (config_path.read_text("utf-8") if config_path.exists() else "") != original:
            temp_path.unlink()
            raise SystemExit("Config changed concurrently during installation; rerun install.py.")

        temp_path.replace(config_path)
        print(f"Added shortcut '{active_key}' to {config_path}")

    # Reload Herdr server config
    try:
        subprocess.run([herdr, "server", "reload-config"], check=True, capture_output=True)
        print("Herdr server config reloaded.")
    except subprocess.CalledProcessError as e:
        print(f"Notice: 'herdr server reload-config' returned: {e}")

    print(f"✓ herdr-agent-prompt installed successfully! Shortcut: {active_key}")


def main():
    parser = argparse.ArgumentParser(description="Install and configure herdr-agent-prompt plugin")
    parser.add_argument("--key", default=os.environ.get("HERDR_PROMPT_KEY", DEFAULT_KEY), help="Shortcut key to bind (default: prefix+p)")
    parser.add_argument("--herdr", default=os.environ.get("HERDR_BIN_PATH", "herdr"), help="Path to herdr executable")
    parser.add_argument("--dry-run", action="store_true", help="Preview actions without writing")
    parser.add_argument(
        "--no-link",
        action="store_true",
        help="Only configure the shortcut; skip 'herdr plugin link' (use after 'herdr plugin install')",
    )
    args = parser.parse_args()

    install(key=args.key, herdr_bin=args.herdr, dry_run=args.dry_run, link=not args.no_link)


if __name__ == "__main__":
    main()
