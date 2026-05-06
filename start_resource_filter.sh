#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DEFAULT_JIMENG_USER_DATA_DIR=""
DEFAULT_XHS_USER_DATA_DIR=""
DEFAULT_MJ_USER_DATA_DIR=""
DEFAULT_TAOBAO_USER_DATA_DIR=""
DEFAULT_JINGDONG_USER_DATA_DIR=""
DEFAULT_BAIDU_USER_DATA_DIR=""
DEFAULT_JIMENG_INSPIRATION_URL="https://jimeng.jianying.com/ai-tool/home"
DEFAULT_XHS_INSPIRATION_URL="https://www.xiaohongshu.com/explore"
DEFAULT_POSE_INSPIRATION_URL="https://www.photopose.art/zh/poses?pageSize=96&page=1"
DEFAULT_MJ_INSPIRATION_URL="https://www.midjourney.com/explore?tab=top"
DEFAULT_TAOBAO_INSPIRATION_URL="https://uland.taobao.com/sem/tbsearch"
DEFAULT_JINGDONG_INSPIRATION_URL="https://re.jd.com/search"
DEFAULT_BAIDU_INSPIRATION_URL="https://image.baidu.com/"

if [[ -d "$SCRIPT_DIR/user_data/jimeng_profile" ]]; then
    DEFAULT_JIMENG_USER_DATA_DIR="$SCRIPT_DIR/user_data/jimeng_profile"
elif [[ -d "$SCRIPT_DIR/user_data" ]]; then
    DEFAULT_JIMENG_USER_DATA_DIR="$SCRIPT_DIR/user_data"
fi

if [[ -d "$SCRIPT_DIR/user_data/xhs_profile" ]]; then
    DEFAULT_XHS_USER_DATA_DIR="$SCRIPT_DIR/user_data/xhs_profile"
elif [[ -d "$SCRIPT_DIR/playwright/playwright_user_data" ]]; then
    DEFAULT_XHS_USER_DATA_DIR="$SCRIPT_DIR/playwright/playwright_user_data"
fi

if [[ -d "$SCRIPT_DIR/user_data/mj_profile" ]]; then
    DEFAULT_MJ_USER_DATA_DIR="$SCRIPT_DIR/user_data/mj_profile"
fi

if [[ -d "$SCRIPT_DIR/user_data/taobao_profile" ]]; then
    DEFAULT_TAOBAO_USER_DATA_DIR="$SCRIPT_DIR/user_data/taobao_profile"
fi

if [[ -d "$SCRIPT_DIR/user_data/jingdong_profile" ]]; then
    DEFAULT_JINGDONG_USER_DATA_DIR="$SCRIPT_DIR/user_data/jingdong_profile"
fi

if [[ -d "$SCRIPT_DIR/user_data/baidu_profile" ]]; then
    DEFAULT_BAIDU_USER_DATA_DIR="$SCRIPT_DIR/user_data/baidu_profile"
fi

load_env_file() {
    local env_file="$1"
    if [[ -f "$env_file" ]]; then
        set -a
        # 兼容 Windows CRLF 格式的 .env，避免 source 时出现 $'\r' 报错。
        # shellcheck disable=SC1091
        source /dev/stdin < <(sed 's/\r$//' "$env_file")
        set +a
    fi
}

