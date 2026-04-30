from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import shutil
import tempfile
import os
import time
from typing import Any, Callable, List, Optional, TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from playwright.sync_api import Browser, BrowserContext, Page, Playwright
else:
    try:
        from playwright.sync_api import Browser, BrowserContext, Page, Playwright
    except ModuleNotFoundError:
        Browser = Any
        BrowserContext = Any
        Page = Any
        Playwright = Any

try:
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError:
    def sync_playwright():
        raise ModuleNotFoundError("playwright.sync_api is required to run the crawler")

from resource_filter.adapters.base import SiteAdapter
from resource_filter.dedupe_cache import ScrapeItemDedupeCache
from resource_filter.exceptions import SkipScrapeItem
from resource_filter.image_validation import (
    MAX_IMAGE_BYTES_TO_INSPECT,
    MIN_IMAGE_HEIGHT,
    MIN_IMAGE_WIDTH,
    ImageValidationResult,
    looks_like_thumbnail_url,
    promoted_image_url_candidates,
    validate_data_image_url,
    validate_image_bytes,
)
from resource_filter.lunarsand_client import LunarsandApiClient, LunarsandApiRequestError
from resource_filter.models import FeedCardRef, ScrapeItemPayload
from resource_filter.utils import normalize_optional_text, normalize_text


@dataclass
class CrawlSummary:
    processed: int = 0
    imported: int = 0
    skipped: int = 0
    failed: int = 0


