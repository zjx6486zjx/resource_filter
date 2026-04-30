from __future__ import annotations

import html
import json
import re
import time
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from urllib.parse import urljoin, urlparse

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
from resource_filter.models import AuthorPayload, FeedCardRef, ScrapeItemPayload
from resource_filter.utils import normalize_optional_text, normalize_text, parse_count, sha256_text


class JingdongAdapter(SiteAdapter):
    site_name = "jingdong"
    DEFAULT_SEARCH_URL = "https://re.jd.com/search"

    SEARCH_INPUT_SELECTOR = (
        ".jd_search_box input.txt, "
        ".jd_search_row .input-wrapper input, "
        "input.txt[type='text']"
    )
    SEARCH_SUBMIT_SELECTOR = (
        ".jd_search_box a.btn, "
        ".jd_search_box .btn:has-text('搜索'), "
        "a.btn:has-text('搜索'), "
        "button:has-text('搜索')"
    )
    FEED_CARD_SELECTOR = ".jd-pick-content-item"
    FEED_CARD_IMAGE_SELECTORS = (
        "img[data-item]",
        ".imgWrapper img",
        ".img-wrapper img",
        "img[data-src*='360buyimg.com']",
        "img[src*='360buyimg.com']",
    )
    TITLE_SELECTOR = ".title-text-wrapper, .title-wrapper, .info-wrapper-title"
    SHOP_NAME_SELECTOR = ".shop-name"
    PRICE_SELECTOR = ".price-wrapper"
    NEXT_PAGE_SELECTOR = ".pagination-btn.pagination-next, .pagination-next, .pagination-btn:has-text('下一页')"

    NAVIGATION_TIMEOUT_MS = 90000
    POST_NAVIGATION_TIMEOUT_MS = 15000
    FEED_READY_TIMEOUT_MS = 45000
    SEARCH_RESULT_TIMEOUT_MS = 45000
    PAGE_CHANGE_TIMEOUT_MS = 15000

    PLACEHOLDER_IMAGE_PATTERNS = (
        "lazyloadding",
        "lazyloading",
        "loading.png",
        "component-libray/images",
        "header-tab-icon",
    )

    def open_inspiration(self, page: Page, entry_url: str, **kwargs: object) -> None:
        keyword = normalize_optional_text(kwargs.get("keyword"))
        target_url = self._normalize_inspiration_entry_url(entry_url)

        self._goto_page(page, target_url)
        self._dismiss_popups(page)

        if keyword:
            self._search_keyword(page, keyword)

        self._wait_for_feed(page)

    def open_author_page(self, page: Page, author_url: str, **_: object) -> None:
        raise ValueError("jingdong 站点暂不支持 author 模式")

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

        while True:
            self._load_current_page_cards(page, max_items=max_items, collected_count=len(references))
            self._collect_current_page_cards(
                page,
                references,
                seen_item_keys,
                max_items=max_items,
                skipped_cached_item_ids=skipped_cached_item_ids,
            )

            if max_items and len(references) >= max_items:
                break
            if not self._go_to_next_page(page):
                break

        return references

    def extract_item_from_feed(self, page: Page, card_ref: FeedCardRef, **_: object) -> ScrapeItemPayload:
        return self._build_scrape_item(card_ref)

    def _normalize_inspiration_entry_url(self, entry_url: str) -> str:
        raw_url = normalize_optional_text(entry_url) or self.DEFAULT_SEARCH_URL
        if raw_url.startswith("/"):
            raw_url = urljoin(self.DEFAULT_SEARCH_URL, raw_url)

        parsed = urlparse(raw_url)
        if not parsed.scheme:
            return f"https://{raw_url}"
        return raw_url

    def _goto_page(self, page: Page, target_url: str) -> None:
        try:
            page.goto(target_url, wait_until="commit", timeout=self.NAVIGATION_TIMEOUT_MS)
        except PlaywrightTimeoutError as exc:
            raise RuntimeError(f"京东页面连接超时，请检查网络或登录态：{target_url}") from exc
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
            raise RuntimeError("未能触发京东搜索，请检查搜索输入框或搜索按钮是否变化")

        self._wait_for_search_results(page, before_signature=before_signature)
        self._dismiss_popups(page)

    def _wait_for_search_input(self, page: Page) -> Locator:
        locator = page.locator(self.SEARCH_INPUT_SELECTOR).first
        try:
            locator.wait_for(state="visible", timeout=15000)
            return locator
        except Exception as exc:
            raise RuntimeError("未找到京东搜索输入框 .jd_search_box input.txt") from exc

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
            raise RuntimeError(f"京东搜索结果未加载完成：{last_error}") from last_error
        raise RuntimeError(self._build_feed_not_loaded_message(page))

    def _wait_for_feed(self, page: Page) -> None:
        deadline = time.monotonic() + self.FEED_READY_TIMEOUT_MS / 1000
        while time.monotonic() < deadline:
            if self._find_visible_feed_card(page) is not None:
                return
            page.wait_for_timeout(250)

        raise RuntimeError(self._build_feed_not_loaded_message(page))

    def _build_feed_not_loaded_message(self, page: Page) -> str:
        page_url = self._safe_page_url(page)
        title = self._safe_page_title(page)
        body_excerpt = self._safe_body_excerpt(page)
        card_count = self._safe_locator_count(page.locator(self.FEED_CARD_SELECTOR))

        parts = [
            "京东商品列表未加载完成",
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
            data_item = self._extract_card_data_item(card)
            image_url = self._extract_card_image_url(card, data_item=data_item)
            if not image_url:
                continue

            href = self._extract_detail_url(card, page.url, data_item=data_item)
            external_item_id = self._extract_external_item_id(
                data_item=data_item,
                detail_url=href,
                image_url=image_url,
            )
            item_key = external_item_id or href or image_url
            if not item_key or item_key in seen_item_keys:
                continue

            seen_item_keys.add(item_key)
            title = normalize_optional_text(data_item.get("title")) or self._extract_card_text(card, self.TITLE_SELECTOR)
            shop_name = normalize_optional_text(data_item.get("shopName")) or self._extract_card_text(
                card,
                self.SHOP_NAME_SELECTOR,
            )
            sales_count = self._extract_sales_count(card, data_item)

            references.append(
                FeedCardRef(
                    index=len(references),
                    preview_image_url=image_url,
                    author_name=shop_name,
                    like_count=sales_count,
                    detail_url=href,
                    title=title,
                    author_url=None,
                    external_item_id=external_item_id,
                    raw_payload={
                        "data_item": self._compact_data_item(data_item),
                        "price_text": self._extract_card_text(card, self.PRICE_SELECTOR),
                    },
                )
            )

            if max_items and len(references) >= max_items:
                break

    def _extract_card_data_item(self, card: Locator) -> Dict[str, Any]:
        raw_value = None
        data_item_locator = card.locator("[data-item]").first
        try:
            raw_value = data_item_locator.get_attribute("data-item", timeout=1000)
        except Exception:
            raw_value = None
        return self._parse_data_item(raw_value)

    def _parse_data_item(self, raw_value: Optional[str]) -> Dict[str, Any]:
        normalized = normalize_optional_text(raw_value)
        if not normalized:
            return {}

        decoded = html.unescape(normalized)
        try:
            parsed = json.loads(decoded)
        except (TypeError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _compact_data_item(self, data_item: Dict[str, Any]) -> Dict[str, Any]:
        keep_keys = (
            "id",
            "spuId",
            "title",
            "imageUrl",
            "landUrl",
            "shopId",
            "shopName",
            "venderId",
            "price",
            "cc",
            "sales",
            "monthSales",
            "click",
            "exp",
            "gct",
        )
        return {
            key: data_item.get(key)
            for key in keep_keys
            if data_item.get(key) not in (None, "", [], {})
        }

    def _extract_card_image_url(self, card: Locator, *, data_item: Optional[Dict[str, Any]] = None) -> Optional[str]:
        data_item = data_item or self._extract_card_data_item(card)

        # 京东真实可访问的图片地址通常在 DOM 的 data-src/currentSrc 里；
        # data-item.imageUrl 只是 jfs/... 路径片段，作为最后兜底。
        image_url = self._extract_dom_image_url(card)
        if image_url:
            return image_url

        image_url = self._normalize_image_url(data_item.get("imageUrl") if data_item else None)
        if image_url:
            return image_url

        return None

    def _extract_dom_image_url(self, card: Locator) -> Optional[str]:
        for selector in self.FEED_CARD_IMAGE_SELECTORS:
            image = card.locator(selector).first
            image_url = self._first_image_attribute(image)
            if image_url:
                return image_url

        try:
            image_url = card.evaluate(
                """
                (element) => {
                  const imageAttrs = ['currentSrc', 'src'];
                  const attrNames = ['data-src', 'data-original', 'data-lazy-img', 'data-lazyload'];
                  const images = [...element.querySelectorAll('img')];
                  for (const img of images) {
                    for (const prop of imageAttrs) {
                      const value = img[prop] || '';
                      if (value) return value;
                    }
                    for (const attr of attrNames) {
                      const value = img.getAttribute(attr) || '';
                      if (value) return value;
                    }
                  }

                  const styled = [...element.querySelectorAll('[style]')].find((node) => {
                    return (node.style?.backgroundImage || '').includes('url(');
                  });
                  return styled?.style?.backgroundImage || '';
                }
                """
            )
        except Exception:
            image_url = None

        return self._normalize_image_url(image_url)

    def _first_image_attribute(self, image: Locator) -> Optional[str]:
        for attribute_name in ("data-src", "src", "data-original", "data-lazy-img", "data-lazyload"):
            image_url = self._normalize_image_url(self._safe_get_attribute(image, attribute_name))
            if image_url:
                return image_url
        try:
            image_url = image.evaluate("(img) => img.currentSrc || img.src || ''", timeout=1000)
        except Exception:
            image_url = None
        return self._normalize_image_url(image_url)

    def _normalize_image_url(self, image_url: Optional[str]) -> Optional[str]:
        normalized = normalize_optional_text(image_url)
        if not normalized:
            return None

        normalized = html.unescape(normalized).strip()
        css_url_match = re.search(r"url\((['\"]?)(?P<url>.+?)\1\)", normalized)
        if css_url_match:
            normalized = css_url_match.group("url").strip()

        normalized_lower = normalized.lower()
        if any(pattern in normalized_lower for pattern in self.PLACEHOLDER_IMAGE_PATTERNS):
            return None

        if normalized.startswith("//"):
            normalized = f"https:{normalized}"
        elif normalized.startswith("/"):
            normalized = f"https://m.360buyimg.com{normalized}"
        elif normalized.startswith("jfs/"):
            normalized = f"https://m.360buyimg.com/mobilecms/s500x500_{normalized}!q70.dpg"

        if normalized.startswith("http://"):
            normalized = f"https://{normalized.removeprefix('http://')}"
        if not normalized.startswith(("http://", "https://")):
            return None

        return normalized

    def _extract_detail_url(
        self,
        card: Locator,
        base_url: str,
        *,
        data_item: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        data_item = data_item or self._extract_card_data_item(card)
        land_url = normalize_optional_text(data_item.get("landUrl") if data_item else None)
        if land_url:
            return self._resolve_href(land_url, base_url)

        href = self._resolve_href(self._safe_get_attribute(card.locator("a.item-link, a[href]").first, "href"), base_url)
        if href and not href.startswith("javascript:"):
            return href
        return None

    def _extract_card_text(self, card: Locator, selector: str) -> Optional[str]:
        text = normalize_optional_text(self._safe_inner_text(card.locator(selector).first))
        if not text:
            return None
        return re.sub(r"\s+", " ", text).strip()

    def _extract_sales_count(self, card: Locator, data_item: Dict[str, Any]) -> Optional[int]:
        for key in ("cc", "sales", "monthSales"):
            count = parse_count(normalize_optional_text(data_item.get(key)))
            if count is not None:
                return count

        text = " ".join(
            normalize_text(data_item.get(key))
            for key in ("cc", "sales", "monthSales", "gct")
            if normalize_text(data_item.get(key))
        )
        count = parse_count(text)
        if count is not None:
            return count
        return parse_count(self._extract_card_text(card, ".comment-wrapper, .sales, .month-sales"))

    def _extract_external_item_id(
        self,
        *,
        data_item: Dict[str, Any],
        detail_url: Optional[str],
        image_url: str,
    ) -> Optional[str]:
        for key in ("spuId", "id"):
            value = normalize_optional_text(data_item.get(key))
            if value:
                return value

        normalized_url = normalize_text(detail_url)
        match = re.search(r"item\.jd\.com/(\d+)\.html", normalized_url)
        if match:
            return match.group(1)
        match = re.search(r"[?&](?:skuId|spuId|wareId|id)=(\d+)", normalized_url)
        if match:
            return match.group(1)

        if normalized_url:
            return sha256_text(f"{self.site_name}|{normalized_url}")
        return sha256_text(f"{self.site_name}|{image_url}")

    def _build_scrape_item(self, card_ref: FeedCardRef) -> ScrapeItemPayload:
        source_image_url = normalize_optional_text(card_ref.preview_image_url)
        if not source_image_url:
            raise RuntimeError("京东商品卡片缺少图片")

        product_detail_url = normalize_optional_text(card_ref.detail_url)
        data_item = {}
        if isinstance(card_ref.raw_payload, dict):
            raw_data_item = card_ref.raw_payload.get("data_item")
            data_item = raw_data_item if isinstance(raw_data_item, dict) else {}

        external_item_id = normalize_optional_text(card_ref.external_item_id) or sha256_text(
            f"{self.site_name}|{product_detail_url or source_image_url}"
        )
        author_name = normalize_optional_text(card_ref.author_name)
        shop_id = normalize_optional_text(data_item.get("shopId")) or normalize_optional_text(data_item.get("venderId"))
        author_uid = shop_id or (sha256_text(f"{self.site_name}|shop|{author_name}") if author_name else None)
        prompt_text = normalize_optional_text(card_ref.title)

        raw_payload: Dict[str, Any] = {
            "feed": {
                "index": card_ref.index,
                "preview_image_url": source_image_url,
                "product_detail_url": product_detail_url,
                "title": prompt_text,
                "shop_name": author_name,
                "sales_count": card_ref.like_count,
                "external_item_id": external_item_id,
                "price": data_item.get("price"),
                "sku_id": data_item.get("id"),
                "spu_id": data_item.get("spuId"),
            },
            "detail": None,
            "thumbnail_only": True,
            "data_item": data_item or None,
        }

        return ScrapeItemPayload(
            site_name=self.site_name,
            source_image_url=source_image_url,
            detail_url=None,
            prompt_text=prompt_text,
            like_count=card_ref.like_count,
            external_item_id=external_item_id,
            author=AuthorPayload(
                uid=author_uid,
                name=author_name,
                url=None,
                avatar_url=None,
            )
            if author_name
            else None,
            raw_payload=raw_payload,
        )

    def _go_to_next_page(self, page: Page) -> bool:
        next_button = self._first_visible([page.locator(self.NEXT_PAGE_SELECTOR)])
        if next_button is None or self._is_next_button_disabled(next_button):
            return False

        before_signature = self._current_page_signature(page)
        try:
            next_button.scroll_into_view_if_needed(timeout=3000)
        except Exception:
            pass

        try:
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
                  const activePage =
                    document.querySelector('.pagination-item.pagination-active')?.textContent?.trim() || '';
                  const firstImage = document.querySelector('.jd-pick-content-item img[data-item], .jd-pick-content-item img');
                  const dataItem = firstImage?.getAttribute('data-item') || '';
                  return [
                    location.href,
                    activePage,
                    dataItem.slice(0, 256),
                    firstImage?.getAttribute('data-src') || firstImage?.currentSrc || firstImage?.src || '',
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
        return (
            "disabled" in class_name
            or "pagination-disabled" in class_name
            or aria_disabled == "true"
            or disabled in {"true", "disabled"}
        )

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
            return normalize_optional_text(locator.get_attribute(attribute_name, timeout=1000))
        except Exception:
            return None

    def _safe_inner_text(self, locator: Locator) -> Optional[str]:
        try:
            return normalize_optional_text(locator.inner_text(timeout=1000))
        except Exception:
            return None

    def _resolve_href(self, href: Optional[str], base_url: str) -> Optional[str]:
        normalized_href = normalize_optional_text(href)
        if not normalized_href:
            return None
        return urljoin(base_url, normalized_href)

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
