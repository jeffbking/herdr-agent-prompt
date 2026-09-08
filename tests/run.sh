#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
echo "Running herdr-agent-prompt unit tests..."
python3 -m unittest discover tests -v
