from __future__ import annotations

import json
import math
import re
import time
from html import unescape
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

if TYPE_CHECKING:
    from playwright.sync_api import Page
else:
    try:
        from playwright.sync_api import Page
    except ModuleNotFoundError:
        Page = Any

from resource_filter.adapters.base import SiteAdapter
from resource_filter.models import AuthorPayload, FeedCardRef, ScrapeItemPayload
from resource_filter.utils import normalize_optional_text, normalize_text, sha256_text


class PoseAdapter(SiteAdapter):
    site_name = "pose"
    BASE_URL = "https://www.photopose.art"
    DEFAULT_LOCALE = "zh"
    DEFAULT_PAGE_SIZE = 96
    DEFAULT_LIST_PATH = "/zh/poses"
    NEXT_DATA_SELECTOR = "#__NEXT_DATA__"
    NAVIGATION_TIMEOUT_MS = 90000
    NEXT_DATA_TIMEOUT_MS = 60000
    FETCH_ATTEMPT_TIMEOUT_MS = 30000
    POLITE_PAUSE_MS = 900

    def __init__(self) -> None:
        self._pose_summary_cache: Dict[str, Dict[str, Any]] = {}
        self._pose_detail_cache: Dict[str, Dict[str, Any]] = {}
        self._current_feed_url: Optional[str] = None

    def open_inspiration(self, page: Page, entry_url: str, **_: object) -> None:
        self._pose_summary_cache.clear()
        self._pose_detail_cache.clear()
        target_url = self._normalize_inspiration_entry_url(entry_url)
        self._load_next_data_for_url(page, target_url, allow_navigation=True)
        self._current_feed_url = target_url

    def open_author_page(self, page: Page, author_url: str, **_: object) -> None:
        raise ValueError("pose 站点暂不支持 author 模式")

    def collect_feed_cards(self, page: Page, max_items: int | None = None, **_: object) -> List[FeedCardRef]:
        references: List[FeedCardRef] = []
        seen_pose_ids: set[str] = set()

        current_url = self._normalize_inspiration_entry_url(self._current_feed_url or page.url or "")
        current_page = self._extract_page_number(current_url)
        page_size = self._extract_page_size(current_url)
        total_pages: Optional[int] = None

        while True:
            next_data = self._load_next_data_for_url(page, current_url, allow_navigation=False)
            page_props = self._extract_page_props(next_data)
            poses = page_props.get("poses")
            if not isinstance(poses, list) or not poses:
                break

            locale = self._resolve_locale(next_data, current_url)
            total_items = self._extract_total_items(page)
            if total_items is not None and page_size > 0:
                total_pages = max(1, math.ceil(total_items / page_size))

            new_items_on_page = 0
            for pose in poses:
                if not isinstance(pose, dict):
                    continue
                pose_id = normalize_optional_text(pose.get("id"))
                if not pose_id or pose_id in seen_pose_ids:
                    continue

                seen_pose_ids.add(pose_id)
                self._pose_summary_cache[pose_id] = pose
                references.append(self._build_feed_card_ref(pose, locale=locale, index=len(references)))
                new_items_on_page += 1

                if max_items and len(references) >= max_items:
                    return references

            if total_pages is not None and current_page >= total_pages:
                break
            if page_size > 0 and len(poses) < page_size:
                break
            if new_items_on_page == 0:
                break

            current_page += 1
            current_url = self._build_page_url(current_url, page_number=current_page, page_size=page_size)
            self._polite_pause(page)

        return references

    def extract_item_from_feed(self, page: Page, card_ref: FeedCardRef, **_: object) -> ScrapeItemPayload:
        detail_url = normalize_optional_text(card_ref.detail_url)
        pose_id = normalize_optional_text(card_ref.external_item_id) or self._extract_pose_id_from_url(detail_url)
        locale = self._extract_locale_from_url(detail_url) or self.DEFAULT_LOCALE

        next_data: Optional[Dict[str, Any]] = None
        pose_payload: Optional[Dict[str, Any]] = None

        if detail_url:
            try:
                self._polite_pause(page)
                next_data = self._load_next_data_for_url(page, detail_url, allow_navigation=False)
                detail_page_props = self._extract_page_props(next_data)
                pose_value = detail_page_props.get("pose")
                if isinstance(pose_value, dict):
                    pose_payload = pose_value
                    pose_id = normalize_optional_text(pose_payload.get("id")) or pose_id
                    if pose_id:
                        self._pose_detail_cache[pose_id] = pose_payload
                    locale = self._resolve_locale(next_data, detail_url)
            except Exception:
                pose_payload = None

        if pose_payload is None and pose_id:
            cached_detail = self._pose_detail_cache.get(pose_id)
            if isinstance(cached_detail, dict):
                pose_payload = cached_detail

        if pose_payload is None and pose_id:
            cached_summary = self._pose_summary_cache.get(pose_id)
            if isinstance(cached_summary, dict):
                pose_payload = cached_summary

        if pose_payload is None:
            raise RuntimeError("未能从 PhotoPose 提取姿势详情数据")

        return self._build_scrape_item(card_ref, pose_payload, locale=locale, detail_url=detail_url)

    def _wait_for_next_data(self, page: Page) -> None:
        self._wait_for_next_data_payload(page)

    def _goto_and_wait_for_next_data(self, page: Page, target_url: str) -> None:
        self._load_next_data_for_url(page, target_url, allow_navigation=True)

    def _load_next_data_for_url(self, page: Page, target_url: str, *, allow_navigation: bool = False) -> Dict[str, Any]:
        normalized_target_url = normalize_text(target_url)
        if not allow_navigation:
            return self._fetch_next_data_payload(page, normalized_target_url, timeout_ms=self.NEXT_DATA_TIMEOUT_MS)

        try:
            if normalize_text(page.url) != normalized_target_url:
                page.goto(normalized_target_url, wait_until="commit", timeout=self.NAVIGATION_TIMEOUT_MS)
            return self._wait_for_next_data_payload(page, timeout_ms=self.NEXT_DATA_TIMEOUT_MS)
        except Exception as exc:
            try:
                payload = self._fetch_next_data_payload(page, normalized_target_url, timeout_ms=self.NEXT_DATA_TIMEOUT_MS)
                print(f"PhotoPose 页面导航超时，已用 HTML fetch 兜底读取数据：{normalized_target_url}")
                return payload
            except Exception:
                raise exc

    def _wait_for_next_data_payload(self, page: Page, timeout_ms: int = 30000) -> Dict[str, Any]:
        page.locator(self.NEXT_DATA_SELECTOR).wait_for(state="attached", timeout=min(timeout_ms, 15000))
        deadline = time.monotonic() + timeout_ms / 1000
        last_error: Optional[Exception] = None

        while time.monotonic() < deadline:
            try:
                return self._extract_next_data(page)
            except (json.JSONDecodeError, RuntimeError) as exc:
                last_error = exc
                page.wait_for_timeout(250)

        if last_error is not None:
            raise RuntimeError(f"页面 __NEXT_DATA__ 数据未完整加载：{last_error}") from last_error
        raise RuntimeError("页面 __NEXT_DATA__ 数据未完整加载")

    def _fetch_next_data_payload(self, page: Page, target_url: str, timeout_ms: int) -> Dict[str, Any]:
        deadline = time.monotonic() + timeout_ms / 1000
        last_error: Optional[Exception] = None

        while time.monotonic() < deadline:
            try:
                response = page.context.request.get(
                    target_url,
                    timeout=self.FETCH_ATTEMPT_TIMEOUT_MS,
                    headers={"Cache-Control": "no-cache"},
                )
                if not response.ok:
                    raise RuntimeError(f"HTTP {response.status}")
                return self._extract_next_data_from_html(response.text())
            except Exception as exc:
                last_error = exc
                page.wait_for_timeout(self.POLITE_PAUSE_MS)

        if last_error is not None:
            raise RuntimeError(f"fetch 页面 __NEXT_DATA__ 数据未完整加载：{last_error}") from last_error
        raise RuntimeError("fetch 页面 __NEXT_DATA__ 数据未完整加载")

    def _extract_next_data_from_html(self, html: str) -> Dict[str, Any]:
        match = re.search(
            r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(?P<payload>.*?)</script>',
            html,
            re.DOTALL | re.IGNORECASE,
        )
        if not match:
            raise RuntimeError("fetch 页面缺少 __NEXT_DATA__ 数据")
        payload_text = normalize_optional_text(unescape(match.group("payload")))
        if not payload_text:
            raise RuntimeError("fetch 页面 __NEXT_DATA__ 数据为空")
        return json.loads(payload_text)

    def _polite_pause(self, page: Page) -> None:
        page.wait_for_timeout(self.POLITE_PAUSE_MS)

    def _normalize_inspiration_entry_url(self, entry_url: str) -> str:
        raw_url = normalize_optional_text(entry_url) or urljoin(self.BASE_URL, self.DEFAULT_LIST_PATH)
        if raw_url.startswith("/"):
            raw_url = urljoin(self.BASE_URL, raw_url)

        parsed = urlparse(raw_url)
        scheme = parsed.scheme or "https"
        netloc = parsed.netloc or urlparse(self.BASE_URL).netloc
        path = parsed.path or self.DEFAULT_LIST_PATH
        query = parse_qs(parsed.query, keep_blank_values=True)

        if not normalize_optional_text(query.get("page", [None])[0]):
            query["page"] = ["1"]
        if not normalize_optional_text(query.get("pageSize", [None])[0]):
            query["pageSize"] = [str(self.DEFAULT_PAGE_SIZE)]

        return urlunparse(
            (
                scheme,
                netloc,
                path,
                parsed.params,
                urlencode(query, doseq=True),
                parsed.fragment,
            )
        )

    def _build_page_url(self, base_url: str, *, page_number: int, page_size: Optional[int] = None) -> str:
        parsed = urlparse(self._normalize_inspiration_entry_url(base_url))
        query = parse_qs(parsed.query, keep_blank_values=True)
        query["page"] = [str(max(page_number, 1))]
        if page_size and page_size > 0:
            query["pageSize"] = [str(page_size)]
        return urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                urlencode(query, doseq=True),
                parsed.fragment,
            )
        )

    def _extract_page_number(self, url: str) -> int:
        parsed = urlparse(self._normalize_inspiration_entry_url(url))
        values = parse_qs(parsed.query).get("page", [])
        raw_value = normalize_optional_text(values[0]) if values else None
        if raw_value and raw_value.isdigit():
            return max(int(raw_value), 1)
        return 1

    def _extract_page_size(self, url: str) -> int:
        parsed = urlparse(self._normalize_inspiration_entry_url(url))
        values = parse_qs(parsed.query).get("pageSize", [])
        raw_value = normalize_optional_text(values[0]) if values else None
        if raw_value and raw_value.isdigit():
            return max(int(raw_value), 1)
        return self.DEFAULT_PAGE_SIZE

    def _extract_next_data(self, page: Page) -> Dict[str, Any]:
        raw_payload = page.locator(self.NEXT_DATA_SELECTOR).text_content(timeout=10000)
        payload_text = normalize_optional_text(raw_payload)
        if not payload_text:
            raise RuntimeError("页面缺少 __NEXT_DATA__ 数据")
        return json.loads(payload_text)

    def _extract_page_props(self, next_data: Dict[str, Any]) -> Dict[str, Any]:
        props = next_data.get("props")
        if not isinstance(props, dict):
            raise RuntimeError("Next.js 页面缺少 props")
        page_props = props.get("pageProps")
        if not isinstance(page_props, dict):
            raise RuntimeError("Next.js 页面缺少 pageProps")
        return page_props

    def _extract_total_items(self, page: Page) -> Optional[int]:
        try:
            body_text = page.locator("body").inner_text(timeout=3000)
        except Exception:
            return None

        match = re.search(r"共\s*(\d+)\s*项", body_text)
        if match:
            return int(match.group(1))

        match = re.search(r"Showing\s+\d+\s+to\s+\d+\s+of\s+(\d+)\s+items", body_text, re.IGNORECASE)
        if match:
            return int(match.group(1))

        return None

    def _resolve_locale(self, next_data: Dict[str, Any], current_url: str) -> str:
        locale = normalize_optional_text(next_data.get("locale"))
        if locale:
            return locale

        try:
            page_props = self._extract_page_props(next_data)
        except Exception:
            page_props = {}

        next_i18n = page_props.get("_nextI18Next")
        if isinstance(next_i18n, dict):
            locale = normalize_optional_text(next_i18n.get("initialLocale"))
            if locale:
                return locale

        return self._extract_locale_from_url(current_url) or self.DEFAULT_LOCALE

    def _extract_locale_from_url(self, url: Optional[str]) -> Optional[str]:
        parsed = urlparse(normalize_text(url))
        path_parts = [part for part in parsed.path.split("/") if part]
        if path_parts and path_parts[0] in {"zh", "en", "ja", "ko"}:
            return path_parts[0]
        return None

    def _extract_pose_id_from_url(self, url: Optional[str]) -> Optional[str]:
        parsed = urlparse(normalize_text(url))
        path_parts = [part for part in parsed.path.split("/") if part]
        if not path_parts:
            return None
        if path_parts[-2:] and len(path_parts) >= 2 and path_parts[-2] == "poses":
            return normalize_optional_text(path_parts[-1])
        if "poses" in path_parts:
            return normalize_optional_text(path_parts[-1])
        return None

    def _build_feed_card_ref(self, pose: Dict[str, Any], *, locale: str, index: int) -> FeedCardRef:
        pose_id = normalize_optional_text(pose.get("id"))
        detail_url = self._build_detail_url(pose_id, locale)
        preview_image_url = normalize_optional_text(pose.get("thumbnail_url")) or normalize_optional_text(
            pose.get("image_url")
        )

        return FeedCardRef(
            index=index,
            preview_image_url=preview_image_url,
            detail_url=detail_url,
            title=self._localized_field(pose, "title", locale),
            external_item_id=pose_id,
        )

    def _build_detail_url(self, pose_id: Optional[str], locale: str) -> Optional[str]:
        normalized_pose_id = normalize_optional_text(pose_id)
        if not normalized_pose_id:
            return None
        normalized_locale = normalize_optional_text(locale) or self.DEFAULT_LOCALE
        return urljoin(self.BASE_URL, f"/{normalized_locale}/poses/{normalized_pose_id}")

    def _build_scrape_item(
        self,
        card_ref: FeedCardRef,
        pose: Dict[str, Any],
        *,
        locale: str,
        detail_url: Optional[str],
    ) -> ScrapeItemPayload:
        pose_id = normalize_optional_text(pose.get("id")) or normalize_optional_text(card_ref.external_item_id)
        final_detail_url = normalize_optional_text(detail_url) or self._build_detail_url(pose_id, locale)
        title = self._localized_field(pose, "title", locale) or card_ref.title
        description = self._localized_field(pose, "description", locale)
        source_image_url = normalize_optional_text(pose.get("image_url")) or normalize_optional_text(
            card_ref.preview_image_url
        )
        if not source_image_url:
            raise RuntimeError("未能从 PhotoPose 提取原图地址")

        thumbnail_url = normalize_optional_text(pose.get("thumbnail_url")) or normalize_optional_text(
            card_ref.preview_image_url
        )
        difficulty = normalize_optional_text(pose.get("difficulty"))
        categories = self._extract_named_entries(pose.get("categories"), locale)
        tags = self._extract_named_entries(pose.get("tags"), locale)

        user = pose.get("user")
        author_name = None
        author_uid = None
        avatar_url = None
        if isinstance(user, dict):
            author_uid = normalize_optional_text(user.get("id"))
            author_name = normalize_optional_text(user.get("full_name")) or normalize_optional_text(user.get("email"))
            avatar_url = normalize_optional_text(user.get("avatar_url"))

        prompt_text = self._compose_prompt_text(title, description)
        external_item_id = pose_id or sha256_text(f"{self.site_name}|{final_detail_url or source_image_url}")

        raw_payload = {
            "feed": {
                "index": card_ref.index,
                "detail_url": final_detail_url,
                "preview_image_url": card_ref.preview_image_url,
                "title": card_ref.title,
                "external_item_id": card_ref.external_item_id,
            },
            "detail": {
                "detail_url": final_detail_url,
                "external_item_id": external_item_id,
                "title": title,
                "description": description,
                "source_image_url": source_image_url,
                "thumbnail_url": thumbnail_url,
                "difficulty": difficulty,
                "created_at": normalize_optional_text(pose.get("created_at")),
                "updated_at": normalize_optional_text(pose.get("updated_at")),
                "categories": categories,
                "tags": tags,
                "author_name": author_name,
                "author_uid": author_uid,
                "author_avatar_url": avatar_url,
            },
        }

        return ScrapeItemPayload(
            site_name=self.site_name,
            source_image_url=source_image_url,
            detail_url=final_detail_url,
            prompt_text=prompt_text,
            like_count=None,
            external_item_id=external_item_id,
            author=AuthorPayload(
                uid=author_uid,
                name=author_name,
                url=None,
                avatar_url=avatar_url,
            )
            if author_uid or author_name or avatar_url
            else None,
            raw_payload=raw_payload,
        )

    def _extract_named_entries(self, value: Any, locale: str) -> List[Dict[str, Any]]:
        if not isinstance(value, list):
            return []

        results: List[Dict[str, Any]] = []
        for entry in value:
            if not isinstance(entry, dict):
                continue
            entry_id = normalize_optional_text(entry.get("id"))
            if not entry_id:
                entry_id = normalize_optional_text(entry.get("category_id")) or normalize_optional_text(
                    entry.get("tag_id")
                )

            results.append(
                {
                    "id": entry_id,
                    "name": self._localized_name(entry, locale),
                    "slug": normalize_optional_text(entry.get("slug")),
                    "description": self._localized_field(entry, "description", locale),
                }
            )
        return results

    def _localized_name(self, payload: Dict[str, Any], locale: str) -> Optional[str]:
        return self._localized_field(payload, "name", locale)

    def _localized_field(self, payload: Dict[str, Any], field_name: str, locale: str) -> Optional[str]:
        direct_value = normalize_optional_text(payload.get(field_name))
        i18n_value = payload.get(f"{field_name}_i18n")
        if isinstance(i18n_value, dict):
            localized = normalize_optional_text(i18n_value.get(locale))
            if localized:
                return localized
            zh_value = normalize_optional_text(i18n_value.get("zh"))
            if zh_value:
                return zh_value
            en_value = normalize_optional_text(i18n_value.get("en"))
            if en_value:
                return en_value
        return direct_value

    def _compose_prompt_text(self, title: Optional[str], description: Optional[str]) -> Optional[str]:
        parts = [normalize_optional_text(title), normalize_optional_text(description)]
        normalized_parts = [part for part in parts if part]
        if not normalized_parts:
            return None
        return "\n".join(normalized_parts)