resolve_python() {
    if [[ -n "$PYTHON_BIN" ]]; then
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

show_usage() {
    cat <<'EOF'
用法:
  ./start_resource_filter.sh [CLI 参数...]

不传参数时，会进入交互式入口，询问你：
  1. 爬哪个目标站点
  2. 抓多少条
  3. 某些站点必填的入口 URL / 作者信息

交互式入口会优先用当前目录下 .env 中的值作为默认值。

如果你直接传 CLI 参数，则按非交互模式执行。可用默认配置包括：
  RESOURCE_FILTER_MODE=inspiration|author
  RESOURCE_FILTER_ENTRY_URL=...
  RESOURCE_FILTER_AUTHOR_URL=...
  RESOURCE_FILTER_AUTHOR_QUERY=...
  RESOURCE_FILTER_KEYWORD=...
  RESOURCE_FILTER_TAB_LIMIT=1
  RESOURCE_FILTER_TAB_NAMES=综合,张力
  RESOURCE_FILTER_SITE=jimeng|xhs|pose|mj|taobao|jingdong|baidu
  RESOURCE_FILTER_STORAGE_STATE=/path/to/state.json
  RESOURCE_FILTER_USER_DATA_DIR=/path/to/user_data_or_profile
  RESOURCE_FILTER_BROWSER_CHANNEL=chrome
  RESOURCE_FILTER_CDP_URL=http://127.0.0.1:9222
  RESOURCE_FILTER_PROXY_SERVER=http://127.0.0.1:7890
  RESOURCE_FILTER_HEADFUL=1
  RESOURCE_FILTER_SLOW_MO=200
  RESOURCE_FILTER_MAX_ITEMS=20
  RESOURCE_FILTER_API_TIMEOUT=120
  RESOURCE_FILTER_API_RETRIES=0
  RESOURCE_FILTER_IMPORT_DELAY=2
  LUNARSAND_API_BASE=http://127.0.0.1:8000/api  # V3 生产可配 https://your-domain.example/api
  LUNARSAND_API_KEY=your-admin-jwt-or-Bearer-token   # V3 短剧后台登录 JWT；可填纯 token 或 Bearer xxx

示例:
  ./start_resource_filter.sh
  ./start_resource_filter.sh inspiration --entry-url "https://jimeng.jianying.com/" --headful --slow-mo 200 --max-items 5
  ./start_resource_filter.sh author --author-url "https://jimeng.jianying.com/u/xxx"
  ./start_resource_filter.sh --site xhs inspiration --keyword "武侠动作参考" --tab-limit 3 --max-items 5
  ./start_resource_filter.sh --site xhs author --author-query "橘困（努力拍照中）"
  ./start_resource_filter.sh --site pose inspiration
  ./start_resource_filter.sh --site mj inspiration --max-items 20
  ./start_resource_filter.sh mj
  ./start_resource_filter.sh mj --max-items 30
  ./start_resource_filter.sh taobao
  ./start_resource_filter.sh taobao "古风衣服 汉服"
  ./start_resource_filter.sh jingdong
  ./start_resource_filter.sh jd "古风衣服 汉服"
  ./start_resource_filter.sh baidu "赵露思"
EOF
}

resolve_default_user_data_dir() {
    case "${1:-}" in
        jimeng)
            echo "$DEFAULT_JIMENG_USER_DATA_DIR"
            ;;
        xhs)
            echo "$DEFAULT_XHS_USER_DATA_DIR"
            ;;
        mj)
            echo "$DEFAULT_MJ_USER_DATA_DIR"
            ;;
        taobao)
            echo "$DEFAULT_TAOBAO_USER_DATA_DIR"
            ;;
        jingdong|jd)
            echo "$DEFAULT_JINGDONG_USER_DATA_DIR"
            ;;
        baidu|bd)
            echo "$DEFAULT_BAIDU_USER_DATA_DIR"
            ;;
        *)
            echo ""
            ;;
    esac
}

normalize_user_data_dir() {
    local configured_dir="${1:-}"
    local site_name="${2:-}"
    local default_dir
    default_dir="$(resolve_default_user_data_dir "$site_name")"

    if [[ -z "$configured_dir" ]]; then
        echo "$default_dir"
        return 0
    fi

    if [[ "$site_name" == "xhs" && -n "$DEFAULT_XHS_USER_DATA_DIR" && "$configured_dir" == "$DEFAULT_JIMENG_USER_DATA_DIR" ]]; then
        echo "$DEFAULT_XHS_USER_DATA_DIR"
        return 0
    fi

    if [[ "$site_name" == "jimeng" && -n "$DEFAULT_JIMENG_USER_DATA_DIR" && "$configured_dir" == "$DEFAULT_XHS_USER_DATA_DIR" ]]; then
        echo "$DEFAULT_JIMENG_USER_DATA_DIR"
        return 0
    fi

    if [[ "$site_name" == "mj" && -n "$DEFAULT_MJ_USER_DATA_DIR" && "$configured_dir" == "$DEFAULT_XHS_USER_DATA_DIR" ]]; then
        echo "$DEFAULT_MJ_USER_DATA_DIR"
        return 0
    fi

    if [[ "$site_name" == "taobao" ]]; then
        if [[ -n "$DEFAULT_TAOBAO_USER_DATA_DIR" ]]; then
            if [[ "$configured_dir" == "$DEFAULT_JIMENG_USER_DATA_DIR" || "$configured_dir" == "$DEFAULT_XHS_USER_DATA_DIR" || "$configured_dir" == "$DEFAULT_MJ_USER_DATA_DIR" ]]; then
                echo "$DEFAULT_TAOBAO_USER_DATA_DIR"
                return 0
            fi
        elif [[ "$configured_dir" == "$DEFAULT_JIMENG_USER_DATA_DIR" || "$configured_dir" == "$DEFAULT_XHS_USER_DATA_DIR" || "$configured_dir" == "$DEFAULT_MJ_USER_DATA_DIR" ]]; then
            echo ""
            return 0
        fi
    fi

    if [[ "$site_name" == "jingdong" || "$site_name" == "jd" ]]; then
        if [[ -n "$DEFAULT_JINGDONG_USER_DATA_DIR" ]]; then
            if [[ "$configured_dir" == "$DEFAULT_JIMENG_USER_DATA_DIR" || "$configured_dir" == "$DEFAULT_XHS_USER_DATA_DIR" || "$configured_dir" == "$DEFAULT_MJ_USER_DATA_DIR" || "$configured_dir" == "$DEFAULT_TAOBAO_USER_DATA_DIR" ]]; then
                echo "$DEFAULT_JINGDONG_USER_DATA_DIR"
                return 0
            fi
        elif [[ "$configured_dir" == "$DEFAULT_JIMENG_USER_DATA_DIR" || "$configured_dir" == "$DEFAULT_XHS_USER_DATA_DIR" || "$configured_dir" == "$DEFAULT_MJ_USER_DATA_DIR" || "$configured_dir" == "$DEFAULT_TAOBAO_USER_DATA_DIR" ]]; then
            echo ""
            return 0
        fi
    fi

    if [[ "$site_name" == "baidu" || "$site_name" == "bd" ]]; then
        if [[ -n "$DEFAULT_BAIDU_USER_DATA_DIR" ]]; then
            if [[ "$configured_dir" == "$DEFAULT_JIMENG_USER_DATA_DIR" || "$configured_dir" == "$DEFAULT_XHS_USER_DATA_DIR" || "$configured_dir" == "$DEFAULT_MJ_USER_DATA_DIR" || "$configured_dir" == "$DEFAULT_TAOBAO_USER_DATA_DIR" || "$configured_dir" == "$DEFAULT_JINGDONG_USER_DATA_DIR" ]]; then
                echo "$DEFAULT_BAIDU_USER_DATA_DIR"
                return 0
            fi
        elif [[ "$configured_dir" == "$DEFAULT_JIMENG_USER_DATA_DIR" || "$configured_dir" == "$DEFAULT_XHS_USER_DATA_DIR" || "$configured_dir" == "$DEFAULT_MJ_USER_DATA_DIR" || "$configured_dir" == "$DEFAULT_TAOBAO_USER_DATA_DIR" || "$configured_dir" == "$DEFAULT_JINGDONG_USER_DATA_DIR" ]]; then
            echo ""
            return 0
        fi
    fi

    echo "$configured_dir"
}

