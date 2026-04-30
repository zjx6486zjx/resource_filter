from __future__ import annotations

import argparse
import os
import sys

from resource_filter.adapters import BaiduAdapter, JimengAdapter, JingdongAdapter, MjAdapter, PoseAdapter, TaobaoAdapter, XhsAdapter
from resource_filter.lunarsand_client import LunarsandApiClient
from resource_filter.scraper import PlaywrightSiteCrawler
from resource_filter.utils import normalize_text

GLOBAL_OPTIONS_WITH_VALUE = {
    "--site",
    "--api-base",
    "--api-key",
    "--storage-state",
    "--user-data-dir",
    "--browser-channel",
    "--cdp-url",
    "--proxy-server",
    "--slow-mo",
    "--max-items",
    "--api-timeout",
    "--api-retries",
    "--import-delay",
}
GLOBAL_FLAG_OPTIONS = {
    "--headful",
}


def normalize_cli_args(argv: list[str]) -> list[str]:
    """
    argparse 默认只接受子命令前面的全局参数。
    这里把全局参数提到前面，让下面两种写法都成立：
    - python -m resource_filter.cli --headful inspiration --entry-url ...
    - python -m resource_filter.cli inspiration --entry-url ... --headful
    """

    global_args: list[str] = []
    remaining_args: list[str] = []
    index = 0

    while index < len(argv):
        token = argv[index]
        option_name, has_inline_value, _ = token.partition("=")

        if token in GLOBAL_FLAG_OPTIONS:
            global_args.append(token)
            index += 1
            continue

        if option_name in GLOBAL_OPTIONS_WITH_VALUE:
            global_args.append(token)
            if not has_inline_value:
                next_index = index + 1
                if next_index < len(argv):
                    global_args.append(argv[next_index])
                index += 2
                continue
            index += 1
            continue

        remaining_args.append(token)
        index += 1

    return global_args + remaining_args


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="通用灵感站点抓取入口")
    parser.add_argument("--site", default="jimeng", help="站点适配器名称，当前支持 jimeng、xhs、pose、mj、taobao、jingdong、baidu")
    parser.add_argument("--api-base", default=os.getenv("LUNARSAND_API_BASE", "http://127.0.0.1:8000/api"))
    parser.add_argument("--api-key", default=os.getenv("LUNARSAND_API_KEY", ""))
    parser.add_argument("--storage-state", default=os.getenv("RESOURCE_FILTER_STORAGE_STATE", ""))
    parser.add_argument(
        "--user-data-dir",
        default=os.getenv("RESOURCE_FILTER_USER_DATA_DIR", ""),
        help="Playwright 持久化用户目录，适合直接复用目标站点登录态",
    )
    parser.add_argument(
        "--browser-channel",
        default=os.getenv("RESOURCE_FILTER_BROWSER_CHANNEL", ""),
        help="优先使用的浏览器通道，例如 chrome、msedge",
    )
    parser.add_argument(
        "--proxy-server",
        default=os.getenv("RESOURCE_FILTER_PROXY_SERVER", ""),
        help="Playwright 浏览器代理，例如 http://127.0.0.1:7890 或 socks5://127.0.0.1:7890",
    )
    parser.add_argument(
        "--cdp-url",
        default=os.getenv("RESOURCE_FILTER_CDP_URL", ""),
        help="连接已打开 Chrome 的 CDP 地址，例如 http://127.0.0.1:9222",
    )
    parser.add_argument("--headful", action="store_true", help="使用有头浏览器运行，方便人工观察")
    parser.add_argument("--slow-mo", type=int, default=0, help="Playwright slow_mo，毫秒")
    parser.add_argument(
        "--max-items",
        type=int,
        default=0,
        help="最多抓取多少张；xhs inspiration 模式下表示每个标签最多抓取多少张",
    )
    parser.add_argument(
        "--api-timeout",
        type=float,
        default=float(os.getenv("RESOURCE_FILTER_API_TIMEOUT", "120") or "120"),
        help="等待 Lunarsand 导入接口响应的秒数",
    )
    parser.add_argument(
        "--api-retries",
        type=int,
        default=int(os.getenv("RESOURCE_FILTER_API_RETRIES", "0") or "0"),
        help="Lunarsand 导入接口连接超时/中断时的重试次数",
    )
    parser.add_argument(
        "--import-delay",
        type=float,
        default=float(os.getenv("RESOURCE_FILTER_IMPORT_DELAY", "2") or "2"),
        help="每次提交后端导入后暂停的秒数，用于降低服务器读写压力",
    )

    subparsers = parser.add_subparsers(dest="mode", required=True)

    inspiration_parser = subparsers.add_parser("inspiration", help="从灵感/首页作品流抓取")
    inspiration_parser.add_argument(
        "--entry-url",
        default=os.getenv("RESOURCE_FILTER_ENTRY_URL", ""),
        help="站点入口 URL；xhs 可留空，默认进入 explore 页",
    )
    inspiration_parser.add_argument(
        "--keyword",
        default=os.getenv("RESOURCE_FILTER_KEYWORD", ""),
        help="搜索关键词；xhs、taobao、jingdong、baidu inspiration 模式建议显式提供",
    )
    inspiration_parser.add_argument(
        "--tab-limit",
        type=int,
        default=int(os.getenv("RESOURCE_FILTER_TAB_LIMIT", "1") or "1"),
        help="xhs inspiration 模式下最多切换多少个搜索标签",
    )
    inspiration_parser.add_argument(
        "--tab-names",
        default=os.getenv("RESOURCE_FILTER_TAB_NAMES", ""),
        help="xhs inspiration 模式下显式指定标签名，逗号分隔，例如 综合,张力,素材",
    )

    author_parser = subparsers.add_parser("author", help="从作者主页抓取")
    author_parser.add_argument(
        "--author-url",
        default=os.getenv("RESOURCE_FILTER_AUTHOR_URL", ""),
        help="作者主页 URL；xhs 下可不传，改用 --author-query",
    )
    author_parser.add_argument(
        "--author-query",
        default=os.getenv("RESOURCE_FILTER_AUTHOR_QUERY", ""),
        help="作者名称；仅在 xhs author 模式下生效",
    )
    return parser


