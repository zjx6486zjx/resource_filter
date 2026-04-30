from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from urllib.parse import unquote, urljoin, urlparse, urlsplit, urlunsplit

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


class TaobaoAdapter(SiteAdapter):
    site_name = "taobao"
    DEFAULT_SEARCH_URL = "https://uland.taobao.com/sem/tbsearch"

    SEARCH_INPUT_SELECTOR = (
        "input#q[name='q'], "
        "input#q, "
        "input[name='q'][aria-label*='搜索'], "
        "input[aria-label*='请输入搜索文字']"
    )
    SEARCH_SUBMIT_SELECTOR = (
        "button[type='submit'], "
        "button:has-text('搜索'), "
        "input[type='submit'], "
        ".search-button, "
        "[class*='searchBtn']"
    )
    FEED_CARD_SELECTOR = "a[id^='item_id_'], a[class*='CardV2--doubleCardWrapper']"
    FEED_CARD_IMAGE_SELECTORS = (
        "img[class*='MainPic--mainPic']",
        "[class*='MainPic--mainPicWrapper'] img[src]",
        "img[src*='alicdn.com'][width='240']",
        "img[src*='alicdn.com'][height='240']",
    )
    TITLE_SELECTOR = "[class*='Title--title']"
    SHOP_NAME_SELECTOR = "[class*='ShopInfo--shopNameText'], [class*='ShopInfo--shopName']"
    SALES_SELECTOR = "[class*='Price--realSales']"
    NEXT_PAGE_SELECTOR = "button.next-next, button[aria-label*='下一页'], button:has-text('下一页')"

    NAVIGATION_TIMEOUT_MS = 90000
    POST_NAVIGATION_TIMEOUT_MS = 15000
    FEED_READY_TIMEOUT_MS = 45000
    SEARCH_RESULT_TIMEOUT_MS = 45000
    PAGE_CHANGE_TIMEOUT_MS = 15000
    PLACEHOLDER_IMAGE_PATTERNS = (
        "-2-tps-",
        "tps-64-32",
        "atmosphere_center_image",
        "lazyloadding",
        "lazyloading",
        "loading.png",
        "placeholder",
    )

    def open_inspiration(self, page: Page, entry_url: str, **kwargs: object) -> None:
        keyword = normalize_optional_text(kwargs.get("keyword"))
        target_url = self._normalize_inspiration_entry_url(entry_url)

        print(f"淘宝：打开入口 {target_url}", flush=True)
        self._goto_page(page, target_url)
        self._dismiss_popups(page)

        if keyword:
            print(f"淘宝：提交搜索关键词 {keyword}", flush=True)
            self._search_keyword(page, keyword)

        print("淘宝：等待商品列表加载...", flush=True)
        self._wait_for_feed(page)

    def open_author_page(self, page: Page, author_url: str, **_: object) -> None:
        raise ValueError("taobao 站点暂不支持 author 模式")

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
            print(f"淘宝：收集并解析第 {page_number} 页商品列表...", flush=True)
            self._load_current_page_cards(page, max_items=max_items, collected_count=len(references))
            before_count = len(references)
            self._collect_current_page_cards(
                page,
                references,
                seen_item_keys,
                max_items=max_items,
                skipped_cached_item_ids=skipped_cached_item_ids,
            )
            print(f"淘宝：第 {page_number} 页新增 {len(references) - before_count} 个，累计 {len(references)} 个", flush=True)

            if max_items and len(references) >= max_items:
                break
            print("淘宝：尝试进入下一页...", flush=True)
            if not self._go_to_next_page(page):
                print("淘宝：没有更多下一页。", flush=True)
                break
            page_number += 1

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
            raise RuntimeError(f"淘宝页面连接超时，请检查网络或登录态：{target_url}") from exc
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
        print("淘宝：等待搜索输入框...", flush=True)
        search_input = self._wait_for_search_input(page)
        before_signature = self._current_page_signature(page)

        search_input.fill(keyword, timeout=5000)
        page.wait_for_timeout(200)

        submitted = False
        try:
            search_input.press("Enter", timeout=3000)
            submitted = True
        except Exception:
            submitted = False

        if not submitted:
            search_button = self._first_visible([page.locator(self.SEARCH_SUBMIT_SELECTOR)])
            if search_button is not None:
                search_button.click(timeout=3000, force=True)
                submitted = True

        if not submitted:
            raise RuntimeError("未能触发淘宝搜索，请检查搜索输入框或搜索按钮是否变化")

        print("淘宝：等待搜索结果刷新...", flush=True)
        self._wait_for_search_results(page, before_signature=before_signature)
        self._dismiss_popups(page)

    def _wait_for_search_input(self, page: Page) -> Locator:
        locator = page.locator(self.SEARCH_INPUT_SELECTOR).first
        try:
            locator.wait_for(state="visible", timeout=15000)
            return locator
        except Exception as exc:
            raise RuntimeError("未找到淘宝搜索输入框 input#q") from exc

    def _wait_for_search_results(self, page: Page, *, before_signature: str) -> None:
        deadline = time.monotonic() + self.SEARCH_RESULT_TIMEOUT_MS / 1000
        next_notice = time.monotonic() + 5
        last_error: Optional[Exception] = None

        while time.monotonic() < deadline:
            try:
                if self._find_visible_feed_card(page) is not None:
                    current_signature = self._current_page_signature(page)
                    if not before_signature or current_signature != before_signature:
                        return
            except Exception as exc:
                last_error = exc
            if time.monotonic() >= next_notice:
                print("淘宝：仍在等待搜索结果...", flush=True)
                next_notice += 5
            page.wait_for_timeout(300)

        if self._find_visible_feed_card(page) is not None:
            return
        if last_error is not None:
            raise RuntimeError(f"淘宝搜索结果未加载完成：{last_error}") from last_error
        raise RuntimeError(self._build_feed_not_loaded_message(page))

    def _wait_for_feed(self, page: Page) -> None:
        deadline = time.monotonic() + self.FEED_READY_TIMEOUT_MS / 1000
        next_notice = time.monotonic() + 5
        while time.monotonic() < deadline:
            if self._find_visible_feed_card(page) is not None:
                return
            if time.monotonic() >= next_notice:
                print("淘宝：仍在等待商品列表...", flush=True)
                next_notice += 5
            page.wait_for_timeout(250)

        raise RuntimeError(self._build_feed_not_loaded_message(page))

    def _build_feed_not_loaded_message(self, page: Page) -> str:
        page_url = self._safe_page_url(page)
        title = self._safe_page_title(page)
        body_excerpt = self._safe_body_excerpt(page)
        card_count = self._safe_locator_count(page.locator(self.FEED_CARD_SELECTOR))

        parts = [
            "淘宝商品列表未加载完成",
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
                print(f"淘宝：当前页已加载 {current_count} 个商品卡片...", flush=True)
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
        if count:
            print(f"淘宝：开始解析当前页 {count} 个商品卡片...", flush=True)

        for index in range(count):
            if index == 0 or (index + 1) % 10 == 0:
                print(f"淘宝：正在解析当前页卡片 {index + 1}/{count}...", flush=True)

            card = cards.nth(index)
            image_url = self._extract_card_image_url(card)
            if not image_url:
                continue

            href = self._resolve_href(self._safe_get_attribute(card, "href"), page.url)
            dom_id = normalize_optional_text(self._safe_get_attribute(card, "id"))
            external_item_id = self._extract_external_item_id(dom_id=dom_id, detail_url=href, image_url=image_url)
            detail_url = self._normalize_detail_url(href, external_item_id=external_item_id)
            item_key = external_item_id or detail_url or image_url
            if not item_key or item_key in seen_item_keys:
                continue

            seen_item_keys.add(item_key)
            if external_item_id and external_item_id in skipped_cached_item_ids:
                continue

            title = self._extract_card_text(card, self.TITLE_SELECTOR)
            shop_name = self._extract_card_text(card, self.SHOP_NAME_SELECTOR)
            sales_count = parse_count(self._extract_card_text(card, self.SALES_SELECTOR))

            references.append(
                FeedCardRef(
                    index=len(references),
                    preview_image_url=image_url,
                    author_name=shop_name,
                    like_count=sales_count,
                    detail_url=detail_url,
                    title=title,
                    author_url=None,
                    external_item_id=external_item_id,
                    raw_payload=self._build_card_raw_payload(raw_detail_url=href, detail_url=detail_url),
                )
            )

            if max_items and len(references) >= max_items:
                break

    def _extract_card_image_url(self, card: Locator) -> Optional[str]:
        try:
            image_url = card.evaluate(
                """
                (element) => {
                  const readSrc = (img) => {
                    return img?.currentSrc || img?.src || img?.getAttribute('src') || img?.getAttribute('data-src') || '';
                  };
                  const isBadUrl = (src) => {
                    const lower = (src || '').toLowerCase();
                    return !lower.includes('alicdn.com') ||
                      lower.includes('-2-tps-') ||
                      lower.includes('tps-64-32') ||
                      lower.includes('atmosphere_center_image') ||
                      lower.includes('lazyloadding') ||
                      lower.includes('lazyloading') ||
                      lower.includes('loading.png') ||
                      lower.includes('placeholder');
                  };
                  const imageSize = (img) => {
                    const width = Number(img?.getAttribute('width') || img?.naturalWidth || img?.clientWidth || 0);
                    const height = Number(img?.getAttribute('height') || img?.naturalHeight || img?.clientHeight || 0);
                    return { width, height, area: width * height };
                  };
                  const selectors = [
                    'img[class*="MainPic--mainPic"]',
                    '[class*="MainPic--mainPicWrapper"] img[src]',
                    'img[src*="alicdn.com"][width="240"]',
                    'img[src*="alicdn.com"][height="240"]'
                  ];
                  for (const selector of selectors) {
                    const image = element.querySelector(selector);
                    const src = readSrc(image);
                    if (src && !isBadUrl(src)) {
                      return src;
                    }
                  }
                  const images = [...element.querySelectorAll('img')];
                  const candidates = images
                    .map((img) => ({ img, src: readSrc(img), ...imageSize(img) }))
                    .filter((item) => item.src && !isBadUrl(item.src) && Math.max(item.width, item.height) >= 160);
                  candidates.sort((left, right) => right.area - left.area);
                  return candidates[0]?.src || '';
                }
                """
            )
            normalized = self._normalize_image_url(image_url)
            if normalized:
                return normalized
        except Exception:
            pass

        for selector in self.FEED_CARD_IMAGE_SELECTORS:
            image = card.locator(selector).first
            image_url = self._first_image_attribute(image)
            if image_url:
                return image_url

        try:
            image_url = card.evaluate(
                """
                (element) => {
                  const badPatterns = [
                    '-2-tps-',
                    'tps-64-32',
                    'atmosphere_center_image',
                    'lazyloadding',
                    'lazyloading',
                    'loading.png',
                    'placeholder'
                  ];
                  const images = [...element.querySelectorAll('img')];
                  const candidates = images.map((img) => {
                    const src = img.currentSrc || img.src || img.getAttribute('src') || '';
                    const width = Number(img.getAttribute('width') || img.naturalWidth || 0);
                    const height = Number(img.getAttribute('height') || img.naturalHeight || 0);
                    return { src, width, height, area: width * height };
                  }).filter((item) => {
                    const lower = item.src.toLowerCase();
                    return lower.includes('alicdn.com') &&
                      Math.max(item.width, item.height) >= 160 &&
                      !badPatterns.some((pattern) => lower.includes(pattern));
                  });
                  candidates.sort((left, right) => right.area - left.area);
                  return candidates[0]?.src || '';
                }
                """
            )
        except Exception:
            image_url = None

        return self._normalize_image_url(image_url)

    def _first_image_attribute(self, image: Locator) -> Optional[str]:
        for attribute_name in ("src", "data-src", "data-ks-lazyload", "data-lazy-src"):
            image_url = self._normalize_image_url(self._safe_get_attribute(image, attribute_name))
            if image_url:
                return image_url
        return None

    def _normalize_image_url(self, image_url: Optional[str]) -> Optional[str]:
        normalized = normalize_optional_text(image_url)
        if not normalized:
            return None
        if normalized.startswith("//"):
            normalized = f"https:{normalized}"
        if normalized.startswith("http://img.alicdn.com/"):
            normalized = f"https://{normalized.removeprefix('http://')}"
        if not normalized.startswith(("http://", "https://")):
            return None
        normalized = self._normalize_alicdn_image_variant(normalized)
        if not normalized:
            return None
        if self._looks_like_placeholder_image_url(normalized):
            return None
        return normalized

    def _normalize_alicdn_image_variant(self, image_url: str) -> Optional[str]:
        parsed = urlsplit(image_url)
        if "alicdn.com" not in parsed.netloc.lower():
            return image_url

        if self._looks_like_placeholder_image_url(image_url):
            return None

        path = re.sub(
            r"(?i)(\.(?:jpg|jpeg|png|webp))(?:_[^/?#]*)+$",
            r"\1",
            parsed.path,
        )
        if path.lower().endswith(".avif"):
            return None
        return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment))

    def _looks_like_placeholder_image_url(self, image_url: str) -> bool:
        normalized = normalize_text(image_url).lower()
        if any(pattern in normalized for pattern in self.PLACEHOLDER_IMAGE_PATTERNS):
            return True

        for match in re.finditer(r"(?:tps-|[_-])(\d{1,4})[-x](\d{1,4})", normalized):
            width = int(match.group(1))
            height = int(match.group(2))
            if max(width, height) < 120:
                return True
        return False

    def _extract_card_text(self, card: Locator, selector: str) -> Optional[str]:
        text = normalize_optional_text(self._safe_inner_text(card.locator(selector).first))
        if not text:
            return None
        return re.sub(r"\s+", " ", text).strip()

    def _extract_external_item_id(
        self,
        *,
        dom_id: Optional[str],
        detail_url: Optional[str],
        image_url: str,
    ) -> Optional[str]:
        normalized_dom_id = normalize_text(dom_id)
        match = re.search(r"item_id_(\d+)", normalized_dom_id)
        if match:
            return match.group(1)

        normalized_url = normalize_text(detail_url)
        item_id = self._extract_item_id_from_url(normalized_url)
        if item_id:
            return item_id

        if normalized_url:
            return sha256_text(f"{self.site_name}|{normalized_url}")
        return sha256_text(f"{self.site_name}|{image_url}")

    def _normalize_detail_url(self, detail_url: Optional[str], *, external_item_id: Optional[str] = None) -> Optional[str]:
        normalized = normalize_optional_text(detail_url)
        external_id = normalize_optional_text(external_item_id)
        if external_id and external_id.isdigit():
            return self._canonical_item_url(external_id)

        item_id = self._extract_item_id_from_url(normalized)
        if item_id:
            return self._canonical_item_url(item_id)

        if not normalized:
            return None
        if len(normalized) > 1000:
            return None
        return normalized

    def _extract_item_id_from_url(self, detail_url: Optional[str]) -> Optional[str]:
        normalized_url = normalize_optional_text(detail_url)
        if not normalized_url:
            return None

        for candidate in self._decoded_url_variants(normalized_url):
            match = re.search(r"(?:[?&]|^)(?:id|itemId|item_id|skuId)=(\d+)", candidate)
            if match:
                return match.group(1)
        return None

    def _decoded_url_variants(self, value: str) -> List[str]:
        variants = [value]
        current = value
        for _ in range(3):
            decoded = unquote(current)
            if decoded == current:
                break
            variants.append(decoded)
            current = decoded
        return variants

    def _canonical_item_url(self, item_id: str) -> str:
        return f"https://item.taobao.com/item.htm?id={item_id}"

    def _build_card_raw_payload(self, *, raw_detail_url: Optional[str], detail_url: Optional[str]) -> Dict[str, Any]:
        normalized_raw_detail_url = normalize_optional_text(raw_detail_url)
        normalized_detail_url = normalize_optional_text(detail_url)
        if not normalized_raw_detail_url or normalized_raw_detail_url == normalized_detail_url:
            return {}
        return {"raw_detail_url_sha256": sha256_text(normalized_raw_detail_url)}

    def _build_scrape_item(self, card_ref: FeedCardRef) -> ScrapeItemPayload:
        source_image_url = normalize_optional_text(card_ref.preview_image_url)
        if not source_image_url:
            raise RuntimeError("淘宝商品卡片缺少缩略图")

        product_detail_url = normalize_optional_text(card_ref.detail_url)
        external_item_id = normalize_optional_text(card_ref.external_item_id) or sha256_text(
            f"{self.site_name}|{product_detail_url or source_image_url}"
        )
        author_name = normalize_optional_text(card_ref.author_name)
        author_uid = sha256_text(f"{self.site_name}|shop|{author_name}") if author_name else None
        prompt_text = normalize_optional_text(card_ref.title)

        feed_payload: Dict[str, Any] = {
            "index": card_ref.index,
            "preview_image_url": source_image_url,
            "product_detail_url": product_detail_url,
            "title": prompt_text,
            "shop_name": author_name,
            "sales_count": card_ref.like_count,
            "external_item_id": external_item_id,
        }
        raw_detail_url_sha256 = normalize_optional_text(card_ref.raw_payload.get("raw_detail_url_sha256"))
        if raw_detail_url_sha256:
            feed_payload["raw_detail_url_sha256"] = raw_detail_url_sha256

        raw_payload: Dict[str, Any] = {
            "feed": {
                **feed_payload,
            },
            "detail": None,
            "thumbnail_only": True,
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
                    document.querySelector('.next-current, [aria-current="page"]')?.textContent?.trim() || '';
                  const firstCard = document.querySelector("a[id^='item_id_']");
                  const firstImage = firstCard?.querySelector('img[class*="MainPic--mainPic"], img[src*="alicdn.com"]');
                  return [
                    location.href,
                    activePage,
                    firstCard?.id || '',
                    firstImage?.currentSrc || firstImage?.src || firstImage?.getAttribute('src') || '',
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
            or "next-disabled" in class_name
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
            if locator.count() == 0:
                return None
            return normalize_optional_text(locator.get_attribute(attribute_name, timeout=300))
        except Exception:
            return None

    def _safe_inner_text(self, locator: Locator) -> Optional[str]:
        try:
            if locator.count() == 0:
                return None
            return normalize_optional_text(locator.inner_text(timeout=300))
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
