from __future__ import annotations

import random
import time
from collections.abc import Iterable
from typing import Any, List, Optional, TYPE_CHECKING
from urllib.parse import quote, urljoin, urlparse

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page
else:
    try:
        from playwright.sync_api import Locator, Page
    except ModuleNotFoundError:
        Locator = Any
        Page = Any

from resource_filter.adapters.base import SiteAdapter
from resource_filter.exceptions import SkipScrapeItem
from resource_filter.models import AuthorPayload, FeedCardRef, ScrapeItemPayload
from resource_filter.utils import normalize_optional_text, normalize_text, parse_count, sha256_text


class XhsAdapter(SiteAdapter):
    site_name = "xhs"
    collect_feed_incrementally = True
    EXPLORE_URL = "https://www.xiaohongshu.com/explore"
    SEARCH_TAB_SELECTOR = (
        ".tab-scroll-container button.tab, "
        ".tab-scroll-container [role='tab'], "
        ".content-container button.tab, "
        ".content-container [role='tab'], "
        "button.tab, "
        "div.tab"
    )

    SEARCH_INPUT_SELECTOR = "input#search-input, input.search-input"
    FEED_CARD_SELECTOR = "section.note-item, div.note-item"
    FEED_CARD_DETAIL_LINK_SELECTOR = (
        "a.cover[href], "
        "a.title[href], "
        "a[href*='/search_result/'][target='_self'], "
        "a[href*='/explore/'][target='_self'], "
        "a[href*='/discovery/item/'][target='_self'], "
        "a[href*='/search_result/'], "
        "a[href*='/explore/'], "
        "a[href*='/discovery/item/']"
    )
    FEED_CARD_IMAGE_SELECTOR = "a.cover img, img[data-xhs-img], img"
    FEED_CARD_CLICK_SELECTOR = "a.cover[href], a.title[href], .cover, img[data-xhs-img], img"
    FEED_CARD_TITLE_SELECTOR = ".footer .title, a.title, .title span"
    FEED_CARD_AUTHOR_LINK_SELECTOR = "a.author[href*='/user/profile/'], a[href*='/user/profile/']"
    FEED_CARD_AUTHOR_NAME_SELECTOR = ".author .name, .name-time-wrapper .name, .name"
    FEED_CARD_TIME_SELECTOR = ".author .time, .name-time-wrapper .time, .time"
    FEED_CARD_LIKE_SELECTOR = ".like-wrapper .count, .count"

    DETAIL_READY_SELECTOR = "#detail-title, .note-content, .img-container img, .note-content .desc"
    DETAIL_TITLE_SELECTOR = "#detail-title, .note-content .title, .title"
    DETAIL_DESC_SELECTOR = "#detail-desc, .note-content .desc, .desc"
    DETAIL_DATE_SELECTOR = ".note-content .date, .date, time"
    DETAIL_LIKE_SELECTOR = ".left .like-wrapper .count, .like-wrapper .count"
    DETAIL_COLLECT_SELECTOR = ".left .collect-wrapper .count, .collect-wrapper .count"
    DETAIL_COMMENT_SELECTOR = ".left .chat-wrapper .count, .chat-wrapper .count"
    DETAIL_AUTHOR_LINK_SELECTOR = (
        "a.name[href*='/user/profile/'], "
        "a.author[href*='/user/profile/'], "
        "a[href*='/user/profile/']"
    )
    DETAIL_AUTHOR_NAME_SELECTOR = ".name .username, a.name .username, a.name, .author .name, .username"
    DETAIL_AUTHOR_AVATAR_SELECTOR = "a.author img, img.author-avatar, img[class*='avatar']"
    DETAIL_NOTE_IMAGE_SELECTOR = (
        ".note-content .swiper-slide img, "
        ".note-content .img-container img, "
        ".note-content img[data-xhs-img], "
        ".img-container img"
    )
    DETAIL_NEXT_IMAGE_SELECTOR = (
        ".img-container .swiper-button-next, "
        ".note-content .swiper-button-next, "
        "button[aria-label*='下一'], "
        "button[aria-label*='next'], "
        ".img-container [class*='next'], "
        ".img-container [class*='arrow'][class*='right']"
    )
    DETAIL_CLOSE_SELECTOR = (
        "div.close-circle, "
        "div.close-box, "
        "button.close, "
        "button[aria-label*='关闭'], "
        "svg[width='18'][height='18']"
    )
    POPUP_CLOSE_SELECTOR = (
        "div.close-circle, "
        "div.close-box, "
        "button.close, "
        "button[aria-label*='关闭'], "
        "button[aria-label*='Close'], "
        "[class*='close'][role='button'], "
        "[class*='Close'][role='button'], "
        ".login-container [class*='close'], "
        ".reds-modal [class*='close'], "
        ".modal [class*='close'], "
        "svg[width='18'][height='18']"
    )
    BLOCKING_POPUP_TEXTS = (
        "登录后查看",
        "登录后查看更多",
        "扫码登录",
        "打开小红书",
        "访问频繁",
        "安全验证",
        "请完成验证",
        "验证",
    )
    FEED_CARD_VIDEO_SELECTOR = (
        "video, "
        "source[type*='video'], "
        "[data-type*='video'], "
        "[class*='video'], "
        "[class*='play-icon'], "
        "[class*='playIcon'], "
        "[aria-label*='视频']"
    )
    DETAIL_VIDEO_SELECTOR = (
        ".note-content video, "
        ".note-content source[type*='video'], "
        ".note-content [data-type*='video'], "
        ".note-content [class*='video'], "
        ".note-content [class*='player'], "
        "video"
    )

    def open_inspiration(self, page: Page, entry_url: str, **kwargs) -> None:
        target_url = normalize_optional_text(entry_url) or self.EXPLORE_URL
        keyword = normalize_optional_text(kwargs.get("keyword"))
        preserve_entry_search_results = self._is_search_results_page(target_url)
        self._preserve_entry_search_results = preserve_entry_search_results

        page.goto(target_url, wait_until="domcontentloaded")
        self._pause(page, 1200, 260)
        self._dismiss_popups(page)

        if preserve_entry_search_results:
            print("小红书：入口已经是搜索结果页，按当前 URL 抓取，不重新提交关键词", flush=True)
        elif keyword:
            print(f"小红书：提交搜索关键词 {keyword}", flush=True)
            self._search_keyword(page, keyword)
            self._ensure_search_results_page(page, keyword)
        elif not self._is_search_results_page(page.url):
            raise ValueError("xhs inspiration 模式必须提供 keyword，或直接传入搜索结果页 entry_url")

        print(f"小红书：搜索结果页已打开 {page.url}", flush=True)
        if not preserve_entry_search_results:
            self._switch_search_channel(page, channel_id="image", channel_label="图文")
        self._wait_for_feed(page)

    def open_author_page(self, page: Page, author_url: str, **kwargs) -> None:
        author_query = normalize_optional_text(kwargs.get("author_query"))
        author_target = normalize_optional_text(author_url) or author_query
        if not author_target:
            raise ValueError("xhs author 模式必须提供作者主页 URL 或作者名称")

        if self._looks_like_profile_url(author_target):
            page.goto(author_target, wait_until="domcontentloaded")
            self._pause(page, 1200, 260)
        else:
            self._open_author_profile_by_query(page, author_target)

        self._dismiss_popups(page)
        self._ensure_author_notes_tab(page)
        self._wait_for_feed(page)

    def collect_feed_cards(self, page: Page, max_items: int | None = None, **kwargs) -> List[FeedCardRef]:
        crawl_mode = normalize_text(kwargs.get("crawl_mode") or "inspiration").lower()
        if crawl_mode == "author":
            self._wait_for_feed(page)
            return self._collect_current_feed_cards(page, max_items=max_items)

        if not getattr(self, "_preserve_entry_search_results", False):
            self._switch_search_channel(page, channel_id="image", channel_label="图文")
        tab_names = self._resolve_target_tab_names(page, kwargs.get("tab_names"), kwargs.get("tab_limit"))
        if not tab_names:
            print("小红书：未发现可切换标签，直接抓取当前结果页", flush=True)
            self._wait_for_feed(page)
            return self._collect_current_feed_cards(page, max_items=max_items)

        print(f"小红书：将依次切换 {len(tab_names)} 个标签：{', '.join(tab_names)}", flush=True)
        references: List[FeedCardRef] = []
        seen_keys: set[str] = set()

        for tab_name in tab_names:
            if not self._activate_tab(page, tab_name):
                print(f"小红书：未能切换标签 {tab_name}，已跳过", flush=True)
                continue
            self._wait_for_feed(page)
            current_refs = self._collect_current_feed_cards(page, max_items=max_items, tab_name=tab_name)
            for ref in current_refs:
                key = normalize_optional_text(ref.external_item_id) or normalize_optional_text(ref.detail_url)
                if not key:
                    key = f"{tab_name}:{ref.index}:{ref.preview_image_url or ''}"
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                references.append(ref)

        if references:
            return references

        self._wait_for_feed(page)
        return self._collect_current_feed_cards(page, max_items=max_items)

    def extract_item_from_feed(self, page: Page, card_ref: FeedCardRef, **kwargs) -> ScrapeItemPayload:
        detail_url = normalize_optional_text(card_ref.detail_url)
        if not detail_url:
            raise RuntimeError("未能从小红书卡片提取详情链接")
        self._prepare_feed_for_card(page, card_ref)
        listing_url = page.url
        self._open_feed_card(page, card_ref)
        try:
            detail_ready = self._wait_for_detail_ready(page, card_ref)
            if not detail_ready:
                fallback_item = self._build_preview_fallback_item(page, card_ref, detail_url)
                if fallback_item is not None:
                    return fallback_item
                raise RuntimeError(f"小红书详情页未加载完成，current_url={page.url}")
            if self._detail_contains_video(page):
                raise SkipScrapeItem("小红书视频作品不保存")

            final_detail_url = normalize_optional_text(page.url) or detail_url
            image_urls = self._extract_note_images(page)
            source_image_url = image_urls[0] if image_urls else normalize_optional_text(card_ref.preview_image_url)
            if not source_image_url:
                raise RuntimeError("未能从小红书详情页提取图片地址")

            title = normalize_optional_text(self._safe_inner_text(page.locator(self.DETAIL_TITLE_SELECTOR).first))
            description = normalize_optional_text(
                self._extract_description_text(page.locator(self.DETAIL_DESC_SELECTOR).first)
            )
            publish_time = normalize_optional_text(
                self._safe_inner_text(page.locator(self.DETAIL_DATE_SELECTOR).first)
            ) or card_ref.publish_time
            like_count = parse_count(self._safe_inner_text(page.locator(self.DETAIL_LIKE_SELECTOR).first))
            collect_count = parse_count(
                self._safe_inner_text(page.locator(self.DETAIL_COLLECT_SELECTOR).first)
            )
            comment_count = parse_count(
                self._safe_inner_text(page.locator(self.DETAIL_COMMENT_SELECTOR).first)
            )

            author_link = page.locator(self.DETAIL_AUTHOR_LINK_SELECTOR).first
            author_url = self._resolve_href(author_link, final_detail_url) or card_ref.author_url
            author_name = normalize_optional_text(
                self._safe_inner_text(page.locator(self.DETAIL_AUTHOR_NAME_SELECTOR).first)
            ) or card_ref.author_name
            avatar_url = normalize_optional_text(
                self._safe_get_attribute(page.locator(self.DETAIL_AUTHOR_AVATAR_SELECTOR).first, "src")
            )

            prompt_text = self._compose_prompt_text(title, description)
            note_id = card_ref.external_item_id or self._extract_note_id(final_detail_url)
            author_uid_seed = author_url or "|".join(part for part in (author_name, avatar_url) if part)
            author_uid = sha256_text(f"{self.site_name}|{author_uid_seed}") if author_uid_seed else None
            external_item_id = note_id or sha256_text(f"{self.site_name}|{final_detail_url}")

            raw_payload = {
                "feed": {
                    "index": card_ref.index,
                    "tab_name": card_ref.tab_name,
                    "detail_url": card_ref.detail_url,
                    "preview_image_url": card_ref.preview_image_url,
                    "title": card_ref.title,
                    "author_name": card_ref.author_name,
                    "author_url": card_ref.author_url,
                    "publish_time": card_ref.publish_time,
                    "like_count": card_ref.like_count,
                },
                "detail": {
                    "detail_url": final_detail_url,
                    "external_item_id": external_item_id,
                    "title": title,
                    "description": description,
                    "publish_time": publish_time,
                    "source_image_url": source_image_url,
                    "image_urls": image_urls,
                    "image_count": len(image_urls),
                    "like_count": like_count,
                    "collect_count": collect_count,
                    "comment_count": comment_count,
                    "author_name": author_name,
                    "author_url": author_url,
                    "avatar_url": avatar_url,
                    "prompt_text": prompt_text,
                },
            }

            return ScrapeItemPayload(
                site_name=self.site_name,
                source_image_url=source_image_url,
                detail_url=final_detail_url,
                prompt_text=prompt_text,
                like_count=like_count or card_ref.like_count,
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
            self._return_to_feed(page, listing_url, card_ref)

    def _search_keyword(self, page: Page, keyword: str) -> None:
        input_locator = self._first_visible(
            [
                page.locator("input#search-input").first,
                page.locator("input.search-input").last,
                page.locator(self.SEARCH_INPUT_SELECTOR).first,
            ]
        )
        if input_locator is None:
            self._goto_search_results(page, keyword)
            return
        self._clear_and_type_keyword(page, input_locator, keyword)

        search_trigger = self._first_visible(
            [
                page.locator(".input-button .search-icon").last,
                page.locator(".search-icon").last,
            ]
        )
        if search_trigger is not None:
            try:
                self._click_locator_like_human(page, search_trigger, timeout=3000)
            except Exception:
                input_locator.press("Enter")
        else:
            input_locator.press("Enter")

        self._pause(page, 1500, 420)
        if not self._is_search_results_page(page.url):
            self._goto_search_results(page, keyword)
            return
        self._dismiss_popups(page)

    def _ensure_search_results_page(self, page: Page, keyword: str) -> None:
        if self._is_search_results_page(page.url):
            return

        self._goto_search_results(page, keyword)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self._is_search_results_page(page.url):
                return
            self._pause(page, 300, 90, minimum_ms=160)

        raise RuntimeError(f"小红书搜索未进入结果页，current_url={page.url}，keyword={keyword}")

    def _goto_search_results(self, page: Page, keyword: str) -> None:
        expected_url = f"https://www.xiaohongshu.com/search_result?keyword={quote(keyword)}&source=web_explore_feed"
        print(f"小红书：直接打开搜索结果页 {expected_url}", flush=True)
        page.goto(expected_url, wait_until="domcontentloaded")
        self._pause(page, 1200, 260)
        self._dismiss_popups(page)

    def _open_author_profile_by_query(self, page: Page, author_query: str) -> None:
        page.goto(self.EXPLORE_URL, wait_until="domcontentloaded")
        self._pause(page, 1200, 260)
        self._dismiss_popups(page)
        self._search_keyword(page, author_query)
        self._switch_search_channel(page, channel_id="user", channel_label="用户")
        self._pause(page, 1200, 260)

        candidate = page.evaluate(
            """
            (query) => {
                const normalizedQuery = String(query || "").trim();
                const anchors = [...document.querySelectorAll("a[href*='/user/profile/']")];
                const visible = anchors
                  .map((anchor) => {
                    const rect = anchor.getBoundingClientRect();
                    const style = window.getComputedStyle(anchor);
                    const text = (anchor.innerText || anchor.textContent || "").trim().replace(/\\s+/g, " ");
                    return {
                      href: anchor.href || anchor.getAttribute("href") || "",
                      text,
                      visible: rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden",
                    };
                  })
                  .filter((item) => item.visible && item.href);
                const exact = visible.find((item) => item.text === normalizedQuery);
                if (exact) return exact;
                const partial = visible.find((item) => item.text.includes(normalizedQuery));
                return partial || visible[0] || null;
            }
            """,
            author_query,
        )
        if not candidate or not normalize_optional_text(candidate.get("href")):
            raise RuntimeError(f"未找到匹配作者：{author_query}")

        page.goto(candidate["href"], wait_until="domcontentloaded")
        self._pause(page, 1200, 260)

    def _switch_search_channel(self, page: Page, *, channel_id: str, channel_label: str) -> None:
        channel = self._first_visible(
            [
                page.locator(f"#{channel_id}.channel").first,
                page.locator(".channel").filter(has_text=channel_label).first,
            ]
        )
        if channel is None:
            return

        try:
            if "active" in (channel.get_attribute("class") or ""):
                return
        except Exception:
            pass

        self._click_locator_like_human(page, channel)
        self._pause(page, 1000, 280)

    def _resolve_target_tab_names(self, page: Page, tab_names: object, tab_limit: object) -> List[str]:
        explicit_names = self._normalize_tab_names(tab_names)
        available_names = self._wait_for_search_tabs(page)
        if available_names:
            print(f"小红书：发现可切换标签 {len(available_names)} 个：{', '.join(available_names)}", flush=True)
        else:
            print("小红书：未找到搜索结果标签栏", flush=True)

        if explicit_names:
            matched_names, missing_names = self._match_requested_tab_names(explicit_names, available_names)
            if missing_names:
                print(f"小红书：指定标签未找到，已跳过：{', '.join(missing_names)}", flush=True)
            return matched_names

        if not available_names:
            return []

        normalized_limit = self._coerce_positive_int(tab_limit) or 1
        if len(available_names) < normalized_limit:
            print(
                f"小红书：请求切换 {normalized_limit} 个标签，但只发现 {len(available_names)} 个，按已有标签继续",
                flush=True,
            )
        return available_names[:normalized_limit]

    def _wait_for_search_tabs(self, page: Page) -> List[str]:
        for _ in range(10):
            names = self._list_search_tab_names(page)
            if names:
                return names
            try:
                self._dismiss_popups(page)
            except Exception:
                pass
            self._pause(page, 500, 160, minimum_ms=180)
        return []

    def _match_requested_tab_names(
        self,
        requested_names: List[str],
        available_names: List[str],
    ) -> tuple[List[str], List[str]]:
        if not available_names:
            return [], requested_names

        matched_names: List[str] = []
        missing_names: List[str] = []
        for requested_name in requested_names:
            exact_match = next((name for name in available_names if name == requested_name), None)
            partial_match = next(
                (
                    name
                    for name in available_names
                    if requested_name in name or name in requested_name
                ),
                None,
            )
            matched_name = exact_match or partial_match
            if matched_name and matched_name not in matched_names:
                matched_names.append(matched_name)
            elif not matched_name:
                missing_names.append(requested_name)
        return matched_names, missing_names

    def _activate_tab(self, page: Page, tab_name: str) -> bool:
        tab = self._find_search_tab(page, tab_name)
        if tab is None:
            return False

        try:
            if "active" in (tab.get_attribute("class") or ""):
                return True
        except Exception:
            pass

        self._click_locator_like_human(page, tab)
        self._pause(page, 1200, 320)
        return True

    def _list_search_tab_names(self, page: Page) -> List[str]:
        names: List[str] = []
        tabs = page.locator(self.SEARCH_TAB_SELECTOR)
        for index in range(tabs.count()):
            locator = tabs.nth(index)
            try:
                if not locator.is_visible():
                    continue
            except Exception:
                pass
            text = self._read_search_tab_name(locator)
            if text and text not in names:
                names.append(text)
        return names

    def _read_search_tab_name(self, locator: Locator) -> Optional[str]:
        text = normalize_optional_text(self._safe_inner_text(locator))
        if text:
            return text
        for attribute_name in ("aria-details", "aria-label", "title"):
            text = normalize_optional_text(self._safe_get_attribute(locator, attribute_name))
            if text:
                return text
        return None

    def _find_search_tab(self, page: Page, tab_name: str) -> Optional[Locator]:
        normalized_target = normalize_optional_text(tab_name)
        if not normalized_target:
            return None

        partial_match: Optional[Locator] = None
        tabs = page.locator(self.SEARCH_TAB_SELECTOR)
        for index in range(tabs.count()):
            locator = tabs.nth(index)
            try:
                if not locator.is_visible():
                    continue
            except Exception:
                pass
            current_name = self._read_search_tab_name(locator)
            if not current_name:
                continue
            if current_name == normalized_target:
                return locator
            if partial_match is None and (normalized_target in current_name or current_name in normalized_target):
                partial_match = locator
        return partial_match

    def _prepare_feed_for_card(self, page: Page, card_ref: FeedCardRef) -> None:
        if normalize_optional_text(card_ref.tab_name):
            self._activate_tab(page, str(card_ref.tab_name))
        self._wait_for_feed(page)

    def _open_feed_card(self, page: Page, card_ref: FeedCardRef) -> None:
        detail_url = normalize_optional_text(card_ref.detail_url)
        try:
            card = self._resolve_feed_card(page, card_ref)
            click_target = self._first_visible(
                [
                    card.locator("a.cover[href]").first,
                    card.locator("a.title[href]").first,
                    card.locator(self.FEED_CARD_CLICK_SELECTOR).first,
                    card,
                ]
            )
            if click_target is None:
                raise RuntimeError(f"未能重新定位到小红书卡片 index={card_ref.index}")
            self._click_locator_like_human(page, click_target)
            self._pause(page, 1000, 260)
            return
        except Exception as exc:
            if not detail_url:
                raise exc
            print(f"小红书：点击卡片失败，改用详情链接打开 index={card_ref.index}", flush=True)
            page.goto(detail_url, wait_until="domcontentloaded")
            self._pause(page, 1000, 260)

    def _resolve_feed_card(self, page: Page, card_ref: FeedCardRef) -> Locator:
        for _ in range(6):
            matched_card = self._find_feed_card(page, card_ref)
            if matched_card is not None:
                return matched_card
            self._human_scroll_step(page, long_scroll=True)

        cards = page.locator(self.FEED_CARD_SELECTOR)
        if cards.count() <= card_ref.index:
            raise RuntimeError(f"未能重新定位到小红书卡片 index={card_ref.index}")
        return cards.nth(card_ref.index)

    def _find_feed_card(self, page: Page, card_ref: FeedCardRef) -> Optional[Locator]:
        target_external_id = normalize_optional_text(card_ref.external_item_id)
        target_detail_url = normalize_optional_text(card_ref.detail_url)
        target_preview_url = normalize_optional_text(card_ref.preview_image_url)
        cards = page.locator(self.FEED_CARD_SELECTOR)

        for index in range(cards.count()):
            card = cards.nth(index)
            if self._is_video_card(card):
                continue
            detail_href = self._safe_get_attribute(card.locator(self.FEED_CARD_DETAIL_LINK_SELECTOR).first, "href")
            detail_url = self._normalize_note_url(detail_href, page.url)
            external_item_id = self._extract_note_id(detail_url)
            preview_url = normalize_optional_text(
                self._safe_get_attribute(card.locator(self.FEED_CARD_IMAGE_SELECTOR).first, "src")
            )

            if target_external_id and external_item_id == target_external_id:
                return card
            if target_detail_url and detail_url == target_detail_url:
                return card
            if target_preview_url and preview_url == target_preview_url:
                return card
        return None

    def _collect_current_feed_cards(
        self,
        page: Page,
        *,
        max_items: int | None = None,
        tab_name: Optional[str] = None,
    ) -> List[FeedCardRef]:
        cards = page.locator(self.FEED_CARD_SELECTOR)
        references: List[FeedCardRef] = []
        count = cards.count()

        for index in range(count):
            card = cards.nth(index)
            if self._is_video_card(card):
                continue
            detail_href = self._safe_get_attribute(card.locator(self.FEED_CARD_DETAIL_LINK_SELECTOR).first, "href")
            detail_url = self._normalize_note_url(detail_href, page.url)
            if not detail_url:
                continue

            preview_image_url = normalize_optional_text(
                self._safe_get_attribute(card.locator(self.FEED_CARD_IMAGE_SELECTOR).first, "src")
            )
            author_link = card.locator(self.FEED_CARD_AUTHOR_LINK_SELECTOR).first
            author_url = self._resolve_href(author_link, page.url)
            author_name = normalize_optional_text(
                self._safe_inner_text(card.locator(self.FEED_CARD_AUTHOR_NAME_SELECTOR).first)
            )
            title = normalize_optional_text(
                self._safe_inner_text(card.locator(self.FEED_CARD_TITLE_SELECTOR).first)
            )
            publish_time = normalize_optional_text(
                self._safe_inner_text(card.locator(self.FEED_CARD_TIME_SELECTOR).first)
            )
            like_count = parse_count(self._safe_inner_text(card.locator(self.FEED_CARD_LIKE_SELECTOR).first))
            external_item_id = self._extract_note_id(detail_url)

            references.append(
                FeedCardRef(
                    index=index,
                    preview_image_url=preview_image_url,
                    author_name=author_name,
                    like_count=like_count,
                    detail_url=detail_url,
                    title=title,
                    author_url=author_url,
                    publish_time=publish_time,
                    tab_name=tab_name,
                    external_item_id=external_item_id,
                )
            )
            if max_items and len(references) >= max_items:
                break

        return references

    def _wait_for_feed(self, page: Page) -> None:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if self._find_visible_feed_card(page) is not None:
                return
            self._pause(page, 300, 90, minimum_ms=160)
        raise RuntimeError(f"小红书作品流未加载完成，未发现可见卡片，current_url={page.url}")

    def _find_visible_feed_card(self, page: Page) -> Optional[Locator]:
        cards = page.locator(self.FEED_CARD_SELECTOR)
        for index in range(cards.count()):
            card = cards.nth(index)
            image = card.locator(self.FEED_CARD_IMAGE_SELECTOR).first
            try:
                if image.count() > 0 and image.is_visible(timeout=200):
                    return card
            except Exception:
                continue
        return None

    def _load_all_cards(self, page: Page, max_items: int | None = None) -> None:
        last_count = 0
        stable_rounds = 0
        while stable_rounds < 3:
            current_count = page.locator(self.FEED_CARD_SELECTOR).count()
            valid_count = self._eligible_feed_card_count(page) if max_items else current_count
            if max_items and valid_count >= max_items:
                break
            if current_count == last_count:
                stable_rounds += 1
            else:
                stable_rounds = 0
                last_count = current_count
            self._human_scroll_step(page, long_scroll=not max_items or current_count + 1 < max_items)

    def load_more_feed_cards(self, page: Page, **kwargs) -> bool:
        before_keys = self._current_feed_card_keys(page)
        before_scroll = self._read_scroll_position(page)

        self._human_scroll_step(page, long_scroll=False)
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            current_keys = self._current_feed_card_keys(page)
            if len(current_keys - before_keys) > 0:
                return True

            current_scroll = self._read_scroll_position(page)
            if current_scroll and before_scroll:
                current_y, current_height, current_viewport = current_scroll
                before_y, _, _ = before_scroll
                if current_y > before_y + 40:
                    return True
                if current_y + current_viewport >= current_height - 8:
                    return False

            self._pause(page, 360, 140, minimum_ms=160)

        after_scroll = self._read_scroll_position(page)
        if not after_scroll or not before_scroll:
            return False
        return after_scroll[0] > before_scroll[0] + 40

    def _current_feed_card_keys(self, page: Page) -> set[str]:
        keys: set[str] = set()
        cards = page.locator(self.FEED_CARD_SELECTOR)
        for index in range(cards.count()):
            card = cards.nth(index)
            detail_href = self._safe_get_attribute(card.locator(self.FEED_CARD_DETAIL_LINK_SELECTOR).first, "href")
            detail_url = self._normalize_note_url(detail_href, page.url)
            if detail_url:
                keys.add(detail_url)
                continue
            preview_url = normalize_optional_text(
                self._safe_get_attribute(card.locator(self.FEED_CARD_IMAGE_SELECTOR).first, "src")
            )
            if preview_url:
                keys.add(preview_url)
        return keys

    def _read_scroll_position(self, page: Page) -> Optional[tuple[float, float, float]]:
        try:
            result = page.evaluate(
                """
                () => {
                  const element = document.scrollingElement || document.documentElement;
                  return {
                    y: window.scrollY || element.scrollTop || 0,
                    height: element.scrollHeight || document.body.scrollHeight || 0,
                    viewport: window.innerHeight || element.clientHeight || 0,
                  };
                }
                """
            )
        except Exception:
            return None
        try:
            return (float(result["y"]), float(result["height"]), float(result["viewport"]))
        except Exception:
            return None

    def _eligible_feed_card_count(self, page: Page) -> int:
        cards = page.locator(self.FEED_CARD_SELECTOR)
        count = 0
        for index in range(cards.count()):
            card = cards.nth(index)
            if self._is_video_card(card):
                continue
            detail_href = self._safe_get_attribute(card.locator(self.FEED_CARD_DETAIL_LINK_SELECTOR).first, "href")
            if self._normalize_note_url(detail_href, page.url):
                count += 1
        return count

    def _is_video_card(self, card: Locator) -> bool:
        try:
            if card.locator(self.FEED_CARD_VIDEO_SELECTOR).count() > 0:
                return True
        except Exception:
            pass

        try:
            return bool(
                card.evaluate(
                    """
                    (element) => {
                      const selectors = [
                        "video",
                        "source[type*='video']",
                        "[data-type*='video']",
                        "[class*='video']",
                        "[class*='play-icon']",
                        "[class*='playIcon']",
                        "[aria-label*='视频']",
                      ];
                      return selectors.some((selector) => element.querySelector(selector));
                    }
                    """
                )
            )
        except Exception:
            return False

    def _detail_contains_video(self, page: Page) -> bool:
        try:
            if page.locator(self.DETAIL_VIDEO_SELECTOR).count() > 0:
                return True
        except Exception:
            pass
        return False

    def _extract_note_images(self, page: Page) -> List[str]:
        image_urls: List[str] = []
        seen: set[str] = set()
        last_snapshot: tuple[str, ...] = tuple()
        stable_rounds = 0

        for _ in range(8):
            snapshot = tuple(self._read_current_note_images(page))
            for url in snapshot:
                if url not in seen:
                    seen.add(url)
                    image_urls.append(url)

            if snapshot == last_snapshot:
                stable_rounds += 1
            else:
                stable_rounds = 0
                last_snapshot = snapshot

            if stable_rounds >= 2:
                break

            if not self._advance_note_gallery(page):
                break

        return image_urls

    def _read_current_note_images(self, page: Page) -> List[str]:
        candidates: List[str] = []
        images = page.locator(self.DETAIL_NOTE_IMAGE_SELECTOR)
        for index in range(min(images.count(), 24)):
            locator = images.nth(index)
            src = normalize_optional_text(
                self._safe_get_attribute(locator, "src")
                or self._safe_get_attribute(locator, "data-src")
                or self._safe_get_attribute(locator, "data-original")
            )
            if not src:
                continue
            if "avatar" in src or "emoji" in src or src.startswith("data:"):
                continue
            if src not in candidates:
                candidates.append(src)
        return candidates

    def _ensure_author_notes_tab(self, page: Page) -> None:
        if self._find_visible_feed_card(page) is not None:
            return

        trigger = self._first_visible(
            [
                page.get_by_text("笔记", exact=True),
                page.get_by_text("作品", exact=True),
            ]
        )
        if trigger is not None:
            self._click_locator_like_human(page, trigger, timeout=3000)
            self._pause(page, 1000, 240)

    def _return_to_feed(self, page: Page, listing_url: str, card_ref: FeedCardRef) -> None:
        for _ in range(3):
            if self._find_visible_feed_card(page) is not None and page.locator(self.DETAIL_READY_SELECTOR).count() == 0:
                return

            close_trigger = self._first_visible([page.locator(self.DETAIL_CLOSE_SELECTOR).first])
            if close_trigger is not None:
                try:
                    self._click_locator_like_human(page, close_trigger, timeout=2000)
                    self._pause(page, 500, 180)
                except Exception:
                    pass

            if self._find_visible_feed_card(page) is not None and page.locator(self.DETAIL_READY_SELECTOR).count() == 0:
                return

            try:
                page.keyboard.press("Escape")
                self._pause(page, 600, 180)
            except Exception:
                pass

            if self._find_visible_feed_card(page) is not None and page.locator(self.DETAIL_READY_SELECTOR).count() == 0:
                return

            try:
                if normalize_optional_text(page.url) != normalize_optional_text(listing_url):
                    page.go_back(wait_until="domcontentloaded")
                    self._pause(page, 800, 220)
            except Exception:
                pass

            if self._find_visible_feed_card(page) is not None and page.locator(self.DETAIL_READY_SELECTOR).count() == 0:
                return

        page.goto(listing_url, wait_until="domcontentloaded")
        self._pause(page, 1200, 320)
        if normalize_optional_text(card_ref.tab_name):
            self._activate_tab(page, str(card_ref.tab_name))
        self._wait_for_feed(page)

    def _dismiss_popups(self, page: Page) -> None:
        for _ in range(3):
            close_trigger = self._first_visible([page.locator(self.POPUP_CLOSE_SELECTOR).first])
            if close_trigger is not None:
                try:
                    self._click_locator_like_human(page, close_trigger, timeout=1200)
                    self._pause(page, 220, 90)
                    continue
                except Exception:
                    pass
            try:
                page.keyboard.press("Escape")
            except Exception:
                return
            self._pause(page, 200, 90)

    def _wait_for_detail_ready(self, page: Page, card_ref: FeedCardRef) -> bool:
        deadline = time.monotonic() + 24

        while time.monotonic() < deadline:
            if self._has_visible_detail(page):
                return True

            if self._has_blocking_popup(page):
                self._dismiss_popups(page)
                if self._has_visible_detail(page):
                    return True

            self._pause(page, 360, 120, minimum_ms=180)

        return self._has_visible_detail(page)

    def _has_visible_detail(self, page: Page) -> bool:
        ready = page.locator(self.DETAIL_READY_SELECTOR)
        try:
            count = min(ready.count(), 8)
        except Exception:
            return False
        for index in range(count):
            try:
                if ready.nth(index).is_visible(timeout=200):
                    return True
            except Exception:
                continue
        return False

    def _has_blocking_popup(self, page: Page) -> bool:
        for text in self.BLOCKING_POPUP_TEXTS:
            try:
                locator = page.get_by_text(text, exact=False).first
                if locator.count() > 0 and locator.is_visible(timeout=200):
                    return True
            except Exception:
                continue
        return False

    def _build_preview_fallback_item(
        self,
        page: Page,
        card_ref: FeedCardRef,
        detail_url: str,
    ) -> Optional[ScrapeItemPayload]:
        source_image_url = normalize_optional_text(card_ref.preview_image_url)
        if not source_image_url:
            return None

        title = normalize_optional_text(card_ref.title)
        prompt_text = self._compose_prompt_text(title, None)
        external_item_id = card_ref.external_item_id or self._extract_note_id(detail_url) or sha256_text(
            f"{self.site_name}|{detail_url}|{source_image_url}"
        )
        author_uid = sha256_text(f"{self.site_name}|{card_ref.author_url}") if card_ref.author_url else None

        return ScrapeItemPayload(
            site_name=self.site_name,
            source_image_url=source_image_url,
            detail_url=detail_url,
            prompt_text=prompt_text,
            like_count=card_ref.like_count,
            external_item_id=external_item_id,
            author=AuthorPayload(
                uid=author_uid,
                name=card_ref.author_name,
                url=card_ref.author_url,
                avatar_url=None,
            ),
            raw_payload={
                "feed": {
                    "index": card_ref.index,
                    "tab_name": card_ref.tab_name,
                    "detail_url": card_ref.detail_url,
                    "preview_image_url": card_ref.preview_image_url,
                    "title": card_ref.title,
                    "author_name": card_ref.author_name,
                    "author_url": card_ref.author_url,
                    "publish_time": card_ref.publish_time,
                    "like_count": card_ref.like_count,
                },
                "detail": {
                    "detail_url": detail_url,
                    "external_item_id": external_item_id,
                    "title": title,
                    "description": None,
                    "publish_time": card_ref.publish_time,
                    "source_image_url": source_image_url,
                    "image_urls": [source_image_url],
                    "image_count": 1,
                    "like_count": card_ref.like_count,
                    "collect_count": None,
                    "comment_count": None,
                    "author_name": card_ref.author_name,
                    "author_url": card_ref.author_url,
                    "avatar_url": None,
                    "prompt_text": prompt_text,
                    "fallback_reason": "detail_not_ready",
                    "current_url": normalize_optional_text(page.url),
                },
            },
        )

    def _extract_description_text(self, locator: Locator) -> Optional[str]:
        text = normalize_optional_text(self._safe_inner_text(locator))
        if text:
            return text
        try:
            content = locator.evaluate(
                """
                (element) => {
                    const clone = element.cloneNode(true);
                    clone.querySelectorAll('a').forEach((anchor) => anchor.remove());
                    return (clone.innerText || clone.textContent || '').trim();
                }
                """
            )
        except Exception:
            content = None
        return normalize_optional_text(content)

    def _compose_prompt_text(self, title: Optional[str], description: Optional[str]) -> Optional[str]:
        parts = [normalize_optional_text(title), normalize_optional_text(description)]
        cleaned_parts = [part for part in parts if part]
        if not cleaned_parts:
            return None
        return "\n\n".join(cleaned_parts)

    def _normalize_note_url(self, href: Optional[str], base_url: str) -> Optional[str]:
        normalized_href = normalize_optional_text(href)
        if not normalized_href:
            return None
        absolute_url = urljoin(base_url, normalized_href)
        parsed = urlparse(absolute_url)
        segments = [segment for segment in parsed.path.split("/") if segment]
        if len(segments) < 2:
            return None
        if not (
            segments[-2] in {"search_result", "explore", "item"}
            or (len(segments) >= 3 and segments[-3:] and segments[-2] == "item")
        ):
            return None
        note_id = normalize_optional_text(segments[-1])
        if not note_id or note_id in {"explore", "search_result", "item"} or len(note_id) < 8:
            return None
        return absolute_url

    def _extract_note_id(self, detail_url: Optional[str]) -> Optional[str]:
        normalized_url = normalize_optional_text(detail_url)
        if not normalized_url:
            return None
        parsed = urlparse(normalized_url)
        segments = [segment for segment in parsed.path.split("/") if segment]
        if not segments:
            return None
        if segments[-2:] and segments[-2] in {"search_result", "explore", "item"}:
            return normalize_optional_text(segments[-1])
        return normalize_optional_text(segments[-1])

    def _is_search_results_page(self, url: str) -> bool:
        return "/search_result" in normalize_text(url)

    def _looks_like_profile_url(self, value: str) -> bool:
        normalized = normalize_text(value)
        return normalized.startswith("http") and "/user/profile/" in normalized

    def _normalize_tab_names(self, raw_value: object) -> List[str]:
        if raw_value is None:
            return []
        if isinstance(raw_value, str):
            candidates = raw_value.split(",")
        elif isinstance(raw_value, Iterable):
            candidates = list(raw_value)
        else:
            return []

        names: List[str] = []
        for candidate in candidates:
            normalized = normalize_optional_text(candidate)
            if normalized and normalized not in names:
                names.append(normalized)
        return names

    def _coerce_positive_int(self, value: object) -> Optional[int]:
        try:
            numeric_value = int(value)
        except Exception:
            return None
        return numeric_value if numeric_value > 0 else None

    def _pause(self, page: Page, base_ms: int, jitter_ms: int = 180, minimum_ms: int = 80) -> None:
        lower = max(minimum_ms, base_ms - max(jitter_ms, 0))
        upper = max(lower, base_ms + max(jitter_ms, 0))
        page.wait_for_timeout(random.randint(lower, upper))

    def _clear_and_type_keyword(self, page: Page, input_locator: Locator, keyword: str) -> None:
        self._click_locator_like_human(page, input_locator, timeout=3000)
        try:
            input_locator.press("Control+A")
            self._pause(page, 120, 60)
            input_locator.press("Backspace")
        except Exception:
            input_locator.fill("")
        self._pause(page, 180, 80)
        try:
            input_locator.type(keyword, delay=random.randint(80, 140))
        except Exception:
            input_locator.fill(keyword)
        self._pause(page, 260, 100)

    def _click_locator_like_human(self, page: Page, locator: Locator, timeout: int = 5000) -> None:
        locator.scroll_into_view_if_needed(timeout=3000)
        self._pause(page, 140, 80)
        self._hover_locator(page, locator)
        self._pause(page, 110, 60)
        try:
            locator.click(timeout=timeout)
            return
        except Exception as first_error:
            try:
                box = locator.bounding_box(timeout=1000)
            except Exception:
                box = None
            if not box:
                raise first_error
            click_x = box["x"] + max(6, min(box["width"] - 6, box["width"] * random.uniform(0.38, 0.62)))
            click_y = box["y"] + max(6, min(box["height"] - 6, box["height"] * random.uniform(0.38, 0.62)))
            page.mouse.click(click_x, click_y, delay=random.randint(40, 120))

    def _hover_locator(self, page: Page, locator: Locator) -> None:
        try:
            locator.hover(timeout=2000)
            return
        except Exception:
            pass

        try:
            box = locator.bounding_box(timeout=1000)
        except Exception:
            box = None
        if not box:
            return
        target_x = box["x"] + max(4, min(box["width"] - 4, box["width"] * random.uniform(0.35, 0.65)))
        target_y = box["y"] + max(4, min(box["height"] - 4, box["height"] * random.uniform(0.35, 0.65)))
        try:
            page.mouse.move(target_x, target_y, steps=random.randint(8, 16))
        except Exception:
            return

    def _human_scroll_step(self, page: Page, *, long_scroll: bool = False) -> None:
        step_count = 2 if long_scroll else 1
        for _ in range(step_count):
            delta_y = random.randint(720, 1280) if long_scroll else random.randint(420, 860)
            page.mouse.wheel(0, delta_y)
            self._pause(page, 360 if long_scroll else 260, 160)

    def _advance_note_gallery(self, page: Page) -> bool:
        next_button = self._first_visible(
            [
                page.locator(".img-container .swiper-button-next").first,
                page.locator(".note-content .swiper-button-next").first,
                page.locator("button[aria-label*='下一']").first,
                page.locator(self.DETAIL_NEXT_IMAGE_SELECTOR).first,
            ]
        )
        if next_button is not None:
            try:
                self._click_locator_like_human(page, next_button, timeout=2500)
                self._pause(page, 1100, 360)
                return True
            except Exception:
                pass
        return False

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
            href = locator.get_attribute("href", timeout=1000)
        except Exception:
            href = None
        normalized_href = normalize_optional_text(href)
        if not normalized_href:
            return None
        return urljoin(base_url, normalized_href)
