from __future__ import annotations

import base64
import time
import re
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

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
from resource_filter.utils import normalize_optional_text, normalize_text, sha256_text


class MjAdapter(SiteAdapter):
    site_name = "mj"
    collect_feed_incrementally = True
    BASE_URL = "https://www.midjourney.com"
    DEFAULT_EXPLORE_PATH = "/explore"
    DEFAULT_TAB = "top"

    FEED_SCROLL_CONTAINER_SELECTOR = "#pageScroll"
    FEED_CARD_LINK_SELECTOR = '#pageScroll a[href^="/jobs/"]'
    FEED_CARD_IMAGE_SELECTOR = "img[src]"
    NAVIGATION_TIMEOUT_MS = 90000
    POST_NAVIGATION_TIMEOUT_MS = 15000
    FEED_READY_TIMEOUT_MS = 45000
    SECURITY_VERIFICATION_TIMEOUT_MS = 180000
    INCREMENTAL_BATCH_SIZE = 1

    DETAIL_PROMPT_SELECTOR = "div.notranslate p"
    DETAIL_START_FRAME_SELECTOR = 'button[title="Start Frame"] img'
    DETAIL_IMAGE_SELECTOR = 'img[src*="cdn.midjourney.com"]'
    DETAIL_VIDEO_SELECTOR = "video[src]"
    DETAIL_PARAMETER_TEXT_SELECTOR = 'div.flex.flex-wrap.gap-1 button span[class*="text-transparent"]'
    DETAIL_CLOSE_SELECTORS = (
        'button[aria-label*="close" i]',
        'button[aria-label*="Close" i]',
        'button[aria-label*="关闭"]',
        'button:has(svg path[d*="M4.293 4.293"])',
        '[role="dialog"] button:has(svg path[d*="M4.293 4.293"])',
    )
    CDN_HOST = "cdn.midjourney.com"
    CDN_THUMBNAIL_RE = re.compile(r"^(?P<prefix>.+)_\d+_N\.webp$", re.IGNORECASE)

    def __init__(self) -> None:
        self._resolved_image_url_cache: Dict[str, str] = {}
        self._incremental_seen_job_ids: set[str] = set()
        self._last_feed_url: Optional[str] = None

    def open_inspiration(self, page: Page, entry_url: str, **_: object) -> None:
        self._incremental_seen_job_ids.clear()
        target_url = self._normalize_inspiration_entry_url(entry_url)
        target_url = self._to_images_feed_url(target_url)
        self._last_feed_url = target_url
        self._goto_page(page, target_url)
        self._click_images_tab_if_available(page)
        self._ensure_feed_ready(page, preferred_url=target_url)
        page.wait_for_timeout(1200)

    def open_author_page(self, page: Page, author_url: str, **_: object) -> None:
        raise ValueError("mj 站点暂不支持 author 模式")

    def collect_feed_cards(
        self,
        page: Page,
        max_items: int | None = None,
        *,
        skip_external_item_ids: set[str] | None = None,
        **_: object,
    ) -> List[FeedCardRef]:
        self._ensure_feed_ready(page)

        references: List[FeedCardRef] = []
        seen_job_ids = self._incremental_seen_job_ids if self.collect_feed_incrementally else set()
        skipped_cached_job_ids = {
            normalize_text(job_id)
            for job_id in (skip_external_item_ids or set())
            if normalize_text(job_id)
        }
        collection_limit = self.INCREMENTAL_BATCH_SIZE if self.collect_feed_incrementally else max_items
        max_stable_rounds = 3 if self.collect_feed_incrementally else 6
        max_end_rounds = 1 if self.collect_feed_incrementally else 2
        stable_rounds = 0
        end_rounds = 0

        while stable_rounds < max_stable_rounds and end_rounds < max_end_rounds:
            discovered_items = self._collect_visible_cards(
                page,
                references,
                seen_job_ids,
                max_items=collection_limit,
                skipped_cached_job_ids=skipped_cached_job_ids,
            )
            if collection_limit and len(references) >= collection_limit:
                break

            if discovered_items == 0:
                stable_rounds += 1
            else:
                stable_rounds = 0

            reached_end = self._scroll_feed(page)
            if reached_end:
                end_rounds += 1
            else:
                end_rounds = 0

        return references

    def load_more_feed_cards(self, page: Page, **_: object) -> bool:
        if not self._feed_has_cards(page):
            try:
                self._ensure_feed_ready(page)
                return True
            except RuntimeError as exc:
                print(f"Midjourney 列表恢复失败，停止继续滚动：{exc}", flush=True)
                return False
        return not self._scroll_feed(page, step=450)

    def extract_item_from_feed(self, page: Page, card_ref: FeedCardRef, **_: object) -> ScrapeItemPayload:
        listing_url = normalize_optional_text(page.url)
        self._open_feed_card(page, card_ref)

        try:
            self._wait_for_detail(page)
            final_detail_url = normalize_optional_text(page.url) or normalize_optional_text(card_ref.detail_url)
            prompt_body = normalize_optional_text(self._safe_inner_text(page.locator(self.DETAIL_PROMPT_SELECTOR).first))
            prompt_parameters = self._extract_prompt_parameters(page)
            expected_job_id = normalize_optional_text(card_ref.external_item_id) or self._extract_job_id_from_href(
                final_detail_url
            )
            source_image_url, media_payload = self._extract_source_image_url(
                page,
                card_ref.preview_image_url,
                expected_job_id=expected_job_id,
            )
            if not source_image_url:
                raise RuntimeError("未能从 Midjourney 详情页提取图片地址")
            media_payload.update(self._extract_detail_image_payload(page, source_image_url))
            source_image_data_url = self._capture_detail_image_data_url(page, source_image_url)
            if source_image_data_url:
                source_image_content_type = self._data_url_content_type(source_image_data_url) or "image/png"
                media_payload.update(
                    {
                        "source_image_data_url_present": True,
                        "source_image_data_url_content_type": source_image_content_type,
                    }
                )
            else:
                source_image_content_type = None

            item = self._build_scrape_item(
                card_ref,
                detail_url=final_detail_url,
                prompt_body=prompt_body,
                prompt_parameters=prompt_parameters,
                source_image_url=source_image_url,
                author_name=card_ref.author_name,
            )
            if media_payload:
                detail_payload = item.raw_payload.get("detail")
                if isinstance(detail_payload, dict):
                    detail_payload.update(media_payload)
            if source_image_data_url:
                item.source_image_data_url = source_image_data_url
                extension = self._image_extension_from_content_type(source_image_content_type)
                item.source_image_filename = f"{expected_job_id or item.external_item_id or 'midjourney'}.{extension}"
                item.source_image_content_type = source_image_content_type or "image/png"
            if not normalize_optional_text(item.prompt_text):
                raise RuntimeError("未能从 Midjourney 详情页提取提示词")
            return item
        finally:
            try:
                self._return_to_feed(page, listing_url)
            except Exception as exc:
                print(f"  ⚠ Midjourney 返回列表失败，下一轮会重新打开入口页恢复：{exc}", flush=True)

    def _extract_source_image_url(
        self,
        page: Page,
        fallback_url: Optional[str],
        *,
        expected_job_id: Optional[str] = None,
    ) -> tuple[Optional[str], Dict[str, Any]]:
        video_frame_url, video_payload = self._extract_video_frame_url(page, expected_job_id=expected_job_id)
        if video_frame_url:
            return video_frame_url, video_payload

        detail_image_url = self._select_best_detail_image_url(page, expected_job_id=expected_job_id)
        if detail_image_url:
            return self._resolve_best_midjourney_image_url(page, detail_image_url), {}

        image = page.locator(self.DETAIL_START_FRAME_SELECTOR).first
        candidates = [
            self._select_largest_srcset_url(self._safe_get_attribute(image, "srcset")),
            self._safe_evaluate_locator(image, "el => el.currentSrc"),
            self._safe_get_attribute(image, "src"),
            *self._build_image_url_candidates_from_job_id(expected_job_id),
            fallback_url,
        ]

        for candidate in candidates:
            normalized_candidate = normalize_optional_text(candidate)
            if not normalized_candidate:
                continue
            return self._resolve_best_midjourney_image_url(page, normalized_candidate), {}
        return None, {}

    def _build_image_url_candidates_from_job_id(self, job_id: Optional[str]) -> List[str]:
        normalized_job_id = normalize_optional_text(job_id)
        if not normalized_job_id:
            return []
        return [
            f"https://{self.CDN_HOST}/{normalized_job_id}/0_0.jpeg",
            f"https://{self.CDN_HOST}/{normalized_job_id}/0_0.png",
            f"https://{self.CDN_HOST}/{normalized_job_id}/0_0.webp",
        ]

    def _select_best_detail_image_url(self, page: Page, *, expected_job_id: Optional[str] = None) -> Optional[str]:
        images = page.locator(self.DETAIL_IMAGE_SELECTOR)
        count = self._safe_locator_count(images)
        best_url: Optional[str] = None
        best_score: tuple[int, int, int, int, int] | None = None

        for index in range(count):
            image = images.nth(index)
            payload = self._extract_image_metadata(image)
            candidate_urls = [
                self._select_largest_srcset_url(normalize_optional_text(str(payload.get("srcset") or ""))),
                normalize_optional_text(str(payload.get("current_src") or "")),
                normalize_optional_text(str(payload.get("src") or "")),
                self._safe_get_attribute(image, "src"),
            ]
            for candidate_url in candidate_urls:
                normalized_url = normalize_optional_text(candidate_url)
                if not self._is_public_image_url(normalized_url):
                    continue
                score = self._score_detail_image_candidate(
                    normalized_url,
                    payload,
                    expected_job_id=expected_job_id,
                )
                if score is None:
                    continue
                if best_score is None or score > best_score:
                    best_score = score
                    best_url = normalized_url

        return best_url

    def _extract_detail_image_payload(self, page: Page, source_image_url: str) -> Dict[str, Any]:
        normalized_url = normalize_optional_text(source_image_url)
        if not normalized_url:
            return {}

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
                  const images = Array.from(document.images || []);
                  let best = null;
                  for (const img of images) {
                    const rawUrl = img.currentSrc || img.src || img.getAttribute('src') || '';
                    if (!rawUrl) continue;
                    let current;
                    try {
                      current = new URL(rawUrl, document.baseURI);
                    } catch (error) {
                      continue;
                    }
                    if (current.host !== target.host || current.pathname !== target.pathname) {
                      continue;
                    }
                    const rect = img.getBoundingClientRect();
                    const width = img.naturalWidth || Math.round(rect.width || img.clientWidth || 0);
                    const height = img.naturalHeight || Math.round(rect.height || img.clientHeight || 0);
                    const area = width * height;
                    if (width && height && (!best || area > best.area)) {
                      best = {
                        source_image_url: current.href,
                        source_image_width: width,
                        source_image_height: height,
                        source_image_area: area,
                        source_image_validation_source: 'detail_dom',
                      };
                    }
                  }
                  return best;
                }
                """,
                normalized_url,
            )
        except Exception:
            return {}

        if not isinstance(payload, dict):
            return {}
        return {
            key: value
            for key, value in payload.items()
            if key in {
                "source_image_url",
                "source_image_width",
                "source_image_height",
                "source_image_area",
                "source_image_validation_source",
            }
        }

    def _capture_detail_image_data_url(self, page: Page, source_image_url: str) -> Optional[str]:
        image = self._find_detail_image_locator_by_url(page, source_image_url)
        if image is None:
            return None
        canvas_data_url = self._capture_image_data_url_with_canvas(image)
        if canvas_data_url:
            return canvas_data_url
        try:
            image_bytes = image.screenshot(timeout=5000, type="jpeg", quality=78)
            content_type = "image/jpeg"
        except TypeError:
            try:
                image_bytes = image.screenshot(timeout=5000)
                content_type = "image/png"
            except Exception:
                return None
        except Exception:
            return None
        if not image_bytes:
            return None
        encoded = base64.b64encode(image_bytes).decode("ascii")
        return f"data:{content_type};base64,{encoded}"

    def _capture_image_data_url_with_canvas(self, image: Locator) -> Optional[str]:
        try:
            data_url = image.evaluate(
                """
                (img) => {
                  const width = img.naturalWidth || img.clientWidth || img.offsetWidth;
                  const height = img.naturalHeight || img.clientHeight || img.offsetHeight;
                  if (!width || !height) return '';
                  const maxSide = 1400;
                  const scale = Math.min(1, maxSide / Math.max(width, height));
                  const targetWidth = Math.max(1, Math.round(width * scale));
                  const targetHeight = Math.max(1, Math.round(height * scale));
                  const canvas = document.createElement('canvas');
                  canvas.width = targetWidth;
                  canvas.height = targetHeight;
                  const context = canvas.getContext('2d');
                  if (!context) return '';
                  context.drawImage(img, 0, 0, targetWidth, targetHeight);
                  return canvas.toDataURL('image/jpeg', 0.82);
                }
                """,
                timeout=5000,
            )
        except Exception:
            return None
        normalized = normalize_optional_text(data_url)
        if normalized and normalized.startswith("data:image/"):
            return normalized
        return None

    def _data_url_content_type(self, data_url: str) -> Optional[str]:
        header = normalize_text(data_url).split(",", 1)[0]
        if not header.lower().startswith("data:") or ";base64" not in header.lower():
            return None
        content_type = header[5:].split(";", 1)[0].strip().lower()
        return content_type or None

    def _image_extension_from_content_type(self, content_type: Optional[str]) -> str:
        normalized = normalize_text(content_type).split(";", 1)[0].lower()
        if normalized in {"image/jpeg", "image/jpg", "image/pjpeg"}:
            return "jpg"
        if normalized == "image/webp":
            return "webp"
        if normalized == "image/gif":
            return "gif"
        if normalized in {"image/bmp", "image/x-ms-bmp"}:
            return "bmp"
        return "png"

    def _find_detail_image_locator_by_url(self, page: Page, source_image_url: str) -> Optional[Locator]:
        normalized_url = normalize_optional_text(source_image_url)
        if not normalized_url:
            return None
        images = page.locator(self.DETAIL_IMAGE_SELECTOR)
        count = self._safe_locator_count(images)
        fallback: Optional[Locator] = None

        for index in range(count):
            image = images.nth(index)
            payload = self._extract_image_metadata(image)
            current_urls = [
                normalize_optional_text(str(payload.get("current_src") or "")),
                normalize_optional_text(str(payload.get("src") or "")),
                self._safe_get_attribute(image, "src"),
            ]
            if fallback is None and self._coerce_positive_int(payload.get("client_width")) and self._coerce_positive_int(
                payload.get("client_height")
            ):
                fallback = image
            for current_url in current_urls:
                if current_url and self._same_url_path(current_url, normalized_url):
                    return image

        return fallback

    def _same_url_path(self, left_url: str, right_url: str) -> bool:
        left = urlparse(normalize_text(left_url))
        right = urlparse(normalize_text(right_url))
        return bool(
            left.netloc
            and right.netloc
            and left.netloc.lower() == right.netloc.lower()
            and left.path == right.path
        )

    def _extract_image_metadata(self, image: Locator) -> Dict[str, Any]:
        payload = self._safe_evaluate_locator_payload(
            image,
            """
            (img) => {
              const rect = img.getBoundingClientRect();
              return {
                src: img.getAttribute('src') || '',
                current_src: img.currentSrc || img.src || '',
                srcset: img.getAttribute('srcset') || '',
                natural_width: img.naturalWidth || 0,
                natural_height: img.naturalHeight || 0,
                client_width: Math.round(rect.width || img.clientWidth || 0),
                client_height: Math.round(rect.height || img.clientHeight || 0),
                visible: !!(rect.width && rect.height),
              };
            }
            """,
        )
        return payload if isinstance(payload, dict) else {}

    def _score_detail_image_candidate(
        self,
        image_url: str,
        metadata: Dict[str, Any],
        *,
        expected_job_id: Optional[str] = None,
    ) -> Optional[tuple[int, int, int, int, int]]:
        normalized_url = normalize_optional_text(image_url)
        if not normalized_url:
            return None

        if expected_job_id and not self._url_matches_job(normalized_url, expected_job_id):
            return None

        parsed = urlparse(normalized_url)
        if parsed.netloc.lower() != self.CDN_HOST:
            return None

        path = parsed.path.lower()
        is_original = 0 if self.CDN_THUMBNAIL_RE.match(parsed.path) else 1
        extension_score = 3 if path.endswith((".png", ".jpg", ".jpeg")) else 2 if path.endswith(".webp") else 1
        visible_score = 1 if metadata.get("visible") else 0
        width = self._coerce_positive_int(metadata.get("natural_width")) or self._coerce_positive_int(
            metadata.get("client_width")
        )
        height = self._coerce_positive_int(metadata.get("natural_height")) or self._coerce_positive_int(
            metadata.get("client_height")
        )
        area = width * height

        return (visible_score, is_original, extension_score, area, len(normalized_url))

    def _extract_video_frame_url(
        self,
        page: Page,
        *,
        expected_job_id: Optional[str] = None,
    ) -> tuple[Optional[str], Dict[str, Any]]:
        videos = page.locator(self.DETAIL_VIDEO_SELECTOR)
        if self._safe_locator_count(videos) == 0:
            return None, {}

        video = self._select_video_locator(videos, expected_job_id=expected_job_id)
        metadata = self._prepare_video_for_frame_capture(video)
        if not metadata:
            metadata = self._extract_video_metadata(video)
        self._fill_video_attribute_metadata(video, metadata)

        poster_url = self._select_video_poster_source_url(page, metadata, expected_job_id=expected_job_id)
        if poster_url:
            metadata.update(
                {
                    "media_type": "video",
                    "source_image_kind": "video_poster",
                    "frame_capture_method": "poster_url",
                }
            )
            return poster_url, metadata

        data_url = self._capture_video_frame_with_canvas(video)
        capture_method = "canvas"
        if not data_url:
            data_url = self._capture_video_frame_with_screenshot(video)
            capture_method = "element_screenshot"
        if not data_url:
            return None, metadata

        metadata.update(
            {
                "media_type": "video",
                "source_image_kind": "video_first_frame",
                "frame_capture_method": capture_method,
            }
        )
        return data_url, metadata

    def _select_video_locator(self, videos: Locator, *, expected_job_id: Optional[str] = None) -> Locator:
        normalized_expected_job_id = normalize_optional_text(expected_job_id)
        count = self._safe_locator_count(videos)
        fallback = videos.first

        for index in range(count):
            video = videos.nth(index)
            metadata = self._extract_video_metadata(video)
            self._fill_video_attribute_metadata(video, metadata)
            if normalized_expected_job_id and not self._metadata_matches_job(metadata, normalized_expected_job_id):
                continue
            if self._is_locator_visible(video):
                return video
            if not normalized_expected_job_id:
                continue
            fallback = video

        return fallback

    def _fill_video_attribute_metadata(self, video: Locator, metadata: Dict[str, Any]) -> None:
        for key, attribute_name in (("poster_url", "poster"), ("video_url", "src")):
            if normalize_optional_text(str(metadata.get(key) or "")):
                continue
            attribute_value = self._safe_get_attribute(video, attribute_name)
            if attribute_value:
                metadata[key] = attribute_value

    def _select_video_poster_source_url(
        self,
        _page: Page,
        metadata: Dict[str, Any],
        *,
        expected_job_id: Optional[str] = None,
    ) -> Optional[str]:
        normalized_expected_job_id = normalize_optional_text(expected_job_id)
        candidates = [
            normalize_optional_text(str(metadata.get("poster_url") or "")),
            self._derive_video_poster_url(
                normalize_optional_text(str(metadata.get("video_url") or "")),
                expected_job_id=normalized_expected_job_id,
            ),
            self._build_video_poster_url_from_job_id(normalized_expected_job_id),
        ]
        for candidate_url in candidates:
            if normalized_expected_job_id and not self._url_matches_job(candidate_url, normalized_expected_job_id):
                continue
            if self._is_public_image_url(candidate_url):
                return candidate_url
        return None

    def _derive_video_poster_url(
        self,
        video_url: Optional[str],
        *,
        expected_job_id: Optional[str] = None,
    ) -> Optional[str]:
        normalized_url = normalize_optional_text(video_url)
        if not normalized_url:
            return None

        parsed = urlparse(normalized_url)
        if parsed.netloc.lower() != self.CDN_HOST or not parsed.path.lower().startswith("/video/"):
            return None
        if expected_job_id and not self._url_matches_job(normalized_url, expected_job_id):
            return None
        path_lower = parsed.path.lower()
        if not path_lower.endswith((".mp4", ".webm", ".mov", ".m4v")):
            return None

        stem = parsed.path.rsplit(".", 1)[0]
        return urlunparse((parsed.scheme, parsed.netloc, f"{stem}_640_N.webp", "", "", ""))

    def _build_video_poster_url_from_job_id(self, job_id: Optional[str]) -> Optional[str]:
        normalized_job_id = normalize_optional_text(job_id)
        if not normalized_job_id:
            return None
        return f"https://{self.CDN_HOST}/video/{normalized_job_id}/0_640_N.webp"

    def _metadata_matches_job(self, metadata: Dict[str, Any], job_id: str) -> bool:
        return any(
            self._url_matches_job(normalize_optional_text(str(metadata.get(key) or "")), job_id)
            for key in ("poster_url", "video_url")
        )

    def _url_matches_job(self, url: Optional[str], job_id: str) -> bool:
        normalized_url = normalize_text(url).lower()
        normalized_job_id = normalize_text(job_id).lower()
        return bool(normalized_url and normalized_job_id and normalized_job_id in normalized_url)

    def _is_public_image_url(self, image_url: Optional[str]) -> bool:
        normalized_url = normalize_optional_text(image_url)
        if not normalized_url:
            return False

        parsed = urlparse(normalized_url)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
            return False

        path = parsed.path.lower()
        return path.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".bmp"))

    def _prepare_video_for_frame_capture(self, video: Locator) -> Dict[str, Any]:
        try:
            payload = video.evaluate(
                """
                async (video) => {
                  const waitForEvent = (name, timeoutMs) => new Promise((resolve) => {
                    let done = false;
                    const finish = () => {
                      if (done) return;
                      done = true;
                      video.removeEventListener(name, finish);
                      resolve();
                    };
                    video.addEventListener(name, finish, { once: true });
                    setTimeout(finish, timeoutMs);
                  });

                  video.muted = true;
                  video.pause();
                  if (video.readyState < 2) {
                    try { video.load(); } catch (error) {}
                    await waitForEvent('loadeddata', 5000);
                  }
                  try {
                    if (Number.isFinite(video.duration) && video.duration > 0) {
                      video.currentTime = 0;
                      await waitForEvent('seeked', 3000);
                    }
                  } catch (error) {}

                  return {
                    video_url: video.currentSrc || video.src || '',
                    poster_url: video.poster || video.getAttribute('poster') || '',
                    video_width: video.videoWidth || 0,
                    video_height: video.videoHeight || 0,
                    video_ready_state: video.readyState || 0,
                    video_current_time: video.currentTime || 0,
                  };
                }
                """,
                timeout=10000,
            )
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _extract_video_metadata(self, video: Locator) -> Dict[str, Any]:
        payload = self._safe_evaluate_locator_payload(
            video,
            """
            (video) => ({
              video_url: video.currentSrc || video.src || '',
              poster_url: video.poster || video.getAttribute('poster') || '',
              video_width: video.videoWidth || 0,
              video_height: video.videoHeight || 0,
              video_ready_state: video.readyState || 0,
              video_current_time: video.currentTime || 0,
            })
            """,
        )
        return payload if isinstance(payload, dict) else {}

    def _capture_video_frame_with_canvas(self, video: Locator) -> Optional[str]:
        try:
            data_url = video.evaluate(
                """
                (video) => {
                  const width = video.videoWidth || video.clientWidth || video.offsetWidth;
                  const height = video.videoHeight || video.clientHeight || video.offsetHeight;
                  if (!width || !height) return '';
                  const canvas = document.createElement('canvas');
                  canvas.width = width;
                  canvas.height = height;
                  const context = canvas.getContext('2d');
                  if (!context) return '';
                  context.drawImage(video, 0, 0, width, height);
                  return canvas.toDataURL('image/png');
                }
                """,
                timeout=5000,
            )
        except Exception:
            return None
        return normalize_optional_text(data_url)

    def _capture_video_frame_with_screenshot(self, video: Locator) -> Optional[str]:
        try:
            image_bytes = video.screenshot(timeout=5000)
        except Exception:
            return None
        if not image_bytes:
            return None
        encoded = base64.b64encode(image_bytes).decode("ascii")
        return f"data:image/png;base64,{encoded}"

    def _resolve_best_midjourney_image_url(self, page: Page, image_url: str) -> str:
        normalized_url = normalize_text(image_url)
        if not normalized_url:
            return normalized_url
        cached_url = self._resolved_image_url_cache.get(normalized_url)
        if cached_url:
            return cached_url

        for candidate_url in self._promoted_midjourney_image_candidates(normalized_url):
            if self._image_url_is_available(page, candidate_url):
                self._resolved_image_url_cache[normalized_url] = candidate_url
                return candidate_url

        self._resolved_image_url_cache[normalized_url] = normalized_url
        return normalized_url

    def _promoted_midjourney_image_candidates(self, image_url: str) -> List[str]:
        normalized_url = normalize_optional_text(image_url)
        if not normalized_url:
            return []

        parsed = urlparse(normalized_url)
        if parsed.netloc.lower() != self.CDN_HOST:
            return []

        match = self.CDN_THUMBNAIL_RE.match(parsed.path)
        if not match:
            return []

        prefix = match.group("prefix")
        candidates: List[str] = []
        for extension in (".jpeg", ".png", ".webp", ".jpg"):
            candidate = urlunparse(
                (
                    parsed.scheme,
                    parsed.netloc,
                    f"{prefix}{extension}",
                    parsed.params,
                    parsed.query,
                    parsed.fragment,
                )
            )
            if candidate != normalized_url and candidate not in candidates:
                candidates.append(candidate)
        return candidates

    def _image_url_is_available(self, page: Page, image_url: str) -> bool:
        try:
            response = page.context.request.head(
                image_url,
                timeout=10000,
                headers=self._midjourney_image_request_headers(page),
            )
        except Exception:
            return False
        if not response.ok:
            return False
        content_type = normalize_text(response.headers.get("content-type")).lower()
        return not content_type or content_type.startswith("image/")

    def _midjourney_image_request_headers(self, page: Page) -> Dict[str, str]:
        user_agent = self._safe_page_user_agent(page) or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
        )
        return {
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": "https://www.midjourney.com/",
            "User-Agent": user_agent,
        }

    def _select_largest_srcset_url(self, srcset: Optional[str]) -> Optional[str]:
        raw_srcset = normalize_optional_text(srcset)
        if not raw_srcset:
            return None

        best_url: Optional[str] = None
        best_score = -1.0
        for raw_part in raw_srcset.split(","):
            part = raw_part.strip()
            if not part:
                continue
            pieces = part.split()
            candidate_url = normalize_optional_text(pieces[0] if pieces else "")
            if not candidate_url:
                continue

            score = 1.0
            if len(pieces) > 1:
                descriptor = pieces[-1].strip().lower()
                try:
                    if descriptor.endswith("w"):
                        score = float(descriptor[:-1])
                    elif descriptor.endswith("x"):
                        score = float(descriptor[:-1]) * 10000
                except ValueError:
                    score = 1.0

            if score > best_score:
                best_score = score
                best_url = candidate_url

        return best_url

    def _normalize_inspiration_entry_url(self, entry_url: str) -> str:
        raw_url = normalize_optional_text(entry_url) or urljoin(self.BASE_URL, self.DEFAULT_EXPLORE_PATH)
        if raw_url.startswith("/"):
            raw_url = urljoin(self.BASE_URL, raw_url)

        parsed = urlparse(raw_url)
        scheme = parsed.scheme or "https"
        netloc = parsed.netloc or urlparse(self.BASE_URL).netloc
        path = parsed.path or self.DEFAULT_EXPLORE_PATH
        query = parse_qs(parsed.query, keep_blank_values=True)
        if not normalize_optional_text(query.get("tab", [None])[0]):
            query["tab"] = [self.DEFAULT_TAB]

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

    def _to_images_feed_url(self, entry_url: str) -> str:
        parsed = urlparse(entry_url)
        query = parse_qs(parsed.query, keep_blank_values=True)
        query["tab"] = [self.DEFAULT_TAB]
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

    def _click_images_tab_if_available(self, page: Page) -> bool:
        try:
            clicked = page.evaluate(
                """
                () => {
                  const buttons = Array.from(document.querySelectorAll('button'));
                  const target = buttons.find((button) => {
                    const text = (button.innerText || button.textContent || '').replace(/\\s+/g, ' ').trim();
                    return text === 'Images' || text.endsWith(' Images');
                  });
                  if (!target) return false;
                  target.click();
                  return true;
                }
                """
            )
        except Exception:
            return False
        if clicked:
            page.wait_for_timeout(800)
        return bool(clicked)

    def _collect_visible_cards(
        self,
        page: Page,
        references: List[FeedCardRef],
        seen_job_ids: set[str],
        *,
        max_items: int | None,
        skipped_cached_job_ids: set[str],
    ) -> int:
        anchors = page.locator(self.FEED_CARD_LINK_SELECTOR)
        count = anchors.count()
        discovered_items = 0

        for index in range(count):
            anchor = anchors.nth(index)
            href = normalize_optional_text(self._safe_get_attribute(anchor, "href"))
            job_id = self._extract_job_id_from_href(href)
            if not job_id or job_id in seen_job_ids:
                continue
            discovered_items += 1
            if job_id in skipped_cached_job_ids:
                seen_job_ids.add(job_id)
                continue
            is_video_card = self._is_video_card(anchor)
            video = anchor.locator("video").first
            video_url = normalize_optional_text(self._safe_get_attribute(video, "src"))
            poster_url = normalize_optional_text(self._safe_get_attribute(video, "poster"))
            image_url = poster_url or normalize_optional_text(
                self._safe_get_attribute(anchor.locator(self.FEED_CARD_IMAGE_SELECTOR).first, "src")
            )
            detail_url = urljoin(self.BASE_URL, href or "")
            card = anchor.locator("xpath=..")
            author_name = self._extract_card_author_name(card)

            seen_job_ids.add(job_id)
            references.append(
                FeedCardRef(
                    index=index,
                    preview_image_url=image_url,
                    author_name=author_name,
                    detail_url=detail_url,
                    external_item_id=job_id,
                    raw_payload={
                        "media_type": "video" if is_video_card else "image",
                        "video_url": video_url,
                        "poster_url": poster_url,
                    },
                )
            )

            if max_items and len(references) >= max_items:
                break

        return discovered_items

    def _is_video_card(self, anchor: Locator) -> bool:
        try:
            return anchor.locator("video, source[type*='video']").count() > 0
        except Exception:
            return False

    def _extract_card_author_name(self, card: Locator) -> Optional[str]:
        text = normalize_optional_text(self._safe_inner_text(card))
        if not text:
            return None

        parts = [part.strip() for part in text.splitlines() if part.strip()]
        if not parts:
            return None

        candidate = parts[-1]
        if len(candidate) > 80:
            return None
        return candidate

    def _scroll_feed(self, page: Page, step: Optional[int] = None) -> bool:
        state = page.evaluate(
            """
            ({ selector, requestedStep }) => {
              const scroller = document.querySelector(selector);
              if (!scroller) {
                return { atEnd: true };
              }
              const maxScrollTop = Math.max(0, scroller.scrollHeight - scroller.clientHeight);
              const step = requestedStep || Math.max(Math.floor(scroller.clientHeight * 0.85), 800);
              scroller.scrollTop = Math.min(maxScrollTop, scroller.scrollTop + step);
              return {
                atEnd: scroller.scrollTop >= maxScrollTop - 4,
              };
            }
            """,
            {
                "selector": self.FEED_SCROLL_CONTAINER_SELECTOR,
                "requestedStep": step,
            },
        )
        page.wait_for_timeout(900)
        return bool(state.get("atEnd"))

    def _scroll_feed_to_top(self, page: Page) -> None:
        page.evaluate(
            """
            (selector) => {
              const scroller = document.querySelector(selector);
              if (scroller) {
                scroller.scrollTop = 0;
              }
            }
            """,
            self.FEED_SCROLL_CONTAINER_SELECTOR,
        )
        page.wait_for_timeout(600)

    def _wait_for_feed(self, page: Page) -> None:
        deadline = time.monotonic() + self.FEED_READY_TIMEOUT_MS / 1000
        verification_deadline: Optional[float] = None
        verification_message_printed = False

        while time.monotonic() < deadline or (
            verification_deadline is not None and time.monotonic() < verification_deadline
        ):
            if self._feed_has_cards(page):
                return

            if self._is_security_verification_page(page):
                if verification_deadline is None:
                    verification_deadline = time.monotonic() + self.SECURITY_VERIFICATION_TIMEOUT_MS / 1000
                if not verification_message_printed:
                    print("Midjourney 正在进行 Cloudflare 安全验证；请在有头浏览器中完成验证。")
                    verification_message_printed = True

            page.wait_for_timeout(250)

        if self._is_security_verification_page(page):
            raise RuntimeError(
                "Midjourney Cloudflare 安全验证未通过。请先用持久化用户目录完成验证，"
                "再用同一个 --user-data-dir 重跑抓取。"
            )
        if self._is_login_required_page(page):
            raise RuntimeError(
                "Midjourney 当前页面像是未登录状态。请在已开启 CDP 的 Chrome 里重新登录/刷新 Midjourney，"
                "确认 Explore 页面能看到作品卡片后再重跑抓取。"
            )
        raise RuntimeError(self._build_feed_not_loaded_message(page))

    def _ensure_feed_ready(self, page: Page, preferred_url: Optional[str] = None) -> None:
        try:
            self._wait_for_feed(page)
            return
        except RuntimeError as first_error:
            recovery_url = normalize_optional_text(preferred_url) or self._last_feed_url
            if not recovery_url:
                raise

            print("Midjourney 列表暂时为空，重新打开入口页恢复...", flush=True)
            self._goto_page(page, recovery_url)
            page.wait_for_timeout(1500)
            try:
                self._wait_for_feed(page)
                return
            except RuntimeError as second_error:
                raise RuntimeError(f"{second_error}；恢复前错误：{first_error}") from second_error

    def _feed_has_cards(self, page: Page) -> bool:
        if self._safe_locator_count(page.locator(self.FEED_SCROLL_CONTAINER_SELECTOR)) <= 0:
            return False
        return self._safe_locator_count(page.locator(self.FEED_CARD_LINK_SELECTOR)) > 0

    def _is_security_verification_page(self, page: Page) -> bool:
        try:
            title = normalize_text(page.title()).lower()
            if "just a moment" in title:
                return True
        except Exception:
            pass

        try:
            body_text = normalize_text(page.locator("body").inner_text(timeout=1000)).lower()
        except Exception:
            return False

        return (
            "performing security verification" in body_text
            or "security service to protect against malicious bots" in body_text
            or "verify you are human" in body_text
            or "checking if the site connection is secure" in body_text
            or "cloudflare" in body_text
        )

    def _is_login_required_page(self, page: Page) -> bool:
        if self._safe_locator_count(page.locator(self.FEED_CARD_LINK_SELECTOR)) > 0:
            return False
        try:
            body_text = normalize_text(page.locator("body").inner_text(timeout=1000)).lower()
        except Exception:
            return False
        return (
            "log in" in body_text
            and "sign up" in body_text
            and "draft mode" in body_text
        )

    def _build_feed_not_loaded_message(self, page: Page) -> str:
        page_url = self._safe_page_url(page)
        title = self._safe_page_title(page)
        body_excerpt = self._safe_body_excerpt(page)
        page_scroll_count = self._safe_locator_count(page.locator(self.FEED_SCROLL_CONTAINER_SELECTOR))
        job_link_count = self._safe_locator_count(page.locator('a[href*="/jobs/"]'))

        parts = [
            "Midjourney 作品流未加载完成",
            f"url={page_url or '<unknown>'}",
            f"title={title or '<empty>'}",
            f"pageScroll={page_scroll_count}",
            f"jobLinks={job_link_count}",
        ]
        if body_excerpt:
            parts.append(f"body={body_excerpt}")
        return "；".join(parts)

    def _prepare_feed_for_card(self, page: Page, card_ref: FeedCardRef) -> Locator:
        job_id = normalize_optional_text(card_ref.external_item_id) or self._extract_job_id_from_href(card_ref.detail_url)
        if not job_id:
            raise RuntimeError("未能识别 Midjourney 卡片 ID")

        for restart_from_top in (False, True):
            if restart_from_top:
                self._scroll_feed_to_top(page)

            for _ in range(80):
                card = self._find_feed_card_by_job_id(page, job_id)
                if card is not None:
                    card.scroll_into_view_if_needed(timeout=3000)
                    page.wait_for_timeout(250)
                    return card

                if self._scroll_feed(page):
                    break

        raise RuntimeError(f"未能重新定位到 Midjourney 卡片：{job_id}")

    def _find_feed_card_by_job_id(self, page: Page, job_id: str) -> Optional[Locator]:
        anchors = page.locator(self.FEED_CARD_LINK_SELECTOR)
        count = anchors.count()
        for index in range(count):
            anchor = anchors.nth(index)
            href = normalize_optional_text(self._safe_get_attribute(anchor, "href"))
            if self._extract_job_id_from_href(href) == job_id:
                return anchor
        return None

    def _open_feed_card(self, page: Page, card_ref: FeedCardRef) -> None:
        card = self._prepare_feed_for_card(page, card_ref)
        click_target = card.locator("img, video").first if self._safe_locator_count(card.locator("img, video")) > 0 else card
        opened = False

        try:
            click_target.click(timeout=5000, force=True)
            opened = True
        except Exception:
            opened = False

        if opened:
            page.wait_for_timeout(600)
            if self._detail_is_visible(page):
                return

        detail_url = normalize_optional_text(card_ref.detail_url)
        if not detail_url:
            raise RuntimeError("未能打开 Midjourney 详情页")

        self._goto_page(page, detail_url)

    def _wait_for_detail(self, page: Page) -> None:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self._detail_is_visible(page):
                return
            page.wait_for_timeout(250)
        raise RuntimeError("Midjourney 详情面板未加载完成")

    def _detail_is_visible(self, page: Page) -> bool:
        return self._is_locator_visible(page.locator(self.DETAIL_PROMPT_SELECTOR).first) or self._is_locator_visible(
            page.locator(self.DETAIL_START_FRAME_SELECTOR).first
        ) or self._is_locator_visible(
            page.locator(self.DETAIL_VIDEO_SELECTOR).first
        )

    def _extract_prompt_parameters(self, page: Page) -> List[str]:
        spans = page.locator(self.DETAIL_PARAMETER_TEXT_SELECTOR)
        count = spans.count()
        parameters: List[str] = []
        seen: set[str] = set()

        for index in range(count):
            text = normalize_optional_text(self._safe_inner_text(spans.nth(index)))
            if not text or not text.startswith("--") or text in seen:
                continue
            seen.add(text)
            parameters.append(text)

        return parameters

    def _compose_prompt_text(self, prompt_body: Optional[str], prompt_parameters: List[str]) -> Optional[str]:
        body = normalize_optional_text(prompt_body)
        parameter_text = " ".join(param for param in prompt_parameters if normalize_optional_text(param)).strip()
        if body and parameter_text:
            return f"{body}\n{parameter_text}"
        return body or normalize_optional_text(parameter_text)

    def _build_scrape_item(
        self,
        card_ref: FeedCardRef,
        *,
        detail_url: Optional[str],
        prompt_body: Optional[str],
        prompt_parameters: List[str],
        source_image_url: str,
        author_name: Optional[str],
    ) -> ScrapeItemPayload:
        final_detail_url = normalize_optional_text(detail_url) or normalize_optional_text(card_ref.detail_url)
        final_source_image_url = normalize_optional_text(source_image_url)
        if not final_source_image_url:
            raise RuntimeError("未能从 Midjourney 提取详情图")

        final_author_name = normalize_optional_text(author_name) or normalize_optional_text(card_ref.author_name)
        prompt_text = self._compose_prompt_text(prompt_body, prompt_parameters)
        external_item_id = normalize_optional_text(card_ref.external_item_id) or self._extract_job_id_from_href(
            final_detail_url
        )
        if not external_item_id:
            external_item_id = sha256_text(f"{self.site_name}|{final_detail_url or final_source_image_url}")

        author_uid = sha256_text(f"{self.site_name}|author|{final_author_name}") if final_author_name else None

        raw_payload: Dict[str, Any] = {
            "feed": {
                "index": card_ref.index,
                "preview_image_url": card_ref.preview_image_url,
                "detail_url": card_ref.detail_url,
                "author_name": card_ref.author_name,
                "external_item_id": card_ref.external_item_id,
                **(card_ref.raw_payload or {}),
            },
            "detail": {
                "detail_url": final_detail_url,
                "external_item_id": external_item_id,
                "source_image_url": final_source_image_url,
                "prompt_body": normalize_optional_text(prompt_body),
                "prompt_parameters": prompt_parameters,
                "prompt_text": prompt_text,
                "author_name": final_author_name,
            },
        }

        return ScrapeItemPayload(
            site_name=self.site_name,
            source_image_url=final_source_image_url,
            detail_url=final_detail_url,
            prompt_text=prompt_text,
            like_count=None,
            external_item_id=external_item_id,
            author=AuthorPayload(
                uid=author_uid,
                name=final_author_name,
                url=None,
                avatar_url=None,
            )
            if final_author_name
            else None,
            raw_payload=raw_payload,
        )

    def _return_to_feed(self, page: Page, listing_url: Optional[str]) -> None:
        self._attempt_close_detail(page)

        if self._detail_is_visible(page) or self._is_detail_url(page.url):
            try:
                page.keyboard.press("Escape")
                page.wait_for_timeout(500)
            except Exception:
                pass

        if self._detail_is_visible(page) or self._is_detail_url(page.url):
            if normalize_optional_text(listing_url):
                try:
                    page.go_back(wait_until="commit", timeout=30000)
                    self._wait_for_domcontentloaded_or_stop(page)
                except Exception:
                    self._goto_page(page, listing_url)

        if self._detail_is_visible(page) and normalize_optional_text(listing_url):
            self._goto_page(page, listing_url)

        self._ensure_feed_ready(page, preferred_url=listing_url)

    def _goto_page(self, page: Page, target_url: str) -> None:
        try:
            page.goto(target_url, wait_until="commit", timeout=self.NAVIGATION_TIMEOUT_MS)
        except PlaywrightTimeoutError as exc:
            raise RuntimeError(
                "Midjourney 页面连接超时；请检查代理是否可连通，或稍后重试："
                f"{target_url}"
            ) from exc
        self._wait_for_domcontentloaded_or_stop(page)

    def _wait_for_domcontentloaded_or_stop(self, page: Page) -> None:
        try:
            page.wait_for_load_state("domcontentloaded", timeout=self.POST_NAVIGATION_TIMEOUT_MS)
        except PlaywrightTimeoutError:
            try:
                page.evaluate("window.stop()")
            except Exception:
                pass

    def _attempt_close_detail(self, page: Page) -> None:
        for selector in self.DETAIL_CLOSE_SELECTORS:
            locator = page.locator(selector).first
            if not self._is_locator_visible(locator):
                continue
            try:
                locator.click(timeout=2000, force=True)
                page.wait_for_timeout(500)
                if not self._detail_is_visible(page):
                    return
            except Exception:
                continue

    def _is_detail_url(self, url: Optional[str]) -> bool:
        parsed = urlparse(normalize_text(url))
        return parsed.path.startswith("/jobs/")

    def _extract_job_id_from_href(self, href: Optional[str]) -> Optional[str]:
        parsed = urlparse(normalize_text(href))
        match = re.search(r"/jobs/([0-9a-fA-F-]+)", parsed.path)
        if not match:
            return None
        return normalize_optional_text(match.group(1))

    def _safe_locator_count(self, locator: Locator) -> int:
        try:
            return locator.count()
        except Exception:
            return 0

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

    def _safe_page_user_agent(self, page: Page) -> Optional[str]:
        try:
            return normalize_optional_text(page.evaluate("navigator.userAgent"))
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

    def _is_locator_visible(self, locator: Locator) -> bool:
        try:
            return locator.is_visible()
        except Exception:
            return False

    def _safe_get_attribute(self, locator: Locator, name: str) -> Optional[str]:
        try:
            return normalize_optional_text(locator.get_attribute(name, timeout=1500))
        except Exception:
            return None

    def _safe_inner_text(self, locator: Locator) -> Optional[str]:
        try:
            return normalize_optional_text(locator.inner_text(timeout=1500))
        except Exception:
            return None

    def _safe_evaluate_locator(self, locator: Locator, expression: str) -> Optional[str]:
        try:
            return normalize_optional_text(locator.evaluate(expression, timeout=1500))
        except Exception:
            return None

    def _safe_evaluate_locator_payload(self, locator: Locator, expression: str) -> Any:
        try:
            return locator.evaluate(expression, timeout=1500)
        except Exception:
            return None

    def _coerce_positive_int(self, value: Any) -> int:
        try:
            integer = int(value)
        except (TypeError, ValueError):
            return 0
        return integer if integer > 0 else 0