apply_cli_context_overrides() {
    local token=""
    local mode_set="0"

    while [[ "$#" -gt 0 ]]; do
        token="$1"
        case "$token" in
            --site)
                if [[ "$#" -gt 1 ]]; then
                    RESOURCE_FILTER_SITE="$2"
                    shift 2
                    continue
                fi
                ;;
            --site=*)
                RESOURCE_FILTER_SITE="${token#*=}"
                shift
                continue
                ;;
            --user-data-dir)
                if [[ "$#" -gt 1 ]]; then
                    RESOURCE_FILTER_USER_DATA_DIR="$2"
                    shift 2
                    continue
                fi
                ;;
            --user-data-dir=*)
                RESOURCE_FILTER_USER_DATA_DIR="${token#*=}"
                shift
                continue
                ;;
            --entry-url)
                if [[ "$#" -gt 1 ]]; then
                    RESOURCE_FILTER_ENTRY_URL="$2"
                    shift 2
                    continue
                fi
                ;;
            --entry-url=*)
                RESOURCE_FILTER_ENTRY_URL="${token#*=}"
                shift
                continue
                ;;
            --keyword)
                if [[ "$#" -gt 1 ]]; then
                    RESOURCE_FILTER_KEYWORD="$2"
                    shift 2
                    continue
                fi
                ;;
            --keyword=*)
                RESOURCE_FILTER_KEYWORD="${token#*=}"
                shift
                continue
                ;;
            --author-url)
                if [[ "$#" -gt 1 ]]; then
                    RESOURCE_FILTER_AUTHOR_URL="$2"
                    shift 2
                    continue
                fi
                ;;
            --author-url=*)
                RESOURCE_FILTER_AUTHOR_URL="${token#*=}"
                shift
                continue
                ;;
            --author-query)
                if [[ "$#" -gt 1 ]]; then
                    RESOURCE_FILTER_AUTHOR_QUERY="$2"
                    shift 2
                    continue
                fi
                ;;
            --author-query=*)
                RESOURCE_FILTER_AUTHOR_QUERY="${token#*=}"
                shift
                continue
                ;;
            --proxy-server)
                if [[ "$#" -gt 1 ]]; then
                    RESOURCE_FILTER_PROXY_SERVER="$2"
                    shift 2
                    continue
                fi
                ;;
            --proxy-server=*)
                RESOURCE_FILTER_PROXY_SERVER="${token#*=}"
                shift
                continue
                ;;
            --cdp-url)
                if [[ "$#" -gt 1 ]]; then
                    RESOURCE_FILTER_CDP_URL="$2"
                    shift 2
                    continue
                fi
                ;;
            --cdp-url=*)
                RESOURCE_FILTER_CDP_URL="${token#*=}"
                shift
                continue
                ;;
            inspiration|author)
                if [[ "$mode_set" == "0" ]]; then
                    RESOURCE_FILTER_MODE="$token"
                    mode_set="1"
                fi
                shift
                continue
                ;;
            *)
                shift
                continue
                ;;
        esac
        shift
    done
}

