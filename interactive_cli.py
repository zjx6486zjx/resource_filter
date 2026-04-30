from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from resource_filter import cli as cli_module
from resource_filter.utils import normalize_optional_text, normalize_text


SITE_CHOICES = (
    ("jimeng", "即梦"),
    ("xhs", "小红书"),
    ("pose", "PhotoPose"),
    ("mj", "Midjourney"),
    ("taobao", "淘宝商品"),
    ("jingdong", "京东商品"),
    ("baidu", "百度图片"),
)

SITE_MODE_CHOICES = {
    "jimeng": ("inspiration", "author"),
    "xhs": ("inspiration", "author"),
    "pose": ("inspiration",),
    "mj": ("inspiration",),
    "taobao": ("inspiration",),
    "jingdong": ("inspiration",),
    "baidu": ("inspiration",),
}


@dataclass
class InteractiveAnswers:
    site: str
    mode: str
    max_items: int
    entry_url: str = ""
    keyword: str = ""
    author_url: str = ""
    author_query: str = ""
    tab_limit: int = 0
    tab_names: str = ""
    proxy_server: str = ""


def main() -> int:
    answers = collect_answers()
    argv = build_cli_args(answers)
    print(f"即将执行: python -m resource_filter.cli {_format_command_args(argv)}", flush=True)
    return cli_module.main(argv)


def _format_command_args(argv: list[str]) -> str:
    masked_args: list[str] = []
    mask_next = False
    for token in argv:
        if mask_next:
            masked_args.append("***")
            mask_next = False
            continue
        if token == "--api-key":
            masked_args.append(token)
            mask_next = True
            continue
        if token.startswith("--api-key="):
            masked_args.append("--api-key=***")
            continue
        masked_args.append(token)
    return " ".join(masked_args)


def collect_answers() -> InteractiveAnswers:
    default_site = normalize_text(os.getenv("RESOURCE_FILTER_SITE") or "jimeng").lower()
    if default_site not in {choice[0] for choice in SITE_CHOICES}:
        default_site = "jimeng"

    site = prompt_choice(
        "要爬哪个目标？",
        SITE_CHOICES,
        default=default_site,
    )

    site_modes = SITE_MODE_CHOICES[site]
    default_mode = normalize_text(os.getenv("RESOURCE_FILTER_MODE") or site_modes[0]).lower()
    if default_mode not in site_modes:
        default_mode = site_modes[0]

    mode = site_modes[0]
    if len(site_modes) > 1:
        mode = prompt_choice(
            "要爬灵感流还是作者页？",
            tuple((value, "灵感流" if value == "inspiration" else "作者页") for value in site_modes),
            default=default_mode,
        )

    max_items = prompt_positive_int(
        "要抓多少条？",
        default=int(os.getenv("RESOURCE_FILTER_MAX_ITEMS", "50") or "50"),
    )

    answers = InteractiveAnswers(site=site, mode=mode, max_items=max_items)
    if site == "mj":
        answers.proxy_server = prompt_text(
            "MJ 代理地址（留空则不用，例如 http://127.0.0.1:7890）",
            default=normalize_text(os.getenv("RESOURCE_FILTER_PROXY_SERVER")),
            required=False,
        )

    if mode == "inspiration":
        answers.entry_url = resolve_inspiration_entry_url(site)
        if site == "xhs":
            answers.entry_url, answers.keyword = resolve_xhs_inspiration_inputs(answers.entry_url)
            answers.tab_limit = prompt_positive_int(
                "小红书要依次切换几个标签页？",
                default=int(os.getenv("RESOURCE_FILTER_TAB_LIMIT", "1") or "1"),
            )
            answers.tab_names = prompt_text(
                "指定标签名，逗号分隔（留空则从左到右自动切换）",
                default=normalize_text(os.getenv("RESOURCE_FILTER_TAB_NAMES")),
                required=False,
            )
        elif site == "taobao":
            answers.keyword = prompt_text(
                "淘宝搜索关键词",
                default=normalize_text(os.getenv("RESOURCE_FILTER_KEYWORD")),
                required=True,
            )
        elif site == "jingdong":
            answers.keyword = prompt_text(
                "京东搜索关键词",
                default=normalize_text(os.getenv("RESOURCE_FILTER_KEYWORD")),
                required=True,
            )
        elif site == "baidu":
            answers.keyword = prompt_text(
                "百度搜索关键词",
                default=normalize_text(os.getenv("RESOURCE_FILTER_KEYWORD")),
                required=True,
            )
    else:
        if site == "jimeng":
            answers.author_url = prompt_text(
                "请输入即梦作者主页 URL",
                default=normalize_text(os.getenv("RESOURCE_FILTER_AUTHOR_URL")),
                required=True,
            )
        elif site == "xhs":
            target = prompt_text(
                "请输入小红书作者主页 URL 或作者名称",
                default=normalize_text(os.getenv("RESOURCE_FILTER_AUTHOR_URL") or os.getenv("RESOURCE_FILTER_AUTHOR_QUERY")),
                required=True,
            )
            if looks_like_url(target):
                answers.author_url = target
            else:
                answers.author_query = target

    return answers