def build_adapter(site_name: str):
    normalized_site_name = normalize_text(site_name).lower()
    if normalized_site_name == "jimeng":
        return JimengAdapter()
    if normalized_site_name == "xhs":
        return XhsAdapter()
    if normalized_site_name == "pose":
        return PoseAdapter()
    if normalized_site_name == "mj":
        return MjAdapter()
    if normalized_site_name == "taobao":
        return TaobaoAdapter()
    if normalized_site_name in {"jingdong", "jd"}:
        return JingdongAdapter()
    if normalized_site_name in {"baidu", "bd"}:
        return BaiduAdapter()
    raise ValueError(f"暂不支持站点适配器：{site_name}")


def main(argv: list[str] | None = None) -> int:
    normalized_argv = normalize_cli_args(list(argv if argv is not None else sys.argv[1:]))
    parser = build_parser()
    args = parser.parse_args(normalized_argv)

    api_client = LunarsandApiClient(
        base_url=args.api_base,
        api_key=args.api_key,
        timeout_seconds=max(args.api_timeout, 1),
        retry_attempts=max(args.api_retries, 0),
    )
    adapter = build_adapter(args.site)
    crawler = PlaywrightSiteCrawler(
        adapter=adapter,
        api_client=api_client,
        headless=not args.headful,
        storage_state=normalize_text(args.storage_state) or None,
        user_data_dir=normalize_text(args.user_data_dir) or None,
        browser_channel=normalize_text(args.browser_channel) or None,
        cdp_url=normalize_text(args.cdp_url) or None,
        proxy_server=normalize_text(args.proxy_server) or None,
        slow_mo_ms=max(args.slow_mo, 0),
        max_items=(args.max_items if args.max_items > 0 else None),
        import_delay_seconds=max(args.import_delay, 0),
    )

    if args.mode == "inspiration":
        if adapter.site_name == "jimeng" and not normalize_text(args.entry_url):
            parser.error("jimeng inspiration 模式必须提供 --entry-url")
        if adapter.site_name in {"taobao", "jingdong", "baidu"} and not (
            normalize_text(args.entry_url) or normalize_text(args.keyword)
        ):
            parser.error(f"{adapter.site_name} inspiration 模式必须提供 --keyword 或 --entry-url")

        tab_names = [part.strip() for part in str(args.tab_names or "").split(",") if part.strip()]
        summary = crawler.crawl_inspiration(
            normalize_text(args.entry_url),
            keyword=normalize_text(args.keyword) or None,
            tab_limit=(args.tab_limit if args.tab_limit > 0 else None),
            tab_names=tab_names,
        )
    else:
        author_url = normalize_text(args.author_url)
        author_query = normalize_text(args.author_query)

        if adapter.site_name == "jimeng" and not author_url:
            parser.error("jimeng author 模式必须提供 --author-url")
        if adapter.site_name == "xhs" and not (author_url or author_query):
            parser.error("xhs author 模式必须提供 --author-url 或 --author-query")

        summary = crawler.crawl_author(
            author_url or author_query,
            author_query=(author_query or None),
        )

    print(
        f"完成：processed={summary.processed}, imported={summary.imported}, skipped={summary.skipped}, failed={summary.failed}"
    )
    return 0 if summary.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