build_default_args() {
    local -n output_args_ref="$1"

    if [[ -z "${LUNARSAND_API_BASE:-}" ]]; then
        echo "缺少 LUNARSAND_API_BASE，请在 .env 中配置或运行时传入 --api-base" >&2
        exit 1
    fi
    output_args_ref=(--site "$RESOURCE_FILTER_SITE")

    if [[ -n "$RESOURCE_FILTER_STORAGE_STATE" ]]; then
        output_args_ref+=(--storage-state "$RESOURCE_FILTER_STORAGE_STATE")
    fi
    if [[ -n "$RESOURCE_FILTER_USER_DATA_DIR" ]]; then
        output_args_ref+=(--user-data-dir "$RESOURCE_FILTER_USER_DATA_DIR")
    fi
    if [[ -n "$RESOURCE_FILTER_BROWSER_CHANNEL" ]]; then
        output_args_ref+=(--browser-channel "$RESOURCE_FILTER_BROWSER_CHANNEL")
    fi
    if [[ -n "$RESOURCE_FILTER_CDP_URL" ]]; then
        output_args_ref+=(--cdp-url "$RESOURCE_FILTER_CDP_URL")
    fi
    if [[ -n "$RESOURCE_FILTER_PROXY_SERVER" ]]; then
        output_args_ref+=(--proxy-server "$RESOURCE_FILTER_PROXY_SERVER")
    fi
    if [[ "$RESOURCE_FILTER_HEADFUL" == "1" ]]; then
        output_args_ref+=(--headful)
    fi
    if [[ "$RESOURCE_FILTER_SLOW_MO" != "0" ]]; then
        output_args_ref+=(--slow-mo "$RESOURCE_FILTER_SLOW_MO")
    fi
    if [[ "$RESOURCE_FILTER_MAX_ITEMS" != "0" ]]; then
        output_args_ref+=(--max-items "$RESOURCE_FILTER_MAX_ITEMS")
    fi
    if [[ "$RESOURCE_FILTER_API_TIMEOUT" != "0" ]]; then
        output_args_ref+=(--api-timeout "$RESOURCE_FILTER_API_TIMEOUT")
    fi
    if [[ "$RESOURCE_FILTER_API_RETRIES" != "0" ]]; then
        output_args_ref+=(--api-retries "$RESOURCE_FILTER_API_RETRIES")
    fi
    if [[ "$RESOURCE_FILTER_IMPORT_DELAY" != "0" ]]; then
        output_args_ref+=(--import-delay "$RESOURCE_FILTER_IMPORT_DELAY")
    fi

    case "$RESOURCE_FILTER_MODE" in
        inspiration)
            if [[ -z "$RESOURCE_FILTER_ENTRY_URL" ]]; then
                echo "RESOURCE_FILTER_MODE=inspiration 时必须提供 RESOURCE_FILTER_ENTRY_URL" >&2
                exit 1
            fi
            output_args_ref+=(inspiration --entry-url "$RESOURCE_FILTER_ENTRY_URL")
            if [[ -n "$RESOURCE_FILTER_KEYWORD" ]]; then
                output_args_ref+=(--keyword "$RESOURCE_FILTER_KEYWORD")
            fi
            if [[ "$RESOURCE_FILTER_TAB_LIMIT" != "0" ]]; then
                output_args_ref+=(--tab-limit "$RESOURCE_FILTER_TAB_LIMIT")
            fi
            if [[ -n "$RESOURCE_FILTER_TAB_NAMES" ]]; then
                output_args_ref+=(--tab-names "$RESOURCE_FILTER_TAB_NAMES")
            fi
            ;;
        author)
            if [[ -z "$RESOURCE_FILTER_AUTHOR_URL" && -z "$RESOURCE_FILTER_AUTHOR_QUERY" ]]; then
                echo "RESOURCE_FILTER_MODE=author 时必须提供 RESOURCE_FILTER_AUTHOR_URL 或 RESOURCE_FILTER_AUTHOR_QUERY" >&2
                exit 1
            fi
            output_args_ref+=(author)
            if [[ -n "$RESOURCE_FILTER_AUTHOR_URL" ]]; then
                output_args_ref+=(--author-url "$RESOURCE_FILTER_AUTHOR_URL")
            fi
            if [[ -n "$RESOURCE_FILTER_AUTHOR_QUERY" ]]; then
                output_args_ref+=(--author-query "$RESOURCE_FILTER_AUTHOR_QUERY")
            fi
            ;;
        *)
            echo "不支持的 RESOURCE_FILTER_MODE: $RESOURCE_FILTER_MODE" >&2
            echo "仅支持 inspiration 或 author" >&2
            exit 1
            ;;
    esac
}

append_import_tuning_args() {
    local -n output_args_ref="$1"

    if [[ "$RESOURCE_FILTER_API_TIMEOUT" != "0" ]]; then
        output_args_ref+=(--api-timeout "$RESOURCE_FILTER_API_TIMEOUT")
    fi
    if [[ "$RESOURCE_FILTER_API_RETRIES" != "0" ]]; then
        output_args_ref+=(--api-retries "$RESOURCE_FILTER_API_RETRIES")
    fi
    if [[ "$RESOURCE_FILTER_IMPORT_DELAY" != "0" ]]; then
        output_args_ref+=(--import-delay "$RESOURCE_FILTER_IMPORT_DELAY")
    fi
}

