from __future__ import annotations

import time
from typing import Any, List, Optional, TYPE_CHECKING
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
from resource_filter.exceptions import SkipScrapeItem
from resource_filter.models import AuthorPayload, FeedCardRef, ScrapeItemPayload
from resource_filter.utils import normalize_optional_text, normalize_text, parse_count, sha256_text


class JimengAdapter(SiteAdapter):
    site_name = "jimeng"
    INSPIRATION_HOME_URL = "https://jimeng.jianying.com/ai-tool/home"
    MIN_LIKE_COUNT = 10

    FEED_CARD_SELECTOR = 'div[class*="masonry-layout-item"]'
    FEED_CARD_IMAGE_SELECTOR = 'img[data-apm-action="feed-item-image"], img[class*="cover-"]'
    FEED_AD_SELECTOR = 'img[data-apm-action="feed-item-video"]'
    FEED_AUTHOR_NAME_SELECTOR = 'span[class*="username"], div[class*="user-name"]'
    FEED_LIKE_SELECTOR = 'span[class*="count-"]'

    DETAIL_IMAGE_SELECTOR = (
        'div[class*="image-player-image"] img[data-apm-action="ai-generated-image-detail-card"], '
        'img[data-apm-action="ai-generated-image-detail-card"]'
    )
    DETAIL_AUTHOR_TRIGGER_SELECTOR = 'div[class*="user-section"], div[class*="author-"], div[class*="user-profile"]'
    DETAIL_AUTHOR_NAME_SELECTOR = 'div[class*="user-name"], span[class*="username"]'
    DETAIL_AUTHOR_AVATAR_SELECTOR = 'div[class*="user-avatar"] img, img[class*="avatar-image"], img[class*="dreamina-component-avatar"]'
    DETAIL_LIKE_SELECTOR = 'div[class*="favorite"] span[class*="count-"], span[class*="count-"]'
    DETAIL_PROMPT_SELECTOR = 'span[class*="prompt-value-container"], div[class*="prompt-value-text"], div[class*="prompt-value"]'
    DETAIL_CLOSE_SELECTOR = (
        'button.close-button-PTpYOA, '
        'button[class*="close-button-"], '
        'button[class*="close-button"], '
        'button[aria-label*="关闭"]'
    )

    def open_inspiration(self, page: Page, entry_url: str, **_: object) -> None:
        target_url = self._normalize_inspiration_entry_url(entry_url)
        page.goto(target_url, wait_until="domcontentloaded")
        self._dismiss_startup_overlay(page)
        page.wait_for_timeout(1200)

        if self._feed_cards(page).count() == 0:
            trigger = self._first_visible(
                [
                    page.locator("#Home"),
                    page.locator("[role='menuitem']").filter(has_text="灵感"),
                    page.get_by_text("灵感", exact=True),
                ]
            )
            if trigger is not None:
                trigger.click(timeout=3000)
                self._dismiss_startup_overlay(page)
                page.wait_for_timeout(1200)

        self._dismiss_startup_overlay(page)
        self._wait_for_feed(page)

    def _normalize_inspiration_entry_url(self, entry_url: str) -> str:
        parsed = urlparse(entry_url)
        if parsed.netloc == "jimeng.jianying.com" and parsed.path in ("", "/"):
            return self.INSPIRATION_HOME_URL
        return entry_url

    def open_author_page(self, page: Page, author_url: str, **_: object) -> None:
        page.goto(author_url, wait_until="domcontentloaded")
        self._dismiss_startup_overlay(page)
        page.wait_for_timeout(1200)
        self._dismiss_startup_overlay(page)
        self._wait_for_feed(page)

    def _dismiss_startup_overlay(self, page: Page) -> None:
        for _ in range(2):
            try:
                page.keyboard.press("Escape")
            except Exception:
                return
            page.wait_for_timeout(250)

    def collect_feed_cards(self, page: Page, max_items: int | None = None, **_: object) -> List[FeedCardRef]:
        self._wait_for_feed(page)
        self._load_all_cards(page, max_items=max_items)

        cards = self._feed_cards(page)
        count = cards.count()
        references: List[FeedCardRef] = []
        for index in range(count):
            card = cards.nth(index)
            if self._is_skippable_feed_card(card):
                continue
            preview_image_url = self._safe_get_attribute(card.locator(self.FEED_CARD_IMAGE_SELECTOR).first, "src")
            if not normalize_optional_text(preview_image_url):
                continue
            author_name = self._safe_inner_text(card.locator(self.FEED_AUTHOR_NAME_SELECTOR).first)
            like_count = parse_count(self._safe_inner_text(card.locator(self.FEED_LIKE_SELECTOR).first))
            if not self._has_enough_likes(like_count, allow_unknown=True):
                continue
            references.append(
                FeedCardRef(
                    index=index,
                    preview_image_url=normalize_optional_text(preview_image_url),
                    author_name=normalize_optional_text(author_name),
                    like_count=like_count,
                )
            )
            if max_items and len(references) >= max_items:
                break
        return references

    def extract_item_from_feed(self, page: Page, card_ref: FeedCardRef, **_: object) -> ScrapeItemPayload:
        listing_url = page.url
        self._open_feed_card(page, card_ref)

        try:
            detail_url = normalize_optional_text(page.url)
            source_image_url = normalize_optional_text(
                self._safe_get_attribute(page.locator(self.DETAIL_IMAGE_SELECTOR).first, "src")
            )
            if not source_image_url:
                raise RuntimeError("未能从详情页提取图片地址")

            prompt_text = self._extract_prompt(page)
            author_name = normalize_optional_text(
                self._safe_inner_text(page.locator(self.DETAIL_AUTHOR_NAME_SELECTOR).first)
            ) or card_ref.author_name
            avatar_url = normalize_optional_text(
                self._safe_get_attribute(page.locator(self.DETAIL_AUTHOR_AVATAR_SELECTOR).first, "src")
            )
            like_count = parse_count(self._safe_inner_text(page.locator(self.DETAIL_LIKE_SELECTOR).first))
            if like_count is None:
                like_count = card_ref.like_count
            if not self._has_enough_likes(like_count, allow_unknown=False):
                raise SkipScrapeItem(f"即梦作品点赞数不足 {self.MIN_LIKE_COUNT}：{like_count if like_count is not None else '未知'}")

            author_url = self._capture_author_url(page)
            author_uid_seed = author_url or "|".join(part for part in (author_name, avatar_url) if part)
            author_uid = sha256_text(f"{self.site_name}|{author_uid_seed}") if author_uid_seed else None
            external_item_id = sha256_text(f"{self.site_name}|{detail_url or source_image_url}")

            raw_payload = {
                "feed": {
                    "index": card_ref.index,
                    "preview_image_url": card_ref.preview_image_url,
                    "author_name": card_ref.author_name,
                    "like_count": card_ref.like_count,
                },
                "detail": {
                    "detail_url": detail_url,
                    "source_image_url": source_image_url,
                    "prompt_text": prompt_text,
                    "author_name": author_name,
                    "author_url": author_url,
                    "avatar_url": avatar_url,
                    "like_count": like_count,
                },
            }

            return ScrapeItemPayload(
                site_name=self.site_name,
                source_image_url=source_image_url,
                detail_url=detail_url,
                prompt_text=prompt_text,
                like_count=like_count,
                external_item_id=external_item_id,
                author=AuthorPayload(
                    uid=author_uid,
                    name=author_name,
                    url=author_url,
                    avatar_url=avatar_url,
                ),
                raw_payload=raw_payload,
            )
        finally:
            self._return_to_listing(page, listing_url)

    def _feed_cards(self, page: Page) -> Locator:
        return page.locator(self.FEED_CARD_SELECTOR)

    def _wait_for_feed(self, page: Page) -> None:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self._find_visible_feed_card(page) is not None:
                return
            page.wait_for_timeout(250)
        raise RuntimeError("作品流未恢复可见卡片，疑似仍停留在详情弹层或页面白屏")

    def _wait_for_detail(self, page: Page, previous_image_url: Optional[str] = None) -> None:
        deadline = time.monotonic() + 15
        last_image_url = normalize_optional_text(previous_image_url)
        detail_image = page.locator(self.DETAIL_IMAGE_SELECTOR).first

        while time.monotonic() < deadline:
            current_image_url = normalize_optional_text(self._safe_get_attribute(detail_image, "src"))
            if current_image_url and current_image_url != last_image_url:
                return

            try:
                if current_image_url and detail_image.is_visible(timeout=200):
                    return
            except Exception:
                pass

            page.wait_for_timeout(250)

        raise RuntimeError("即梦详情图未加载完成")

    def _load_all_cards(self, page: Page, max_items: int | None = None) -> None:
        last_count = 0
        stable_rounds = 0
        while stable_rounds < 3:
            current_count = self._feed_cards(page).count()
            valid_count = self._eligible_feed_card_count(page) if max_items else current_count
            if max_items and valid_count >= max_items:
                break
            if current_count == last_count:
                stable_rounds += 1
            else:
                stable_rounds = 0
                last_count = current_count
            page.mouse.wheel(0, 2200)
            page.wait_for_timeout(900)

    def _open_feed_card(self, page: Page, card_ref: FeedCardRef) -> None:
        card = self._resolve_feed_card(page, card_ref)
        if self._is_skippable_feed_card(card):
            raise RuntimeError("当前卡片是广告或视频位，已跳过")
        card.scroll_into_view_if_needed(timeout=3000)
        click_target = card.locator(self.FEED_CARD_IMAGE_SELECTOR).first
        if click_target.count() == 0:
            raise RuntimeError("当前卡片没有可点击的作品图片，已跳过")

        previous_url = page.url
        previous_detail_image_url = self._current_detail_image_url(page)
        click_target.click(timeout=5000, force=True)
        try:
            page.wait_for_url(lambda current_url: current_url != previous_url, timeout=4000)
        except PlaywrightTimeoutError:
            pass
        page.wait_for_timeout(400)
        self._wait_for_detail(page, previous_image_url=previous_detail_image_url)

    def _resolve_feed_card(self, page: Page, card_ref: FeedCardRef) -> Locator:
        preview_image_url = normalize_optional_text(card_ref.preview_image_url)
        if preview_image_url:
            for _ in range(6):
                matched_card = self._find_feed_card_by_preview_image(page, preview_image_url)
                if matched_card is not None:
                    return matched_card
                page.mouse.wheel(0, 2200)
                page.wait_for_timeout(700)

        self._load_all_cards(page, max_items=card_ref.index + 1)
        cards = self._feed_cards(page)
        if cards.count() <= card_ref.index:
            raise RuntimeError(f"未能重新定位到卡片 index={card_ref.index}")
        return cards.nth(card_ref.index)

    def _find_feed_card_by_preview_image(self, page: Page, preview_image_url: str) -> Optional[Locator]:
        cards = self._feed_cards(page)
        count = cards.count()
        for index in range(count):
            card = cards.nth(index)
            if self._is_skippable_feed_card(card):
                continue
            current_src = normalize_optional_text(
                self._safe_get_attribute(card.locator(self.FEED_CARD_IMAGE_SELECTOR).first, "src")
            )
            if current_src == preview_image_url:
                return card
        return None

    def _eligible_feed_card_count(self, page: Page) -> int:
        cards = self._feed_cards(page)
        count = cards.count()
        eligible = 0
        for index in range(count):
            card = cards.nth(index)
            if self._is_skippable_feed_card(card):
                continue
            preview_image_url = self._safe_get_attribute(card.locator(self.FEED_CARD_IMAGE_SELECTOR).first, "src")
            like_count = parse_count(self._safe_inner_text(card.locator(self.FEED_LIKE_SELECTOR).first))
            if normalize_optional_text(preview_image_url) and self._has_enough_likes(like_count, allow_unknown=True):
                eligible += 1
        return eligible

    def _has_enough_likes(self, like_count: Optional[int], *, allow_unknown: bool) -> bool:
        if like_count is None:
            return allow_unknown
        return like_count >= self.MIN_LIKE_COUNT

    def _is_skippable_feed_card(self, card: Locator) -> bool:
        if card.locator(self.FEED_AD_SELECTOR).count() > 0:
            return True
        return card.locator("video, source[type*='video']").count() > 0

    def _find_visible_feed_card(self, page: Page) -> Optional[Locator]:
        cards = self._feed_cards(page)
        count = cards.count()
        for index in range(count):
            card = cards.nth(index)
            if self._is_skippable_feed_card(card):
                continue
            try:
                preview_image = card.locator(self.FEED_CARD_IMAGE_SELECTOR).first
                if preview_image.count() > 0 and preview_image.is_visible(timeout=200):
                    return card
            except Exception:
                continue
        return None

    def _capture_author_url(self, page: Page) -> Optional[str]:
        trigger = self._first_visible(
            [
                page.locator(self.DETAIL_AUTHOR_TRIGGER_SELECTOR).first,
                page.locator(self.DETAIL_AUTHOR_NAME_SELECTOR).first,
            ]
        )
        if trigger is None:
            return None

        href = self._resolve_href(trigger, page.url)
        if href:
            return href

        detail_url = page.url
        try:
            with page.context.expect_page(timeout=1500) as popup_info:
                trigger.click(timeout=3000)
            popup = popup_info.value
            popup.wait_for_load_state("domcontentloaded", timeout=5000)
            author_url = normalize_optional_text(popup.url)
            popup.close()
            return author_url
        except Exception:
            pass

        try:
            trigger.click(timeout=3000)
            page.wait_for_url(lambda current_url: current_url != detail_url, timeout=4000)
            page.wait_for_load_state("domcontentloaded", timeout=5000)
            author_url = normalize_optional_text(page.url)
            page.go_back(wait_until="domcontentloaded")
            page.wait_for_timeout(400)
            self._wait_for_detail(page)
            return author_url
        except Exception:
            try:
                if page.url != detail_url:
                    page.go_back(wait_until="domcontentloaded")
                    page.wait_for_timeout(400)
                    self._wait_for_detail(page)
            except Exception:
                pass
            return None

    def _return_to_listing(self, page: Page, listing_url: str) -> None:
        for _ in range(3):
            if self._is_listing_ready(page):
                return

            if self._is_detail_open(page):
                close_trigger = self._first_visible([page.locator(self.DETAIL_CLOSE_SELECTOR).first])
                if close_trigger is not None:
                    try:
                        close_trigger.click(timeout=2000)
                        page.wait_for_timeout(400)
                    except Exception:
                        pass

                close_deadline = time.monotonic() + 2.5
                while time.monotonic() < close_deadline:
                    if self._is_listing_ready(page):
                        return
                    page.wait_for_timeout(200)

                if self._is_detail_open(page):
                    try:
                        page.keyboard.press("Escape")
                        page.wait_for_timeout(500)
                    except Exception:
                        pass

                    escape_deadline = time.monotonic() + 1.5
                    while time.monotonic() < escape_deadline:
                        if self._is_listing_ready(page):
                            return
                        page.wait_for_timeout(200)

            if self._is_listing_ready(page):
                return

        page.goto(listing_url, wait_until="domcontentloaded")
        page.wait_for_timeout(1200)
        self._wait_for_feed(page)

    def _is_detail_open(self, page: Page) -> bool:
        detail_image = page.locator(self.DETAIL_IMAGE_SELECTOR).first
        if detail_image.count() == 0:
            return False
        try:
            return detail_image.is_visible(timeout=1000)
        except Exception:
            return False

    def _current_detail_image_url(self, page: Page) -> Optional[str]:
        return normalize_optional_text(
            self._safe_get_attribute(page.locator(self.DETAIL_IMAGE_SELECTOR).first, "src")
        )

    def _is_listing_ready(self, page: Page) -> bool:
        if self._is_detail_open(page):
            return False
        return self._find_visible_feed_card(page) is not None

    def _extract_prompt(self, page: Page) -> Optional[str]:
        candidates = page.locator(self.DETAIL_PROMPT_SELECTOR)
        for index in range(min(candidates.count(), 5)):
            text = normalize_optional_text(self._safe_inner_text(candidates.nth(index)))
            if not text:
                continue
            if text == "图片提示词":
                continue
            if len(text) >= 4:
                return text

        try:
            text = page.evaluate(
                """
                () => {
                    const allNodes = [...document.querySelectorAll('div, span')];
                    const label = allNodes.find((node) => node.textContent?.trim() === '图片提示词');
                    if (!label) return '';
                    const wrapper = label.parentElement?.nextElementSibling || label.nextElementSibling;
                    return wrapper?.textContent?.trim() || '';
                }
                """
            )
            return normalize_optional_text(text)
        except Exception:
            return None

    def _first_visible(self, locators: List[Locator]) -> Optional[Locator]:
        for locator in locators:
            try:
                if locator.count() > 0 and locator.first.is_visible():
                    return locator.first
            except Exception:
                continue
        return None

    def _safe_inner_text(self, locator: Locator) -> Optional[str]:
        try:
            return locator.inner_text(timeout=1000)
        except Exception:
            return None

    def _safe_get_attribute(self, locator: Locator, attribute_name: str) -> Optional[str]:
        try:
            return locator.get_attribute(attribute_name, timeout=1000)
        except Exception:
            return None

    def _resolve_href(self, locator: Locator, base_url: str) -> Optional[str]:
        try:
            href = locator.evaluate(
                """
                (element) => element.closest('a')?.href || element.querySelector('a')?.href || element.getAttribute('href')
                """
            )
        except Exception:
            href = None
        normalized_href = normalize_optional_text(href)
        if not normalized_href:
            return None
        return urljoin(base_url, normalized_href)