class PlaywrightSiteCrawler:
    VIDEO_FILE_EXTENSIONS = (
        ".mp4",
        ".mov",
        ".m4v",
        ".webm",
        ".avi",
        ".mkv",
        ".flv",
        ".wmv",
        ".m3u8",
    )
    PROFILE_TRANSIENT_NAMES = {
        "LOCK",
        "SingletonCookie",
        "SingletonLock",
        "SingletonSocket",
    }
    PROFILE_IGNORED_DIR_NAMES = {
        "BrowserMetrics",
        "Cache",
        "Code Cache",
        "component_crx_cache",
        "Crash Reports",
        "DawnGraphiteCache",
        "DawnWebGPUCache",
        "extensions_crx_cache",
        "GPUCache",
        "GraphiteDawnCache",
        "GrShaderCache",
        "ShaderCache",
    }

    def __init__(
        self,
        adapter: SiteAdapter,
        api_client: LunarsandApiClient,
        *,
        headless: bool = True,
        storage_state: Optional[str] = None,
        user_data_dir: Optional[str] = None,
        browser_channel: Optional[str] = None,
        cdp_url: Optional[str] = None,
        proxy_server: Optional[str] = None,
        slow_mo_ms: int = 0,
        max_items: Optional[int] = None,
        import_delay_seconds: float = 0,
    ):
        self.adapter = adapter
        self.api_client = api_client
        self.headless = headless
        self.storage_state = storage_state
        self.user_data_dir = user_data_dir
        self.browser_channel = browser_channel
        self.cdp_url = normalize_optional_text(cdp_url)
        self.proxy_server = self._normalize_proxy_server(proxy_server)
        self.slow_mo_ms = slow_mo_ms
        self.max_items = max_items
        self.import_delay_seconds = max(float(import_delay_seconds), 0)

    def crawl_inspiration(self, entry_url: str, **mode_kwargs) -> CrawlSummary:
        return self._crawl(
            lambda page: self.adapter.open_inspiration(page, entry_url, **mode_kwargs),
            crawl_mode="inspiration",
            mode_kwargs=mode_kwargs,
        )

    def crawl_author(self, author_url: str, **mode_kwargs) -> CrawlSummary:
        return self._crawl(
            lambda page: self.adapter.open_author_page(page, author_url, **mode_kwargs),
            crawl_mode="author",
            mode_kwargs=mode_kwargs,
        )

    def _crawl(
        self,
        open_feed: Callable[[Page], None],
        *,
        crawl_mode: str,
        mode_kwargs: dict,
    ) -> CrawlSummary:
        summary = CrawlSummary()
        runtime_user_data_dir: Optional[Path] = None
        dedupe_cache = ScrapeItemDedupeCache()
        seen_card_keys: set[str] = set()
        attempted_card_keys: set[str] = set()

        with sync_playwright() as playwright:
            print(
                f"启动抓取：site={self.adapter.site_name} mode={crawl_mode} max_items={self.max_items or '不限'}",
                flush=True,
            )
            print("准备启动浏览器...", flush=True)
            browser, context, page, runtime_user_data_dir = self._open_browser(playwright)
            try:
                print("浏览器已打开，开始进入目标页面...", flush=True)
                open_feed(page)
                print("目标页面准备完成，开始收集列表卡片...", flush=True)
                incremental_collection = self._adapter_collects_incrementally()
                card_refs = self.adapter.collect_feed_cards(
                    page,
                    max_items=self._next_collection_limit(attempted_card_keys, summary),
                    crawl_mode=crawl_mode,
                    skip_external_item_ids=dedupe_cache.external_item_ids_for_site(self.adapter.site_name),
                    **mode_kwargs,
                )
                if incremental_collection:
                    print(f"列表卡片首批收集完成：{len(card_refs)} 个，开始边抓边滚动导入审核队列...", flush=True)
                else:
                    print(f"列表卡片收集完成：{len(card_refs)} 个，开始导入审核队列...", flush=True)
                if not card_refs:
                    print("未发现可抓取的作品卡片。")
                    return summary

                ordinal = 0
                stop_processing = False
                while True:
                    pending_card_refs: list[FeedCardRef] = []
                    for card_ref in card_refs:
                        card_dedupe_key = self._build_card_dedupe_key(card_ref)
                        if card_dedupe_key and card_dedupe_key in attempted_card_keys:
                            continue
                        pending_card_refs.append(card_ref)

                    if not pending_card_refs:
                        if self.max_items and summary.imported >= self.max_items:
                            break
                        if incremental_collection and not self._load_more_feed_cards(
                            page,
                            crawl_mode=crawl_mode,
                            mode_kwargs=mode_kwargs,
                        ):
                            break
                        card_refs = self.adapter.collect_feed_cards(
                            page,
                            max_items=self._next_collection_limit(attempted_card_keys, summary),
                            crawl_mode=crawl_mode,
                            skip_external_item_ids=dedupe_cache.external_item_ids_for_site(self.adapter.site_name),
                            **mode_kwargs,
                        )
                        if not incremental_collection and len(card_refs) <= len(attempted_card_keys):
                            break
                        continue

                    for card_ref in pending_card_refs:
                        if self.max_items and summary.imported >= self.max_items:
                            stop_processing = True
                            break

                        touched_backend = False
                        card_dedupe_key = self._build_card_dedupe_key(card_ref)
                        if card_dedupe_key:
                            attempted_card_keys.add(card_dedupe_key)
                        if card_dedupe_key and card_dedupe_key in seen_card_keys:
                            summary.skipped += 1
                            print(f"[{ordinal}/{self._format_total_label(len(card_refs), incremental_collection)}] 跳过重复卡片 index={card_ref.index}")
                            continue

                        summary.processed += 1
                        ordinal += 1
                        print(
                            f"[{ordinal}/{self._format_total_label(len(card_refs), incremental_collection)}] "
                            f"开始导入卡片 index={card_ref.index}",
                            flush=True,
                        )
                        try:
                            item = self.adapter.extract_item_from_feed(
                                page,
                                card_ref,
                                crawl_mode=crawl_mode,
                                **mode_kwargs,
                            )
                            if self._is_video_item(item):
                                summary.skipped += 1
                                if card_dedupe_key:
                                    seen_card_keys.add(card_dedupe_key)
                                self._print_video_skip(item)
                                continue
                            if dedupe_cache.should_skip(item):
                                dedupe_cache.remember(item)
                                summary.skipped += 1
                                if card_dedupe_key:
                                    seen_card_keys.add(card_dedupe_key)
                                self._print_cached_skip(item)
                                continue

                            validation = self._validate_source_image_before_import(page, item)
                            if not validation.ok:
                                summary.skipped += 1
                                if card_dedupe_key:
                                    seen_card_keys.add(card_dedupe_key)
                                self._print_image_quality_skip(item, validation)
                                continue

                            self._print_import_request(item)
                            touched_backend = True
                            response = self.api_client.import_item(item)
                            dedupe_cache.remember(item)
                            if card_dedupe_key:
                                seen_card_keys.add(card_dedupe_key)

                            if not response.get("created", True) and response.get("storage_reused", False):
                                summary.skipped += 1
                                self._print_existing_skip(item, response)
                                continue

                            summary.imported += 1
                            self._print_success(item, response)
                        except SkipScrapeItem as exc:
                            summary.skipped += 1
                            if card_dedupe_key:
                                seen_card_keys.add(card_dedupe_key)
                            print(f"  ↷ 跳过：{exc}")
                        except LunarsandApiRequestError as exc:
                            summary.failed += 1
                            print(f"  ✗ 抓取失败：{exc}")
                            if self._is_fatal_api_error(exc):
                                print("Lunarsand API 鉴权失败，停止后续卡片处理。请检查 LUNARSAND_API_KEY。", flush=True)
                                stop_processing = True
                                break
                        except Exception as exc:
                            summary.failed += 1
                            print(f"  ✗ 抓取失败：{exc}")
                            if self._is_browser_closed_error(exc):
                                print("浏览器已关闭，停止后续卡片处理。", flush=True)
                                stop_processing = True
                                break
                        finally:
                            if touched_backend and not (self.max_items and summary.imported >= self.max_items):
                                self._pause_between_imports()

                    if stop_processing or not incremental_collection:
                        if stop_processing or (self.max_items and summary.imported >= self.max_items):
                            break
                    if self.max_items and summary.imported >= self.max_items:
                        break
                    if incremental_collection and not self._load_more_feed_cards(
                        page,
                        crawl_mode=crawl_mode,
                        mode_kwargs=mode_kwargs,
                    ):
                        break
                    card_refs = self.adapter.collect_feed_cards(
                        page,
                        max_items=self._next_collection_limit(attempted_card_keys, summary),
                        crawl_mode=crawl_mode,
                        skip_external_item_ids=dedupe_cache.external_item_ids_for_site(self.adapter.site_name),
                        **mode_kwargs,
                    )

                if ordinal == 0 and not summary.skipped:
                    print("未发现新的可抓取作品卡片。")
            finally:
                dedupe_cache.flush()
                try:
                    context.close()
                except Exception:
                    pass
                if browser is not None:
                    try:
                        browser.close()
                    except Exception:
                        pass
                if runtime_user_data_dir is not None:
                    try:
                        self._sync_runtime_user_data_dir_back(runtime_user_data_dir)
                    finally:
                        shutil.rmtree(runtime_user_data_dir.parent, ignore_errors=True)

        return summary

    def _adapter_collects_incrementally(self) -> bool:
        return bool(getattr(self.adapter, "collect_feed_incrementally", False))

    def _next_collection_limit(self, attempted_card_keys: set[str], summary: CrawlSummary) -> Optional[int]:
        if not self.max_items:
            return None
        remaining_imports = max(self.max_items - summary.imported, 0)
        if remaining_imports <= 0:
            return self.max_items
        return len(attempted_card_keys) + 1

    def _load_more_feed_cards(self, page: Page, *, crawl_mode: str, mode_kwargs: dict) -> bool:
        loader = getattr(self.adapter, "load_more_feed_cards", None)
        if not callable(loader):
            return False
        return bool(loader(page, crawl_mode=crawl_mode, **mode_kwargs))

    def _format_total_label(self, current_batch_count: int, incremental_collection: bool) -> str:
        if self.max_items:
            return str(self.max_items)
        if incremental_collection:
            return "?"
        return str(current_batch_count)

    def _build_ignored_profile_entries(self, names: List[str]) -> set[str]:
        ignored: set[str] = set()
        for name in names:
            if (
                name in self.PROFILE_TRANSIENT_NAMES
                or name in self.PROFILE_IGNORED_DIR_NAMES
                or name.endswith(".lock")
            ):
                ignored.add(name)
        return ignored

    def _cleanup_profile_locks(self, profile_dir: Path) -> None:
        for pattern in ("Singleton*", "*.lock", "LOCK"):
            for lock_path in profile_dir.glob(pattern):
                if lock_path.is_file() or lock_path.is_symlink():
                    lock_path.unlink(missing_ok=True)

        default_profile_dir = profile_dir / "Default"
        if default_profile_dir.exists():
            for pattern in ("LOCK", "*.lock"):
                for lock_path in default_profile_dir.glob(pattern):
                    if lock_path.is_file() or lock_path.is_symlink():
                        lock_path.unlink(missing_ok=True)

    def _prepare_runtime_user_data_dir(self) -> Path:
        source_dir = Path(self.user_data_dir or "").expanduser().resolve()
        if not source_dir.is_dir():
            raise FileNotFoundError(f"user_data 目录不存在：{source_dir}")

        print(f"准备复制浏览器登录目录到临时目录：{source_dir}")
        temp_root = Path(tempfile.mkdtemp(prefix="resource_filter_profile_"))
        runtime_dir = temp_root / source_dir.name

        def ignore_transient_profile_entries(_dir: str, names: list[str]) -> set[str]:
            return self._build_ignored_profile_entries(list(names))

        shutil.copytree(
            source_dir,
            runtime_dir,
            dirs_exist_ok=True,
            symlinks=True,
            ignore_dangling_symlinks=True,
            ignore=ignore_transient_profile_entries,
        )

        self._cleanup_profile_locks(runtime_dir)

        print(f"浏览器登录目录复制完成：{runtime_dir}")
        return runtime_dir

    def _sync_runtime_user_data_dir_back(self, runtime_dir: Path) -> None:
        source_dir = Path(self.user_data_dir or "").expanduser().resolve()
        if not runtime_dir.exists() or not source_dir.exists():
            return

        print(f"同步浏览器登录目录回原目录：{source_dir}")
        self._cleanup_profile_locks(source_dir)
        self._cleanup_profile_locks(runtime_dir)

        def ignore_transient_profile_entries(_dir: str, names: list[str]) -> set[str]:
            return self._build_ignored_profile_entries(list(names))

        shutil.copytree(
            runtime_dir,
            source_dir,
            dirs_exist_ok=True,
            symlinks=True,
            ignore_dangling_symlinks=True,
            ignore=ignore_transient_profile_entries,
        )
        self._cleanup_profile_locks(source_dir)
        print(f"浏览器登录目录同步完成：{source_dir}")

    def _open_browser(self, playwright: Playwright) -> tuple[Optional[Browser], BrowserContext, Page, Optional[Path]]:
        if self.cdp_url:
            return self._connect_to_existing_browser(playwright)

        launch_kwargs = {"headless": self.headless}
        if self.slow_mo_ms > 0:
            launch_kwargs["slow_mo"] = self.slow_mo_ms
        launch_kwargs["args"] = [
            "--disable-gpu",
            "--disable-software-rasterizer",
        ]
        if self.proxy_server:
            launch_kwargs["proxy"] = {"server": self.proxy_server}

        browser_channel = (self.browser_channel or "").strip().lower()
        if browser_channel:
            executable_path = self._resolve_browser_executable(browser_channel)
            if executable_path:
                launch_kwargs["executable_path"] = executable_path
            else:
                launch_kwargs["channel"] = browser_channel

        print(
            "启动浏览器参数："
            f"channel={browser_channel or 'chromium'} "
            f"headless={self.headless} "
            f"user_data_dir={'yes' if self.user_data_dir else 'no'} "
            f"proxy={'yes' if self.proxy_server else 'no'}",
            flush=True,
        )

        context_kwargs = {
            "viewport": {"width": 1440, "height": 1200},
            "ignore_https_errors": True,
        }

        if self.user_data_dir:
            runtime_user_data_dir = self._prepare_runtime_user_data_dir()
            context = playwright.chromium.launch_persistent_context(
                str(runtime_user_data_dir),
                **launch_kwargs,
                **context_kwargs,
            )
            page = context.new_page()
            for existing_page in list(context.pages):
                if existing_page == page:
                    continue
                try:
                    existing_page.close()
                except Exception:
                    pass
            try:
                page.bring_to_front()
            except Exception:
                pass
            page.set_default_timeout(15000)
            page.set_default_navigation_timeout(20000)
            return None, context, page, runtime_user_data_dir

        browser = playwright.chromium.launch(**launch_kwargs)
        if self.storage_state:
            context_kwargs["storage_state"] = self.storage_state
        context = browser.new_context(**context_kwargs)
        page = context.new_page()
        page.set_default_timeout(15000)
        page.set_default_navigation_timeout(20000)
        return browser, context, page, None

    def _connect_to_existing_browser(
        self,
        playwright: Playwright,
    ) -> tuple[Optional[Browser], BrowserContext, Page, Optional[Path]]:
        print(f"连接到已打开的 Chrome：{self.cdp_url}")
        browser = playwright.chromium.connect_over_cdp(self.cdp_url)
        if browser.contexts:
            context = browser.contexts[0]
        else:
            context = browser.new_context(
                viewport={"width": 1440, "height": 1200},
                ignore_https_errors=True,
            )

        page = context.new_page()
        try:
            page.bring_to_front()
        except Exception:
            pass
        page.set_default_timeout(15000)
        page.set_default_navigation_timeout(20000)
        return browser, context, page, None

    def _resolve_browser_executable(self, browser_channel: str) -> Optional[str]:
        channel_candidates = {
            "chrome": (
                "google-chrome",
                "google-chrome-stable",
                "/usr/bin/google-chrome",
                "/usr/bin/google-chrome-stable",
            ),
            "msedge": (
                "microsoft-edge",
                "microsoft-edge-stable",
                "/usr/bin/microsoft-edge",
                "/usr/bin/microsoft-edge-stable",
            ),
            "chromium": (
                "chromium",
                "chromium-browser",
                "/usr/bin/chromium",
                "/usr/bin/chromium-browser",
            ),
        }
        for candidate in channel_candidates.get(browser_channel, ()):
            resolved = shutil.which(candidate) if not candidate.startswith("/") else candidate
            if resolved and os.path.exists(resolved):
                return resolved
        return None

    def _normalize_proxy_server(self, proxy_server: Optional[str]) -> Optional[str]:
        normalized = normalize_optional_text(proxy_server)
        if not normalized:
            return None
        if "://" in normalized:
            return normalized
        return f"http://{normalized}"

    def _build_card_dedupe_key(self, card_ref: FeedCardRef) -> Optional[str]:
        external_item_id = normalize_optional_text(card_ref.external_item_id)
        if external_item_id:
            return f"external:{external_item_id}"

        detail_url = normalize_optional_text(card_ref.detail_url)
        if detail_url:
            return f"detail:{detail_url}"

        preview_image_url = normalize_optional_text(card_ref.preview_image_url)
        if not preview_image_url:
            return None

        author_name = normalize_text(card_ref.author_name)
        like_count = "" if card_ref.like_count is None else str(card_ref.like_count)
        return f"preview:{preview_image_url}|author:{author_name}|like:{like_count}"

    def _is_video_item(self, item: ScrapeItemPayload) -> bool:
        if self._looks_like_video_url(item.source_image_url):
            return True
        if self._looks_like_image_url(item.source_image_url):
            return False
        return self._raw_payload_has_video(item.raw_payload)

    def _looks_like_image_url(self, value: Optional[str]) -> bool:
        normalized = normalize_text(value).lower()
        if not normalized:
            return False
        if normalized.startswith("data:image/"):
            return True
        parsed = urlparse(normalized)
        path = parsed.path or normalized
        return path.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".bmp"))

    def _raw_payload_has_video(self, value: Any) -> bool:
        if isinstance(value, dict):
            for key, child in value.items():
                normalized_key = normalize_text(str(key)).lower()
                if isinstance(child, str):
                    normalized_child = normalize_text(child).lower()
                    if normalized_key in {"media_type", "type", "content_type", "mime_type"} and "video" in normalized_child:
                        return True
                    if "video" in normalized_key and (
                        self._looks_like_video_url(normalized_child) or normalized_child in {"video", "true", "1"}
                    ):
                        return True
                    if normalized_key.endswith("_url") and self._looks_like_video_url(normalized_child):
                        return True
                    continue
                if self._raw_payload_has_video(child):
                    return True
            return False

        if isinstance(value, list):
            return any(self._raw_payload_has_video(child) for child in value)

        if isinstance(value, str):
            return self._looks_like_video_url(value)

        return False

    def _looks_like_video_url(self, value: Optional[str]) -> bool:
        normalized = normalize_text(value).lower()
        if not normalized:
            return False
        parsed = urlparse(normalized)
        path = parsed.path or normalized
        return any(path.endswith(extension) for extension in self.VIDEO_FILE_EXTENSIONS)

    def _print_success(self, item: ScrapeItemPayload, response: dict) -> None:
        author_name = item.author.name if item.author else "未知作者"
        prompt_preview = (item.prompt_text or "").replace("\n", " ")
        if len(prompt_preview) > 48:
            prompt_preview = f"{prompt_preview[:48]}..."
        print(
            "  ✓ 已导入审核队列",
            f"site={item.site_name}",
            f"author={author_name}",
            f"detail={item.detail_url or '-'}",
            f"image={self._format_url_for_log(item.source_image_url)}",
            f"prompt={prompt_preview or '-'}",
            f"queue_id={response.get('id', '-')}",
            sep=" | ",
        )

    def _print_import_request(self, item: ScrapeItemPayload) -> None:
        print(
            "  → 提交后端导入",
            f"detail={item.detail_url or '-'}",
            f"image={self._format_url_for_log(item.source_image_url)}",
            sep=" | ",
            flush=True,
        )

    def _pause_between_imports(self) -> None:
        if self.import_delay_seconds <= 0:
            return
        print(f"  … 等待 {self.import_delay_seconds:.1f}s 后继续，降低服务器读写压力", flush=True)
        time.sleep(self.import_delay_seconds)

    def _print_cached_skip(self, item: ScrapeItemPayload) -> None:
        author_name = item.author.name if item.author else "未知作者"
        print(
            "  ↷ 已命中本地去重缓存，跳过导入",
            f"site={item.site_name}",
            f"author={author_name}",
            f"detail={item.detail_url or '-'}",
            f"image={self._format_url_for_log(item.source_image_url)}",
            f"external_id={item.external_item_id or '-'}",
            sep=" | ",
        )

    def _print_video_skip(self, item: ScrapeItemPayload) -> None:
        print(
            "  ↷ 检测到视频资源，跳过保存",
            f"site={item.site_name}",
            f"detail={item.detail_url or '-'}",
            f"image={self._format_url_for_log(item.source_image_url)}",
            f"external_id={item.external_item_id or '-'}",
            sep=" | ",
        )

    def _validate_source_image_before_import(self, page: Page, item: ScrapeItemPayload) -> ImageValidationResult:
        source_image_url = normalize_optional_text(item.source_image_url)
        if not source_image_url:
            return ImageValidationResult(ok=False, reason="图片地址为空")

        if source_image_url.startswith("data:image/"):
            return validate_data_image_url(source_image_url)

        if not source_image_url.startswith(("http://", "https://")):
            return ImageValidationResult(ok=False, reason="图片地址不是可访问的 http(s)/data 图片")

        trusted_validation = self._validate_trusted_source_image_metadata(item, source_image_url)
        if trusted_validation.ok:
            return trusted_validation

        candidate_urls = promoted_image_url_candidates(source_image_url)
        if looks_like_thumbnail_url(source_image_url) and candidate_urls:
            print(f"  … 图片地址疑似缩略图，尝试升级原图候选 {len(candidate_urls)} 个", flush=True)

        best_failure: Optional[ImageValidationResult] = None
        for candidate_url in [*candidate_urls, source_image_url]:
            validation = self._validate_http_image_url(page, candidate_url, referer_url=item.detail_url)
            if validation.ok:
                if candidate_url != source_image_url:
                    self._replace_item_source_image_url(item, candidate_url, previous_url=source_image_url)
                    print(
                        "  ✓ 已升级为原图地址",
                        f"from={self._format_url_for_log(source_image_url)}",
                        f"to={self._format_url_for_log(candidate_url)}",
                        f"size={validation.width}x{validation.height}",
                        sep=" | ",
                        flush=True,
                    )
                return validation
            if best_failure is None or (validation.width or 0) * (validation.height or 0) > (best_failure.width or 0) * (best_failure.height or 0):
                best_failure = validation

        if looks_like_thumbnail_url(source_image_url):
            return ImageValidationResult(ok=False, reason=f"疑似缩略图，未找到合格原图：{best_failure.reason if best_failure else '-'}")
        if self._is_midjourney_original_cdn_image_url(source_image_url):
            return ImageValidationResult(
                ok=True,
                reason="Midjourney 原图 CDN 会拦截非浏览器 HTTP 校验，已按原图 URL 结构放行",
            )
        return best_failure or ImageValidationResult(ok=False, reason="图片质量检查失败")

    def _validate_trusted_source_image_metadata(
        self,
        item: ScrapeItemPayload,
        source_image_url: str,
    ) -> ImageValidationResult:
        if item.site_name != "mj":
            return ImageValidationResult(ok=False, reason="无可信详情页图片尺寸")

        detail_payload = item.raw_payload.get("detail") if isinstance(item.raw_payload, dict) else None
        if not isinstance(detail_payload, dict):
            return ImageValidationResult(ok=False, reason="无可信详情页图片尺寸")

        payload_url = normalize_optional_text(detail_payload.get("source_image_url"))
        if payload_url and not self._same_url_path(payload_url, source_image_url):
            return ImageValidationResult(ok=False, reason="详情页图片尺寸与当前图片 URL 不匹配")

        width = self._coerce_positive_int(detail_payload.get("source_image_width"))
        height = self._coerce_positive_int(detail_payload.get("source_image_height"))
        if width < MIN_IMAGE_WIDTH or height < MIN_IMAGE_HEIGHT:
            return ImageValidationResult(ok=False, reason="无可信详情页图片尺寸", width=width or None, height=height or None)

        return ImageValidationResult(
            ok=True,
            reason="使用 Midjourney 详情页已加载图片尺寸通过校验",
            width=width,
            height=height,
        )

    def _same_url_path(self, left_url: str, right_url: str) -> bool:
        left = urlparse(left_url)
        right = urlparse(right_url)
        return left.netloc.lower() == right.netloc.lower() and left.path == right.path

    def _is_midjourney_original_cdn_image_url(self, source_image_url: str) -> bool:
        parsed = urlparse(source_image_url)
        if parsed.netloc.lower() != "cdn.midjourney.com":
            return False
        if looks_like_thumbnail_url(source_image_url):
            return False
        if parsed.path.lower().startswith("/video/"):
            return False
        return bool(re.match(r"^/[0-9a-fA-F-]{32,}/\d+_\d+\.(?:jpe?g|png|webp)$", parsed.path))

    def _validate_http_image_url(
        self,
        page: Page,
        source_image_url: str,
        *,
        referer_url: Optional[str] = None,
    ) -> ImageValidationResult:
        try:
            response = page.context.request.get(
                source_image_url,
                timeout=15000,
                headers=self._image_request_headers(page, source_image_url, referer_url=referer_url),
            )
        except Exception as exc:
            return ImageValidationResult(ok=False, reason=f"读取图片失败：{exc}")

        if not getattr(response, "ok", False):
            loaded_validation = self._validate_loaded_image_from_dom(page, source_image_url)
            if loaded_validation.ok:
                return loaded_validation
            return ImageValidationResult(ok=False, reason=f"读取图片失败：HTTP {getattr(response, 'status', '-')}")

        content_type = normalize_text(response.headers.get("content-type")).lower()
        if content_type and not content_type.startswith("image/"):
            return ImageValidationResult(ok=False, reason=f"资源不是图片：{content_type}")

        image_bytes = response.body()
        if len(image_bytes) > MAX_IMAGE_BYTES_TO_INSPECT:
            image_bytes = image_bytes[:MAX_IMAGE_BYTES_TO_INSPECT]
        return validate_image_bytes(image_bytes)

    def _image_request_headers(
        self,
        page: Page,
        source_image_url: str,
        *,
        referer_url: Optional[str] = None,
    ) -> dict[str, str]:
        parsed = urlparse(source_image_url)
        referer = normalize_optional_text(referer_url)
        if not referer and parsed.netloc.lower() == "cdn.midjourney.com":
            referer = "https://www.midjourney.com/"
        elif not referer and parsed.netloc:
            referer = f"{parsed.scheme}://{parsed.netloc}/"

        headers = {
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "User-Agent": self._safe_browser_user_agent(page)
            or (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
            ),
        }
        if referer:
            headers["Referer"] = referer
        return headers

    def _safe_browser_user_agent(self, page: Page) -> Optional[str]:
        try:
            return normalize_optional_text(page.evaluate("navigator.userAgent"))
        except Exception:
            return None

    def _validate_loaded_image_from_dom(self, page: Page, source_image_url: str) -> ImageValidationResult:
        parsed = urlparse(source_image_url)
        if parsed.netloc.lower() != "cdn.midjourney.com":
            return ImageValidationResult(ok=False, reason="图片 HTTP 读取失败，且不是可从 DOM 兜底的 Midjourney CDN 图片")

        try:
            payload = page.evaluate(
                """
                (targetUrl) => {
                  let target;
                  try {
                    target = new URL(targetUrl);
                  } catch (error) {
                    return null;
                  }
                  const matches = Array.from(document.images || []).filter((img) => {
                    const rawUrl = img.currentSrc || img.src || img.getAttribute('src') || '';
                    if (!rawUrl) return false;
                    try {
                      const current = new URL(rawUrl, document.baseURI);
                      return current.host === target.host && current.pathname === target.pathname;
                    } catch (error) {
                      return false;
                    }
                  });
                  let best = null;
                  for (const img of matches) {
                    const rect = img.getBoundingClientRect();
                    const width = img.naturalWidth || Math.round(rect.width || img.clientWidth || 0);
                    const height = img.naturalHeight || Math.round(rect.height || img.clientHeight || 0);
                    const area = width * height;
                    if (width && height && (!best || area > best.area)) {
                      best = { width, height, area };
                    }
                  }
                  return best;
                }
                """,
                source_image_url,
            )
        except Exception:
            return ImageValidationResult(ok=False, reason="图片 HTTP 读取失败，DOM 兜底检查也失败")

        if not isinstance(payload, dict):
            return ImageValidationResult(ok=False, reason="图片 HTTP 读取失败，页面里未找到已加载的同源图片")

        width = self._coerce_positive_int(payload.get("width"))
        height = self._coerce_positive_int(payload.get("height"))
        if width < MIN_IMAGE_WIDTH or height < MIN_IMAGE_HEIGHT:
            return ImageValidationResult(ok=False, reason=f"图片尺寸过小：{width}x{height}", width=width, height=height)

        return ImageValidationResult(ok=True, reason="HTTP 403，但浏览器页面中已加载同图，使用 DOM 尺寸通过校验", width=width, height=height)

    def _coerce_positive_int(self, value: Any) -> int:
        try:
            integer = int(value)
        except (TypeError, ValueError):
            return 0
        return integer if integer > 0 else 0

    def _replace_item_source_image_url(
        self,
        item: ScrapeItemPayload,
        source_image_url: str,
        *,
        previous_url: str,
    ) -> None:
        item.source_image_url = source_image_url
        raw_payload = item.raw_payload if isinstance(item.raw_payload, dict) else {}
        raw_payload["source_image_url_promoted_from"] = previous_url
        detail_payload = raw_payload.get("detail")
        if isinstance(detail_payload, dict):
            detail_payload["source_image_url"] = source_image_url
            detail_payload["source_image_url_promoted_from"] = previous_url

    def _print_image_quality_skip(self, item: ScrapeItemPayload, validation: ImageValidationResult) -> None:
        size_label = "-"
        if validation.width is not None and validation.height is not None:
            size_label = f"{validation.width}x{validation.height}"
        print(
            "  ↷ 保存前图片质量检查未通过，跳过保存",
            f"site={item.site_name}",
            f"detail={item.detail_url or '-'}",
            f"image={self._format_url_for_log(item.source_image_url)}",
            f"size={size_label}",
            f"reason={validation.reason}",
            sep=" | ",
        )

    def _print_existing_skip(self, item: ScrapeItemPayload, response: dict) -> None:
        author_name = item.author.name if item.author else "未知作者"
        print(
            "  ↷ 后端已存在相同记录，跳过重复保存",
            f"site={item.site_name}",
            f"author={author_name}",
            f"detail={item.detail_url or '-'}",
            f"image={self._format_url_for_log(item.source_image_url)}",
            f"queue_id={response.get('id', '-')}",
            sep=" | ",
        )

    def _format_url_for_log(self, url: Optional[str], limit: int = 120) -> str:
        normalized = normalize_optional_text(url)
        if not normalized:
            return "-"
        if len(normalized) <= limit:
            return normalized
        return f"{normalized[: limit - 3]}..."

    def _is_browser_closed_error(self, exc: Exception) -> bool:
        message = normalize_text(str(exc)).lower()
        return (
            "target page, context or browser has been closed" in message
            or "browser has been closed" in message
            or "target closed" in message
        )

    def _is_fatal_api_error(self, exc: LunarsandApiRequestError) -> bool:
        return exc.status_code in {401, 403}