run_taobao_shortcut() {
    local python_bin="$1"
    shift

    local keyword="${RESOURCE_FILTER_KEYWORD:-古风衣服 汉服}"
    if [[ "$#" -gt 0 && "${1:-}" != --* ]]; then
        keyword="$1"
        shift
    fi

    local max_items="${RESOURCE_FILTER_MAX_ITEMS:-50}"
    if [[ -z "$max_items" || "$max_items" == "0" ]]; then
        max_items="50"
    fi

    RESOURCE_FILTER_SITE="taobao"
    RESOURCE_FILTER_MODE="inspiration"
    RESOURCE_FILTER_ENTRY_URL="${RESOURCE_FILTER_ENTRY_URL:-$DEFAULT_TAOBAO_INSPIRATION_URL}"
    RESOURCE_FILTER_KEYWORD="$keyword"
    RESOURCE_FILTER_HEADFUL="1"
    RESOURCE_FILTER_USER_DATA_DIR="$(normalize_user_data_dir "${RESOURCE_FILTER_USER_DATA_DIR:-}" "$RESOURCE_FILTER_SITE")"

    local -a cli_args
    cli_args=(--site taobao)
    if [[ -n "$RESOURCE_FILTER_STORAGE_STATE" ]]; then
        cli_args+=(--storage-state "$RESOURCE_FILTER_STORAGE_STATE")
    fi
    if [[ -n "$RESOURCE_FILTER_USER_DATA_DIR" ]]; then
        cli_args+=(--user-data-dir "$RESOURCE_FILTER_USER_DATA_DIR")
    fi
    if [[ -n "$RESOURCE_FILTER_BROWSER_CHANNEL" ]]; then
        cli_args+=(--browser-channel "$RESOURCE_FILTER_BROWSER_CHANNEL")
    fi
    if [[ -n "$RESOURCE_FILTER_CDP_URL" ]]; then
        cli_args+=(--cdp-url "$RESOURCE_FILTER_CDP_URL")
    fi
    if [[ -n "$RESOURCE_FILTER_PROXY_SERVER" ]]; then
        cli_args+=(--proxy-server "$RESOURCE_FILTER_PROXY_SERVER")
    fi
    cli_args+=(--headful)
    if [[ "$RESOURCE_FILTER_SLOW_MO" != "0" ]]; then
        cli_args+=(--slow-mo "$RESOURCE_FILTER_SLOW_MO")
    fi
    append_import_tuning_args cli_args
    cli_args+=(--max-items "$max_items" inspiration --entry-url "$RESOURCE_FILTER_ENTRY_URL" --keyword "$keyword")

    echo "使用 Python: $python_bin"
    if [[ -n "${RESOURCE_FILTER_USER_DATA_DIR:-}" ]]; then
        echo "使用用户目录: $RESOURCE_FILTER_USER_DATA_DIR"
    fi
    echo "执行淘宝快捷抓取: $python_bin -m resource_filter.cli ${cli_args[*]} $*"
    exec "$python_bin" -m resource_filter.cli "${cli_args[@]}" "$@"
}

run_jingdong_shortcut() {
    local python_bin="$1"
    shift

    local keyword="${RESOURCE_FILTER_KEYWORD:-古风衣服 汉服}"
    if [[ "$#" -gt 0 && "${1:-}" != --* ]]; then
        keyword="$1"
        shift
    fi

    local max_items="${RESOURCE_FILTER_MAX_ITEMS:-50}"
    if [[ -z "$max_items" || "$max_items" == "0" ]]; then
        max_items="50"
    fi

    RESOURCE_FILTER_SITE="jingdong"
    RESOURCE_FILTER_MODE="inspiration"
    RESOURCE_FILTER_ENTRY_URL="${RESOURCE_FILTER_ENTRY_URL:-$DEFAULT_JINGDONG_INSPIRATION_URL}"
    RESOURCE_FILTER_KEYWORD="$keyword"
    RESOURCE_FILTER_HEADFUL="1"
    RESOURCE_FILTER_USER_DATA_DIR="$(normalize_user_data_dir "${RESOURCE_FILTER_USER_DATA_DIR:-}" "$RESOURCE_FILTER_SITE")"

    local -a cli_args
    cli_args=(--site jingdong)
    if [[ -n "$RESOURCE_FILTER_STORAGE_STATE" ]]; then
        cli_args+=(--storage-state "$RESOURCE_FILTER_STORAGE_STATE")
    fi
    if [[ -n "$RESOURCE_FILTER_USER_DATA_DIR" ]]; then
        cli_args+=(--user-data-dir "$RESOURCE_FILTER_USER_DATA_DIR")
    fi
    if [[ -n "$RESOURCE_FILTER_BROWSER_CHANNEL" ]]; then
        cli_args+=(--browser-channel "$RESOURCE_FILTER_BROWSER_CHANNEL")
    fi
    if [[ -n "$RESOURCE_FILTER_CDP_URL" ]]; then
        cli_args+=(--cdp-url "$RESOURCE_FILTER_CDP_URL")
    fi
    if [[ -n "$RESOURCE_FILTER_PROXY_SERVER" ]]; then
        cli_args+=(--proxy-server "$RESOURCE_FILTER_PROXY_SERVER")
    fi
    cli_args+=(--headful)
    if [[ "$RESOURCE_FILTER_SLOW_MO" != "0" ]]; then
        cli_args+=(--slow-mo "$RESOURCE_FILTER_SLOW_MO")
    fi
    append_import_tuning_args cli_args
    cli_args+=(--max-items "$max_items" inspiration --entry-url "$RESOURCE_FILTER_ENTRY_URL" --keyword "$keyword")

    echo "使用 Python: $python_bin"
    if [[ -n "${RESOURCE_FILTER_USER_DATA_DIR:-}" ]]; then
        echo "使用用户目录: $RESOURCE_FILTER_USER_DATA_DIR"
    fi
    echo "执行京东快捷抓取: $python_bin -m resource_filter.cli ${cli_args[*]} $*"
    exec "$python_bin" -m resource_filter.cli "${cli_args[@]}" "$@"
}

