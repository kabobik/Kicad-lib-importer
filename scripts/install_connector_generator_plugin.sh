#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPT_DIR/lib/kicad_plugin_installer.sh"
install_kicad_action_plugin \
    "$REPO_ROOT/plugins/connector-generator/connector_generator_plugin" \
    connector_generator_plugin 'Generate Connector Symbols'
