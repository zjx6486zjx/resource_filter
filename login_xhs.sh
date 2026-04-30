#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DEFAULT_XHS_PROFILE="$SCRIPT_DIR/user_data/xhs_profile"

load_env_file() {
    local env_file="$1"
    if [[ -f "$env_file" ]]; then
        set -a
        source /dev/stdin < <(sed 's/\r$//' "$env_file")
        set +a
    fi
}

resolve_python() {
    if [[ -n "${PYTHON_BIN:-}" ]]; then
        echo "$PYTHON_BIN"
        return 0
    fi
    if [[ -n "${CONDA_PREFIX:-}" && -x "${CONDA_PREFIX}/bin/python" ]]; then
        echo "${CONDA_PREFIX}/bin/python"
        return 0
    fi
    if [[ -n "${VIRTUAL_ENV:-}" && -x "${VIRTUAL_ENV}/bin/python" ]]; then
        echo "${VIRTUAL_ENV}/bin/python"
        return 0
    fi
    if [[ -x "$SCRIPT_DIR/.venv/bin/python" ]]; then
        echo "$SCRIPT_DIR/.venv/bin/python"
        return 0
    fi
    if command -v python3 >/dev/null 2>&1; then
        echo "python3"
        return 0
    fi
    if command -v python >/dev/null 2>&1; then
        echo "python"
        return 0
    fi
    echo "未找到可用的 Python 解释器" >&2
    exit 1
}

main() {
    load_env_file "$SCRIPT_DIR/.env"
    local python_bin
    python_bin="$(resolve_python)"
    local browser_channel="${RESOURCE_FILTER_BROWSER_CHANNEL:-chrome}"
    local user_data_dir="${RESOURCE_FILTER_USER_DATA_DIR:-$DEFAULT_XHS_PROFILE}"

    if [[ "$user_data_dir" == "$SCRIPT_DIR/user_data/jimeng_profile" ]]; then
        user_data_dir="$DEFAULT_XHS_PROFILE"
    fi

    cd "$PROJECT_ROOT"
    echo "使用 Python: $python_bin"
    echo "使用用户目录: $user_data_dir"
    exec "$python_bin" -m resource_filter.manual_login --site xhs --browser-channel "$browser_channel" --user-data-dir "$user_data_dir" "$@"
}

main "$@"