run_baidu_shortcut() {
    local python_bin="$1"
    shift

    local keyword="${RESOURCE_FILTER_KEYWORD:-}"
    if [[ "$#" -gt 0 && "${1:-}" != --* ]]; then
        keyword="$1"
        shift
    fi

    if [[ -z "$keyword" ]]; then
        echo "百度快捷抓取需要提供搜索关键词，例如：./start_resource_filter.sh baidu \"赵露思\"" >&2
        exit 1
    fi

    local max_items="${RESOURCE_FILTER_MAX_ITEMS:-50}"
    if [[ -z "$max_items" || "$max_items" == "0" ]]; then
        max_items="50"
    fi

    RESOURCE_FILTER_SITE="baidu"
    RESOURCE_FILTER_MODE="inspiration"
    RESOURCE_FILTER_ENTRY_URL="${RESOURCE_FILTER_ENTRY_URL:-$DEFAULT_BAIDU_INSPIRATION_URL}"
    RESOURCE_FILTER_KEYWORD="$keyword"
    RESOURCE_FILTER_HEADFUL="1"
    RESOURCE_FILTER_USER_DATA_DIR="$(normalize_user_data_dir "${RESOURCE_FILTER_USER_DATA_DIR:-}" "$RESOURCE_FILTER_SITE")"

    local -a cli_args
    cli_args=(--site baidu)
    if [[ -n "$RESOURCE_FILTER_STORAGE_STATE" ]]; then
        cli_args+=(--storage-state "$RESOURCE_FILTER_STORAGE_STATE")
    fi
    if [[ -n "$RESOURCE_FILTER_USER_DATA_DIR" ]]; then
        cli_args+=(--user-data-dir "$RESOURCE_FILTER_USER_DATA_DIR")
    fi
    if [[ -n "$RESOURCE_FILTER_BROWSER_CHANNEL" ]]; then
        cli_args+=(--browser-channel "$RESOURCE_FILTER_BROWSER_CHANNEL")
    fi
    if [[ -n "$RESOURCE_FILTER_CDP_URL" ]]; then
        cli_args+=(--cdp-url "$RESOURCE_FILTER_CDP_URL")
    fi
    if [[ -n "$RESOURCE_FILTER_PROXY_SERVER" ]]; then
        cli_args+=(--proxy-server "$RESOURCE_FILTER_PROXY_SERVER")
    fi
    cli_args+=(--headful)
    if [[ "$RESOURCE_FILTER_SLOW_MO" != "0" ]]; then
        cli_args+=(--slow-mo "$RESOURCE_FILTER_SLOW_MO")
    fi
    append_import_tuning_args cli_args
    cli_args+=(--max-items "$max_items" inspiration --entry-url "$RESOURCE_FILTER_ENTRY_URL" --keyword "$keyword")

    echo "使用 Python: $python_bin"
    if [[ -n "${RESOURCE_FILTER_USER_DATA_DIR:-}" ]]; then
        echo "使用用户目录: $RESOURCE_FILTER_USER_DATA_DIR"
    fi
    echo "执行百度快捷抓取: $python_bin -m resource_filter.cli ${cli_args[*]} $*"
    exec "$python_bin" -m resource_filter.cli "${cli_args[@]}" "$@"
}

