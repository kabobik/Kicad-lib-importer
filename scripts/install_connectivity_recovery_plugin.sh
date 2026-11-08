#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPT_DIR/lib/kicad_plugin_installer.sh"

python_bin="${KICAD_RECOVERY_PYTHON:-python3}"
if ! "$python_bin" -c 'import sys; import pcbnew; assert sys.version_info >= (3, 11), "Python 3.11+ required"'; then
    echo 'Recovery needs Python 3.11+ with pcbnew. Set KICAD_RECOVERY_PYTHON to the correct interpreter.' >&2
    exit 1
fi
command -v kicad-cli >/dev/null 2>&1 || { echo 'kicad-cli not found in PATH.' >&2; exit 1; }
install_kicad_action_plugin \
    "$REPO_ROOT/plugins/connectivity-recovery/connectivity_recovery_plugin" \
    connectivity_recovery_plugin 'Восстановить схему по меди'
