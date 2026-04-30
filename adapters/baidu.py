from __future__ import annotations

import html
import json
import re
import time
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlparse, urlsplit, urlunsplit

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page, TimeoutError as PlaywrightTimeoutError
else:
    try:
        from playwright.sync_api import Locator, Page, TimeoutError as PlaywrightTimeoutError
    except ModuleNotFoundError:
        Locator = Any
        Page = Any

        class PlaywrightTimeoutError(Exception):
            pass

from resource_filter.adapters.base import SiteAdapter
from resource_filter.models import FeedCardRef, ScrapeItemPayload
from resource_filter.utils import normalize_optional_text, normalize_text, sha256_text


class BaiduAdapter(SiteAdapter):
    site_name = "baidu"
    DEFAULT_SEARCH_URL = "https://image.baidu.com/"

    SEARCH_INPUT_SELECTOR = (
        "textarea#chat-textarea, "
        "#chat-textarea, "
        "textarea[placeholder*='输入文字'], "
        "input[name='word'], "
        "input#kw"
    )
    SEARCH_SUBMIT_SELECTOR = (
        "button#ci-submit-button, "
        "#ci-submit-button, "
        "input[type='submit'], "
        "button:has-text('百度一下'), "
        "button:has-text('搜索')"
    )
    FEED_CARD_SELECTOR = (
        "[data-module='image-cell'][data-show-ext], "
        ".cos-masonry-container-item [data-show-ext], "
        ".img-cell-w6C5O[data-show-ext]"
    )
    NEXT_PAGE_SELECTOR = (
        "a:has-text('下一页'), "
        "button:has-text('下一页'), "
        ".pagination-next, "
        ".new-pmd .page-item-next"
    )

    NAVIGATION_TIMEOUT_MS = 90000
    POST_NAVIGATION_TIMEOUT_MS = 15000
    FEED_READY_TIMEOUT_MS = 45000
    SEARCH_RESULT_TIMEOUT_MS = 45000
    PAGE_CHANGE_TIMEOUT_MS = 15000
    PLACEHOLDER_IMAGE_PATTERNS = (
        "loading",
        "placeholder",
        "blank.gif",
        "transparent",
    )

    def open_inspiration(self, page: Page, entry_url: str, **kwargs: object) -> None:
        keyword = normalize_optional_text(kwargs.get("keyword"))
        target_url = self._normalize_inspiration_entry_url(entry_url, keyword=keyword)

        print(f"百度：打开入口 {target_url}", flush=True)
        self._goto_page(page, target_url)
        self._dismiss_popups(page)

        if keyword and not self._looks_like_search_result_url(target_url):
            print(f"百度：提交搜索关键词 {keyword}", flush=True)
            self._search_keyword(page, keyword)

        print("百度：等待图片结果加载...", flush=True)
        self._wait_for_feed(page)

    def open_author_page(self, page: Page, author_url: str, **_: object) -> None:
        raise ValueError("baidu 站点暂不支持 author 模式")

    def collect_feed_cards(
        self,
        page: Page,
        max_items: int | None = None,
        *,
        skip_external_item_ids: set[str] | None = None,
        **_: object,
    ) -> List[FeedCardRef]:
        self._wait_for_feed(page)

        references: List[FeedCardRef] = []
        seen_item_keys: set[str] = set()
        skipped_cached_item_ids = {
            normalize_text(item_id)
            for item_id in (skip_external_item_ids or set())
            if normalize_text(item_id)
        }

        page_number = 1
        while True:
            print(f"百度：收集第 {page_number} 页图片结果...", flush=True)
            self._load_current_page_cards(page, max_items=max_items, collected_count=len(references))
            before_count = len(references)
            self._collect_current_page_cards(
                page,
                references,
                seen_item_keys,
                max_items=max_items,
                skipped_cached_item_ids=skipped_cached_item_ids,
            )
            print(f"百度：第 {page_number} 页新增 {len(references) - before_count} 个，累计 {len(references)} 个", flush=True)

            if max_items and len(references) >= max_items:
                break
            if not self._go_to_next_page(page):
                break
            page_number += 1

        return references

    def extract_item_from_feed(self, page: Page, card_ref: FeedCardRef, **_: object) -> ScrapeItemPayload:
        return self._build_scrape_item(card_ref)

    def _normalize_inspiration_entry_url(self, entry_url: str, *, keyword: Optional[str] = None) -> str:
        raw_url = normalize_optional_text(entry_url) or self.DEFAULT_SEARCH_URL
        if raw_url.startswith("/"):
            raw_url = urljoin(self.DEFAULT_SEARCH_URL, raw_url)

        parsed = urlparse(raw_url)
        if not parsed.scheme:
            raw_url = f"https://{raw_url}"

        if keyword and self._looks_like_search_result_url(raw_url):
            parsed = urlsplit(raw_url)
            query = parse_qs(parsed.query, keep_blank_values=True)
            query["word"] = [keyword]
            if not query.get("tn"):
                query["tn"] = ["baiduimage"]
            return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query, doseq=True), parsed.fragment))
        return raw_url

    def _looks_like_search_result_url(self, url: str) -> bool:
        normalized = normalize_text(url).lower()
        return "image.baidu.com/search" in normalized

    def _goto_page(self, page: Page, target_url: str) -> None:
        try:
            page.goto(target_url, wait_until="commit", timeout=self.NAVIGATION_TIMEOUT_MS)
        except PlaywrightTimeoutError as exc:
            raise RuntimeError(f"百度页面连接超时，请检查网络或登录态：{target_url}") from exc
        self._wait_for_domcontentloaded_or_stop(page)

    def _wait_for_domcontentloaded_or_stop(self, page: Page) -> None:
        try:
            page.wait_for_load_state("domcontentloaded", timeout=self.POST_NAVIGATION_TIMEOUT_MS)
        except PlaywrightTimeoutError:
            try:
                page.evaluate("window.stop()")
            except Exception:
                pass

    def _dismiss_popups(self, page: Page) -> None:
        for _ in range(2):
            try:
                page.keyboard.press("Escape")
                page.wait_for_timeout(250)
            except Exception:
                return

    def _search_keyword(self, page: Page, keyword: str) -> None:
        search_input = self._wait_for_search_input(page)
        before_signature = self._current_page_signature(page)

        search_input.fill(keyword, timeout=5000)
        page.wait_for_timeout(200)

        submitted = False
        search_button = self._first_visible([page.locator(self.SEARCH_SUBMIT_SELECTOR)])
        if search_button is not None:
            try:
                search_button.click(timeout=3000, force=True)
                submitted = True
            except Exception:
                submitted = False

        if not submitted:
            try:
                search_input.press("Enter", timeout=3000)
                submitted = True
            except Exception:
                submitted = False

        if not submitted:
            raise RuntimeError("未能触发百度搜索，请检查搜索输入框或搜索按钮是否变化")

        print("百度：等待搜索结果刷新...", flush=True)
        self._wait_for_search_results(page, before_signature=before_signature)
        self._dismiss_popups(page)

    def _wait_for_search_input(self, page: Page) -> Locator:
        locator = page.locator(self.SEARCH_INPUT_SELECTOR).first
        try:
            locator.wait_for(state="visible", timeout=15000)
            return locator
        except Exception as exc:
            raise RuntimeError("未找到百度搜索输入框 #chat-textarea") from exc

    def _wait_for_search_results(self, page: Page, *, before_signature: str) -> None:
        deadline = time.monotonic() + self.SEARCH_RESULT_TIMEOUT_MS / 1000
        last_error: Optional[Exception] = None

        while time.monotonic() < deadline:
            try:
                if self._find_visible_feed_card(page) is not None:
                    current_signature = self._current_page_signature(page)
                    if not before_signature or current_signature != before_signature:
                        return
            except Exception as exc:
                last_error = exc
            page.wait_for_timeout(300)

        if self._find_visible_feed_card(page) is not None:
            return
        if last_error is not None:
            raise RuntimeError(f"百度搜索结果未加载完成：{last_error}") from last_error
        raise RuntimeError(self._build_feed_not_loaded_message(page))

    def _wait_for_feed(self, page: Page) -> None:
        deadline = time.monotonic() + self.FEED_READY_TIMEOUT_MS / 1000
        next_notice = time.monotonic() + 5
        while time.monotonic() < deadline:
            if self._find_visible_feed_card(page) is not None:
                return
            if time.monotonic() >= next_notice:
                print("百度：仍在等待图片结果...", flush=True)
                next_notice += 5
            page.wait_for_timeout(250)

        raise RuntimeError(self._build_feed_not_loaded_message(page))

    def _build_feed_not_loaded_message(self, page: Page) -> str:
        page_url = self._safe_page_url(page)
        title = self._safe_page_title(page)
        body_excerpt = self._safe_body_excerpt(page)
        card_count = self._safe_locator_count(page.locator(self.FEED_CARD_SELECTOR))

        parts = [
            "百度图片结果未加载完成",
            f"url={page_url or '<unknown>'}",
            f"title={title or '<empty>'}",
            f"cards={card_count}",
        ]
        if body_excerpt:
            parts.append(f"body={body_excerpt}")
        return "；".join(parts)

    def _load_current_page_cards(self, page: Page, *, max_items: int | None, collected_count: int) -> None:
        stable_rounds = 0
        last_count = 0

        while stable_rounds < 3:
            current_count = self._safe_locator_count(page.locator(self.FEED_CARD_SELECTOR))
            if current_count != last_count:
                print(f"百度：当前页已加载 {current_count} 个图片卡片...", flush=True)
            if max_items and collected_count + current_count >= max_items:
                break

            if current_count == last_count:
                stable_rounds += 1
            else:
                stable_rounds = 0
                last_count = current_count

            try:
                page.mouse.wheel(0, 2200)
            except Exception:
                break
            page.wait_for_timeout(900)

    def _collect_current_page_cards(
        self,
        page: Page,
        references: List[FeedCardRef],
        seen_item_keys: set[str],
        *,
        max_items: int | None,
        skipped_cached_item_ids: set[str],
    ) -> None:
        cards = page.locator(self.FEED_CARD_SELECTOR)
        count = self._safe_locator_count(cards)

        for index in range(count):
            card = cards.nth(index)
            ext = self._extract_card_show_ext(card)
            if ext.get("isAd") is True:
                continue

            image_url = self._extract_card_image_url(card, ext=ext)
            if not image_url:
                continue

            detail_url = self._extract_detail_url(card, page.url)
            source_url = self._normalize_url(ext.get("fromurl"))
            external_item_id = self._extract_external_item_id(
                ext=ext,
                detail_url=detail_url,
                image_url=image_url,
            )
            item_key = external_item_id or detail_url or image_url
            if not item_key or item_key in seen_item_keys:
                continue

            seen_item_keys.add(item_key)
            if external_item_id and external_item_id in skipped_cached_item_ids:
                continue

            references.append(
                FeedCardRef(
                    index=len(references),
                    preview_image_url=image_url,
                    detail_url=detail_url,
                    title=normalize_optional_text(ext.get("title")) or self._extract_card_title(card),
                    author_url=source_url,
                    external_item_id=external_item_id,
                    raw_payload={
                        "show_ext": self._compact_show_ext(ext),
                    },
                )
            )

            if max_items and len(references) >= max_items:
                break

    def _extract_card_show_ext(self, card: Locator) -> Dict[str, Any]:
        raw_value = self._safe_get_attribute(card, "data-show-ext")
        if not raw_value:
            return {}
        decoded = html.unescape(raw_value)
        try:
            parsed = json.loads(decoded)
        except (TypeError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _compact_show_ext(self, ext: Dict[str, Any]) -> Dict[str, Any]:
        keep_keys = (
            "order",
            "url",
            "objurl",
            "fromurl",
            "cs",
            "setsign",
            "strategy",
            "title",
            "isAd",
            "isSet",
            "pic_num",
            "pic_tag",
        )
        return {key: ext.get(key) for key in keep_keys if ext.get(key) not in (None, "", [], {})}

    def _extract_card_image_url(self, card: Locator, *, ext: Optional[Dict[str, Any]] = None) -> Optional[str]:
        ext = ext or self._extract_card_show_ext(card)
        for value in (
            ext.get("url"),
            self._safe_get_attribute(card.locator("img[data-thumbnail-url]").first, "data-thumbnail-url"),
            self._safe_get_attribute(card.locator("img").first, "src"),
            ext.get("objurl"),
            self._safe_get_attribute(card.locator("img[data-objurl]").first, "data-objurl"),
        ):
            image_url = self._normalize_image_url(value)
            if image_url:
                return image_url
        return None

    def _normalize_image_url(self, image_url: Optional[str]) -> Optional[str]:
        normalized = self._normalize_url(image_url)
        if not normalized:
            return None
        if not normalized.startswith(("http://", "https://")):
            return None

        parsed = urlsplit(normalized)
        if not parsed.netloc:
            return None
        lowered = normalized.lower()
        if any(pattern in lowered for pattern in self.PLACEHOLDER_IMAGE_PATTERNS):
            return None
        if lowered.startswith("http://"):
            normalized = f"https://{normalized.removeprefix('http://')}"
        return normalized

    def _normalize_url(self, value: Any) -> Optional[str]:
        normalized = normalize_optional_text(value)
        if not normalized:
            return None
        normalized = html.unescape(normalized).strip()
        if normalized.startswith("//"):
            normalized = f"https:{normalized}"
        return normalized

    def _extract_detail_url(self, card: Locator, base_url: str) -> Optional[str]:
        href = self._safe_get_attribute(card.locator("a[href]").first, "href")
        if not href:
            return None
        return urljoin(base_url, href)

    def _extract_card_title(self, card: Locator) -> Optional[str]:
        for value in (
            self._safe_get_attribute(card.locator("img[alt]").first, "alt"),
            self._safe_inner_text(card),
        ):
            title = normalize_optional_text(value)
            if title:
                return re.sub(r"\s+", " ", title).strip()
        return None

    def _extract_external_item_id(
        self,
        *,
        ext: Dict[str, Any],
        detail_url: Optional[str],
        image_url: str,
    ) -> Optional[str]:
        for key in ("cs", "setsign", "strategy"):
            value = normalize_optional_text(ext.get(key))
            if value:
                return sha256_text(f"{self.site_name}|{key}|{value}")

        for value in (ext.get("objurl"), ext.get("url"), detail_url):
            normalized = normalize_optional_text(value)
            if normalized:
                return sha256_text(f"{self.site_name}|{unquote(normalized)}")
        return sha256_text(f"{self.site_name}|{image_url}")

    def _build_scrape_item(self, card_ref: FeedCardRef) -> ScrapeItemPayload:
        source_image_url = normalize_optional_text(card_ref.preview_image_url)
        if not source_image_url:
            raise RuntimeError("百度图片卡片缺少图片")

        external_item_id = normalize_optional_text(card_ref.external_item_id) or sha256_text(
            f"{self.site_name}|{card_ref.detail_url or source_image_url}"
        )
        show_ext = card_ref.raw_payload.get("show_ext") if isinstance(card_ref.raw_payload, dict) else {}
        show_ext = show_ext if isinstance(show_ext, dict) else {}

        raw_payload: Dict[str, Any] = {
            "feed": {
                "index": card_ref.index,
                "preview_image_url": source_image_url,
                "detail_url": normalize_optional_text(card_ref.detail_url),
                "source_page_url": normalize_optional_text(card_ref.author_url),
                "title": normalize_optional_text(card_ref.title),
                "external_item_id": external_item_id,
                "original_image_url": normalize_optional_text(show_ext.get("objurl")),
                "thumbnail_image_url": normalize_optional_text(show_ext.get("url")),
            },
            "detail": None,
            "thumbnail_only": True,
            "show_ext": show_ext or None,
        }

        return ScrapeItemPayload(
            site_name=self.site_name,
            source_image_url=source_image_url,
            detail_url=normalize_optional_text(card_ref.detail_url),
            prompt_text=None,
            external_item_id=external_item_id,
            author=None,
            raw_payload=raw_payload,
        )

    def _go_to_next_page(self, page: Page) -> bool:
        next_button = self._first_visible([page.locator(self.NEXT_PAGE_SELECTOR)])
        if next_button is None or self._is_next_button_disabled(next_button):
            return False

        before_signature = self._current_page_signature(page)
        try:
            next_button.scroll_into_view_if_needed(timeout=3000)
            next_button.click(timeout=5000, force=True)
        except Exception:
            return False

        page.wait_for_timeout(800)
        self._wait_for_page_change(page, before_signature=before_signature)
        self._dismiss_popups(page)
        self._wait_for_feed(page)
        return True

    def _wait_for_page_change(self, page: Page, *, before_signature: str) -> None:
        deadline = time.monotonic() + self.PAGE_CHANGE_TIMEOUT_MS / 1000
        while time.monotonic() < deadline:
            current_signature = self._current_page_signature(page)
            if current_signature and current_signature != before_signature:
                return
            page.wait_for_timeout(300)

    def _current_page_signature(self, page: Page) -> str:
        try:
            signature = page.evaluate(
                """
                () => {
                  const firstCard = document.querySelector('[data-module="image-cell"][data-show-ext], .cos-masonry-container-item [data-show-ext]');
                  const firstImage = firstCard?.querySelector('img[data-objurl], img[data-thumbnail-url], img');
                  return [
                    location.href,
                    firstCard?.getAttribute('data-order') || '',
                    firstCard?.getAttribute('data-show-ext')?.slice(0, 256) || '',
                    firstImage?.getAttribute('data-objurl') || firstImage?.currentSrc || firstImage?.src || '',
                  ].join('|');
                }
                """
            )
            return normalize_text(signature)
        except Exception:
            return self._safe_page_url(page) or ""

    def _is_next_button_disabled(self, button: Locator) -> bool:
        try:
            if not button.is_enabled(timeout=1000):
                return True
        except Exception:
            pass

        class_name = normalize_text(self._safe_get_attribute(button, "class")).lower()
        aria_disabled = normalize_text(self._safe_get_attribute(button, "aria-disabled")).lower()
        disabled = normalize_text(self._safe_get_attribute(button, "disabled")).lower()
        return "disabled" in class_name or aria_disabled == "true" or disabled in {"true", "disabled"}

    def _find_visible_feed_card(self, page: Page) -> Optional[Locator]:
        cards = page.locator(self.FEED_CARD_SELECTOR)
        count = self._safe_locator_count(cards)
        for index in range(count):
            card = cards.nth(index)
            try:
                if card.is_visible(timeout=200) and self._extract_card_image_url(card):
                    return card
            except Exception:
                continue
        return None

    def _first_visible(self, locators: List[Locator]) -> Optional[Locator]:
        for locator in locators:
            try:
                if locator.count() > 0 and locator.first.is_visible():
                    return locator.first
            except Exception:
                continue
        return None

    def _safe_locator_count(self, locator: Locator) -> int:
        try:
            return locator.count()
        except Exception:
            return 0

    def _safe_get_attribute(self, locator: Locator, attribute_name: str) -> Optional[str]:
        try:
            if locator.count() == 0:
                return None
            return normalize_optional_text(locator.get_attribute(attribute_name, timeout=500))
        except Exception:
            return None

    def _safe_inner_text(self, locator: Locator) -> Optional[str]:
        try:
            if locator.count() == 0:
                return None
            return normalize_optional_text(locator.inner_text(timeout=500))
        except Exception:
            return None

    def _safe_page_url(self, page: Page) -> Optional[str]:
        try:
            return normalize_optional_text(page.url)
        except Exception:
            return None

    def _safe_page_title(self, page: Page) -> Optional[str]:
        try:
            return normalize_optional_text(page.title())
        except Exception:
            return None

    def _safe_body_excerpt(self, page: Page, limit: int = 500) -> Optional[str]:
        try:
            body_text = normalize_optional_text(page.locator("body").inner_text(timeout=1000))
        except Exception:
            return None
        if not body_text:
            return None
        return re.sub(r"\s+", " ", body_text)[:limit]