run_mj_shortcut() {
    local python_bin="$1"
    shift

    local entry_url="${RESOURCE_FILTER_ENTRY_URL:-$DEFAULT_MJ_INSPIRATION_URL}"
    local cdp_url="${RESOURCE_FILTER_CDP_URL:-http://127.0.0.1:9222}"
    local max_items="60"

    if [[ "${1:-}" == "inspiration" ]]; then
        shift
    fi
    if [[ "$#" -gt 0 && "${1:-}" == http*://* ]]; then
        entry_url="$1"
        shift
    fi

    RESOURCE_FILTER_SITE="mj"
    RESOURCE_FILTER_MODE="inspiration"
    RESOURCE_FILTER_ENTRY_URL="$entry_url"
    RESOURCE_FILTER_CDP_URL="$cdp_url"

    local -a cli_args
    cli_args=(--site mj --cdp-url "$cdp_url")
    append_import_tuning_args cli_args
    cli_args+=(--max-items "$max_items" inspiration --entry-url "$entry_url")

    echo "使用 Python: $python_bin"
    echo "使用 CDP: $cdp_url"
    echo "执行 Midjourney 快捷抓取: $python_bin -m resource_filter.cli ${cli_args[*]} $*"
    exec "$python_bin" -m resource_filter.cli "${cli_args[@]}" "$@"
}

main() {
    load_env_file "$SCRIPT_DIR/.env"

    RESOURCE_FILTER_SITE="${RESOURCE_FILTER_SITE:-jimeng}"
    RESOURCE_FILTER_MODE="${RESOURCE_FILTER_MODE:-inspiration}"
    RESOURCE_FILTER_ENTRY_URL="${RESOURCE_FILTER_ENTRY_URL:-}"
    RESOURCE_FILTER_AUTHOR_URL="${RESOURCE_FILTER_AUTHOR_URL:-}"
    RESOURCE_FILTER_AUTHOR_QUERY="${RESOURCE_FILTER_AUTHOR_QUERY:-}"
    RESOURCE_FILTER_KEYWORD="${RESOURCE_FILTER_KEYWORD:-}"
    RESOURCE_FILTER_TAB_LIMIT="${RESOURCE_FILTER_TAB_LIMIT:-1}"
    RESOURCE_FILTER_TAB_NAMES="${RESOURCE_FILTER_TAB_NAMES:-}"
    RESOURCE_FILTER_STORAGE_STATE="${RESOURCE_FILTER_STORAGE_STATE:-}"
    RESOURCE_FILTER_USER_DATA_DIR="${RESOURCE_FILTER_USER_DATA_DIR:-}"
    RESOURCE_FILTER_BROWSER_CHANNEL="${RESOURCE_FILTER_BROWSER_CHANNEL:-chrome}"
    RESOURCE_FILTER_CDP_URL="${RESOURCE_FILTER_CDP_URL:-}"
    RESOURCE_FILTER_PROXY_SERVER="${RESOURCE_FILTER_PROXY_SERVER:-}"
    RESOURCE_FILTER_HEADFUL="${RESOURCE_FILTER_HEADFUL:-0}"
    RESOURCE_FILTER_SLOW_MO="${RESOURCE_FILTER_SLOW_MO:-0}"
    RESOURCE_FILTER_MAX_ITEMS="${RESOURCE_FILTER_MAX_ITEMS:-0}"
    RESOURCE_FILTER_API_TIMEOUT="${RESOURCE_FILTER_API_TIMEOUT:-120}"
    RESOURCE_FILTER_API_RETRIES="${RESOURCE_FILTER_API_RETRIES:-0}"
    RESOURCE_FILTER_IMPORT_DELAY="${RESOURCE_FILTER_IMPORT_DELAY:-2}"
    PYTHON_BIN="${PYTHON_BIN:-}"

    local python_bin
    python_bin="$(resolve_python)"

    cd "$PROJECT_ROOT"

    if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
        show_usage
        exit 0
    fi

    export RESOURCE_FILTER_DEFAULT_JIMENG_USER_DATA_DIR="$DEFAULT_JIMENG_USER_DATA_DIR"
    export RESOURCE_FILTER_DEFAULT_XHS_USER_DATA_DIR="$DEFAULT_XHS_USER_DATA_DIR"
    export RESOURCE_FILTER_DEFAULT_MJ_USER_DATA_DIR="$DEFAULT_MJ_USER_DATA_DIR"
    export RESOURCE_FILTER_DEFAULT_TAOBAO_USER_DATA_DIR="$DEFAULT_TAOBAO_USER_DATA_DIR"
    export RESOURCE_FILTER_DEFAULT_JINGDONG_USER_DATA_DIR="$DEFAULT_JINGDONG_USER_DATA_DIR"
    export RESOURCE_FILTER_DEFAULT_BAIDU_USER_DATA_DIR="$DEFAULT_BAIDU_USER_DATA_DIR"
    export RESOURCE_FILTER_DEFAULT_JIMENG_ENTRY_URL="$DEFAULT_JIMENG_INSPIRATION_URL"
    export RESOURCE_FILTER_DEFAULT_XHS_ENTRY_URL="$DEFAULT_XHS_INSPIRATION_URL"
    export RESOURCE_FILTER_DEFAULT_POSE_ENTRY_URL="$DEFAULT_POSE_INSPIRATION_URL"
    export RESOURCE_FILTER_DEFAULT_MJ_ENTRY_URL="$DEFAULT_MJ_INSPIRATION_URL"
    export RESOURCE_FILTER_DEFAULT_TAOBAO_ENTRY_URL="$DEFAULT_TAOBAO_INSPIRATION_URL"
    export RESOURCE_FILTER_DEFAULT_JINGDONG_ENTRY_URL="$DEFAULT_JINGDONG_INSPIRATION_URL"
    export RESOURCE_FILTER_DEFAULT_BAIDU_ENTRY_URL="$DEFAULT_BAIDU_INSPIRATION_URL"

    if [[ "$#" -eq 0 ]]; then
        export RESOURCE_FILTER_SITE
        export RESOURCE_FILTER_MODE
        export RESOURCE_FILTER_ENTRY_URL
        export RESOURCE_FILTER_AUTHOR_URL
        export RESOURCE_FILTER_AUTHOR_QUERY
        export RESOURCE_FILTER_KEYWORD
        export RESOURCE_FILTER_TAB_LIMIT
        export RESOURCE_FILTER_TAB_NAMES
        export RESOURCE_FILTER_STORAGE_STATE
        export RESOURCE_FILTER_USER_DATA_DIR
        export RESOURCE_FILTER_BROWSER_CHANNEL
        export RESOURCE_FILTER_CDP_URL
        export RESOURCE_FILTER_PROXY_SERVER
        export RESOURCE_FILTER_HEADFUL
        export RESOURCE_FILTER_SLOW_MO
        export RESOURCE_FILTER_MAX_ITEMS
        export RESOURCE_FILTER_API_TIMEOUT
        export RESOURCE_FILTER_API_RETRIES
        export RESOURCE_FILTER_IMPORT_DELAY
        echo "使用 Python: $python_bin"
        echo "进入交互式抓取入口"
        exec "$python_bin" -m resource_filter.interactive_cli
    fi

    if [[ "${1:-}" == "taobao" || "${1:-}" == "淘宝" ]]; then
        shift
        run_taobao_shortcut "$python_bin" "$@"
    fi
    if [[ "${1:-}" == "jingdong" || "${1:-}" == "jd" || "${1:-}" == "京东" ]]; then
        shift
        run_jingdong_shortcut "$python_bin" "$@"
    fi
    if [[ "${1:-}" == "baidu" || "${1:-}" == "bd" || "${1:-}" == "百度" ]]; then
        shift
        run_baidu_shortcut "$python_bin" "$@"
    fi
    if [[ "${1:-}" == "mj" || "${1:-}" == "MJ" || "${1:-}" == "midjourney" || "${1:-}" == "Midjourney" ]]; then
        shift
        run_mj_shortcut "$python_bin" "$@"
    fi

    apply_cli_context_overrides "$@"

    if [[ -z "$RESOURCE_FILTER_ENTRY_URL" && "$RESOURCE_FILTER_SITE" == "jimeng" && "$RESOURCE_FILTER_MODE" == "inspiration" ]]; then
        RESOURCE_FILTER_ENTRY_URL="$DEFAULT_JIMENG_INSPIRATION_URL"
    fi
    if [[ -z "$RESOURCE_FILTER_ENTRY_URL" && "$RESOURCE_FILTER_SITE" == "xhs" && "$RESOURCE_FILTER_MODE" == "inspiration" ]]; then
        RESOURCE_FILTER_ENTRY_URL="$DEFAULT_XHS_INSPIRATION_URL"
    fi
    if [[ -z "$RESOURCE_FILTER_ENTRY_URL" && "$RESOURCE_FILTER_SITE" == "taobao" && "$RESOURCE_FILTER_MODE" == "inspiration" ]]; then
        RESOURCE_FILTER_ENTRY_URL="$DEFAULT_TAOBAO_INSPIRATION_URL"
    fi
    if [[ -z "$RESOURCE_FILTER_ENTRY_URL" && ( "$RESOURCE_FILTER_SITE" == "jingdong" || "$RESOURCE_FILTER_SITE" == "jd" ) && "$RESOURCE_FILTER_MODE" == "inspiration" ]]; then
        RESOURCE_FILTER_ENTRY_URL="$DEFAULT_JINGDONG_INSPIRATION_URL"
    fi
    if [[ -z "$RESOURCE_FILTER_ENTRY_URL" && ( "$RESOURCE_FILTER_SITE" == "baidu" || "$RESOURCE_FILTER_SITE" == "bd" ) && "$RESOURCE_FILTER_MODE" == "inspiration" ]]; then
        RESOURCE_FILTER_ENTRY_URL="$DEFAULT_BAIDU_INSPIRATION_URL"
    fi
    if [[ -z "$RESOURCE_FILTER_ENTRY_URL" && "$RESOURCE_FILTER_SITE" == "mj" && "$RESOURCE_FILTER_MODE" == "inspiration" ]]; then
        RESOURCE_FILTER_ENTRY_URL="$DEFAULT_MJ_INSPIRATION_URL"
    fi
    RESOURCE_FILTER_USER_DATA_DIR="$(normalize_user_data_dir "${RESOURCE_FILTER_USER_DATA_DIR:-}" "$RESOURCE_FILTER_SITE")"

    export RESOURCE_FILTER_SITE
    export RESOURCE_FILTER_MODE
    export RESOURCE_FILTER_ENTRY_URL
    export RESOURCE_FILTER_AUTHOR_URL
    export RESOURCE_FILTER_AUTHOR_QUERY
    export RESOURCE_FILTER_KEYWORD
    export RESOURCE_FILTER_TAB_LIMIT
    export RESOURCE_FILTER_TAB_NAMES
    export RESOURCE_FILTER_STORAGE_STATE
    export RESOURCE_FILTER_USER_DATA_DIR
    export RESOURCE_FILTER_BROWSER_CHANNEL
    export RESOURCE_FILTER_CDP_URL
    export RESOURCE_FILTER_PROXY_SERVER
    export RESOURCE_FILTER_HEADFUL
    export RESOURCE_FILTER_SLOW_MO
    export RESOURCE_FILTER_MAX_ITEMS
    export RESOURCE_FILTER_API_TIMEOUT
    export RESOURCE_FILTER_API_RETRIES
    export RESOURCE_FILTER_IMPORT_DELAY

    local -a cli_args
    cli_args=("$@")

    echo "使用 Python: $python_bin"
    if [[ -n "${RESOURCE_FILTER_USER_DATA_DIR:-}" ]]; then
        echo "使用用户目录: $RESOURCE_FILTER_USER_DATA_DIR"
    fi
    echo "执行抓取命令: $python_bin -m resource_filter.cli ${cli_args[*]}"
    exec "$python_bin" -m resource_filter.cli "${cli_args[@]}"
}

main "$@"