def build_cli_args(answers: InteractiveAnswers) -> list[str]:
    args = ["--site", answers.site]

    api_base = normalize_text(os.getenv("LUNARSAND_API_BASE", "http://127.0.0.1:8000/api"))
    args.extend(["--api-base", api_base])

    api_key = normalize_text(os.getenv("LUNARSAND_API_KEY"))
    if api_key:
        args.extend(["--api-key", api_key])

    storage_state = normalize_text(os.getenv("RESOURCE_FILTER_STORAGE_STATE"))
    if storage_state:
        args.extend(["--storage-state", storage_state])

    user_data_dir = resolve_user_data_dir(answers.site)
    if user_data_dir:
        args.extend(["--user-data-dir", user_data_dir])

    browser_channel = normalize_text(os.getenv("RESOURCE_FILTER_BROWSER_CHANNEL"))
    if browser_channel:
        args.extend(["--browser-channel", browser_channel])

    proxy_server = normalize_text(answers.proxy_server or os.getenv("RESOURCE_FILTER_PROXY_SERVER"))
    if proxy_server:
        args.extend(["--proxy-server", proxy_server])

    if env_flag_is_true(os.getenv("RESOURCE_FILTER_HEADFUL")):
        args.append("--headful")

    slow_mo = normalize_text(os.getenv("RESOURCE_FILTER_SLOW_MO"))
    if slow_mo and slow_mo != "0":
        args.extend(["--slow-mo", slow_mo])

    api_timeout = normalize_text(os.getenv("RESOURCE_FILTER_API_TIMEOUT"))
    if api_timeout:
        args.extend(["--api-timeout", api_timeout])

    api_retries = normalize_text(os.getenv("RESOURCE_FILTER_API_RETRIES"))
    if api_retries:
        args.extend(["--api-retries", api_retries])

    import_delay = normalize_text(os.getenv("RESOURCE_FILTER_IMPORT_DELAY"))
    if import_delay:
        args.extend(["--import-delay", import_delay])

    args.extend(["--max-items", str(answers.max_items), answers.mode])

    if answers.mode == "inspiration":
        if normalize_optional_text(answers.entry_url):
            args.extend(["--entry-url", answers.entry_url])
        if normalize_optional_text(answers.keyword):
            args.extend(["--keyword", answers.keyword])

        tab_limit = str(answers.tab_limit or normalize_text(os.getenv("RESOURCE_FILTER_TAB_LIMIT")))
        if tab_limit and tab_limit != "0":
            args.extend(["--tab-limit", tab_limit])

        tab_names = normalize_text(answers.tab_names or os.getenv("RESOURCE_FILTER_TAB_NAMES"))
        if tab_names:
            args.extend(["--tab-names", tab_names])
    else:
        if normalize_optional_text(answers.author_url):
            args.extend(["--author-url", answers.author_url])
        if normalize_optional_text(answers.author_query):
            args.extend(["--author-query", answers.author_query])

    return args


def resolve_inspiration_entry_url(site: str) -> str:
    env_entry = normalize_text(os.getenv("RESOURCE_FILTER_ENTRY_URL"))
    default_entry = default_entry_url_for_site(site)

    return prompt_text(
        "入口 URL",
        default=env_entry or default_entry,
        required=site in {"jimeng", "pose", "mj"},
    )


def resolve_xhs_inspiration_inputs(current_entry_url: str) -> tuple[str, str]:
    entry_url = current_entry_url
    keyword_default = normalize_text(os.getenv("RESOURCE_FILTER_KEYWORD"))

    while True:
        keyword = prompt_text(
            "小红书搜索关键词（如果入口已经是搜索结果页，可以留空）",
            default=keyword_default,
            required=False,
        )
        if normalize_optional_text(keyword) or looks_like_xhs_search_result_url(entry_url):
            return entry_url, keyword
        print("小红书灵感模式需要关键词，或者直接提供搜索结果页 URL。")
        entry_url = prompt_text("入口 URL", default=entry_url, required=True)


