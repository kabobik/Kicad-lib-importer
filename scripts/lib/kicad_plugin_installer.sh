#!/usr/bin/env bash
# Shared installation of repository-backed KiCad ActionPlugins (Linux).
install_kicad_action_plugin() {
    local source="$1" package="$2" title="$3"
    local version major_minor plugin_dir destination current
    [[ -f "$source/__init__.py" ]] || { echo "Plugin source not found: $source" >&2; return 1; }
    source=$(cd -- "$source" && pwd -P)
    if [[ -n "${KICAD_PLUGIN_DIR:-}" ]]; then
        plugin_dir="$KICAD_PLUGIN_DIR"
    else
        if ! command -v kicad-cli >/dev/null 2>&1; then
            echo 'kicad-cli not found. Install KiCad or set KICAD_PLUGIN_DIR explicitly.' >&2
            return 1
        fi
        version=$(kicad-cli version) || return 1
        if [[ "$version" =~ ^([0-9]+)\.([0-9]+)(\.|$) ]]; then
            major_minor="${BASH_REMATCH[1]}.${BASH_REMATCH[2]}"
        else
            echo "Cannot determine KiCad major.minor from: $version" >&2
            return 1
        fi
        plugin_dir="${XDG_DATA_HOME:-$HOME/.local/share}/kicad/$major_minor/scripting/plugins"
    fi
    destination="$plugin_dir/$package"
    mkdir -p -- "$plugin_dir"
    if [[ -e "$destination" || -L "$destination" ]]; then
        current=$(readlink -f -- "$destination" 2>/dev/null || true)
        if [[ "$current" != "$source" ]]; then
            echo "Destination already exists and belongs to another installation: $destination" >&2
            echo 'Remove that entry manually or choose KICAD_PLUGIN_DIR.' >&2
            return 1
        fi
    else
        ln -s -- "$source" "$destination"
    fi
    printf 'Installed: %s -> %s\n' "$destination" "$source"
    printf 'Restart PCB Editor, then open Tools -> External Plugins -> %s\n' "$title"
}