def resolve_user_data_dir(site: str) -> str:
    configured = normalize_text(os.getenv("RESOURCE_FILTER_USER_DATA_DIR"))
    default_jimeng = normalize_text(os.getenv("RESOURCE_FILTER_DEFAULT_JIMENG_USER_DATA_DIR"))
    default_xhs = normalize_text(os.getenv("RESOURCE_FILTER_DEFAULT_XHS_USER_DATA_DIR"))
    default_mj = normalize_text(os.getenv("RESOURCE_FILTER_DEFAULT_MJ_USER_DATA_DIR"))
    default_taobao = normalize_text(os.getenv("RESOURCE_FILTER_DEFAULT_TAOBAO_USER_DATA_DIR"))
    default_jingdong = normalize_text(os.getenv("RESOURCE_FILTER_DEFAULT_JINGDONG_USER_DATA_DIR"))
    default_baidu = normalize_text(os.getenv("RESOURCE_FILTER_DEFAULT_BAIDU_USER_DATA_DIR"))

    defaults = {
        "jimeng": default_jimeng,
        "xhs": default_xhs,
        "mj": default_mj,
        "taobao": default_taobao,
        "jingdong": default_jingdong,
        "baidu": default_baidu,
    }

    if not configured:
        return defaults.get(site, "")

    if site == "jimeng" and configured == default_xhs and default_jimeng:
        return default_jimeng
    if site == "xhs" and configured == default_jimeng and default_xhs:
        return default_xhs
    if site == "taobao" and configured in {default_jimeng, default_xhs, default_mj}:
        return default_taobao
    if site == "jingdong" and configured in {default_jimeng, default_xhs, default_mj, default_taobao}:
        return default_jingdong
    if site == "baidu" and configured in {default_jimeng, default_xhs, default_mj, default_taobao, default_jingdong}:
        return default_baidu
    return configured


def default_entry_url_for_site(site: str) -> str:
    overrides = {
        "jimeng": normalize_text(os.getenv("RESOURCE_FILTER_DEFAULT_JIMENG_ENTRY_URL")),
        "xhs": normalize_text(os.getenv("RESOURCE_FILTER_DEFAULT_XHS_ENTRY_URL")),
        "pose": normalize_text(os.getenv("RESOURCE_FILTER_DEFAULT_POSE_ENTRY_URL")),
        "mj": normalize_text(os.getenv("RESOURCE_FILTER_DEFAULT_MJ_ENTRY_URL")),
        "taobao": normalize_text(os.getenv("RESOURCE_FILTER_DEFAULT_TAOBAO_ENTRY_URL")),
        "jingdong": normalize_text(os.getenv("RESOURCE_FILTER_DEFAULT_JINGDONG_ENTRY_URL")),
        "baidu": normalize_text(os.getenv("RESOURCE_FILTER_DEFAULT_BAIDU_ENTRY_URL")),
    }
    return overrides.get(site, "") or {
        "jimeng": "https://jimeng.jianying.com/ai-tool/home",
        "xhs": "https://www.xiaohongshu.com/explore",
        "pose": "https://www.photopose.art/zh/poses?pageSize=96&page=1",
        "mj": "https://www.midjourney.com/explore?tab=top",
        "taobao": "https://uland.taobao.com/sem/tbsearch",
        "jingdong": "https://re.jd.com/search",
        "baidu": "https://image.baidu.com/",
    }.get(site, "")


def prompt_choice(prompt: str, choices: tuple[tuple[str, str], ...], *, default: str) -> str:
    value_to_index = {value: str(index) for index, (value, _label) in enumerate(choices, start=1)}
    index_to_value = {str(index): value for index, (value, _label) in enumerate(choices, start=1)}

    print(prompt)
    for index, (value, label) in enumerate(choices, start=1):
        suffix = " (默认)" if value == default else ""
        print(f"  {index}. {label} [{value}]{suffix}")

    while True:
        raw = normalize_text(input(f"请输入序号，直接回车默认 {value_to_index.get(default, '1')}: "))
        if not raw:
            return default
        if raw in index_to_value:
            return index_to_value[raw]

        normalized = raw.lower()
        if normalized in value_to_index:
            return normalized

        print("输入无效，请重新选择。")


def prompt_text(prompt: str, *, default: str = "", required: bool = False) -> str:
    while True:
        if default:
            raw = input(f"{prompt} [{default}]: ")
        else:
            raw = input(f"{prompt}: ")
        value = normalize_text(raw)
        if value:
            return value
        if default:
            return default
        if not required:
            return ""
        print("这个值不能为空。")


def prompt_positive_int(prompt: str, *, default: int) -> int:
    while True:
        raw = normalize_text(input(f"{prompt} [{default}]: "))
        if not raw:
            return max(default, 1)
        if raw.isdigit() and int(raw) > 0:
            return int(raw)
        print("请输入大于 0 的整数。")


def looks_like_url(value: str) -> bool:
    normalized = normalize_text(value)
    return normalized.startswith("http://") or normalized.startswith("https://")


def looks_like_xhs_search_result_url(url: str) -> bool:
    normalized = normalize_text(url)
    return "xiaohongshu.com/search_result" in normalized or "xiaohongshu.com/explore/" in normalized


def env_flag_is_true(raw_value: str | None) -> bool:
    return normalize_text(raw_value).lower() in {"1", "true", "yes", "y", "on"}


if __name__ == "__main__":
    sys.exit(main())
