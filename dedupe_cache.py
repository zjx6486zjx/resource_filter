from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Optional

from resource_filter.models import ScrapeItemPayload
from resource_filter.utils import normalize_optional_text, normalize_text, sha256_text


DEFAULT_CACHE_PATH = Path(__file__).resolve().parent / ".cache" / "scrape_item_cache.json"


class ScrapeItemDedupeCache:
    """Persist exact-match scrape items locally to avoid re-importing them."""

    MIDJOURNEY_THUMBNAIL_RE = re.compile(r"_(?P<size>\d+)_N\.webp(?:$|[?#])", re.IGNORECASE)

    def __init__(self, cache_path: Optional[str | Path] = None):
        self.cache_path = Path(cache_path) if cache_path else DEFAULT_CACHE_PATH
        self._entries: Dict[str, Dict[str, Any]] = {}
        self._dirty = False
        self._load()

    def should_skip(self, item: ScrapeItemPayload) -> bool:
        entry_key = self._build_entry_key(item)
        if not entry_key:
            return False

        cached_entry = self._entries.get(entry_key)
        current_fingerprint = self._build_content_fingerprint(item)
        if not cached_entry or not current_fingerprint:
            return False

        cached_fingerprint = normalize_optional_text(cached_entry.get("content_fingerprint"))
        return cached_fingerprint == current_fingerprint

    def remember(self, item: ScrapeItemPayload) -> None:
        entry_key = self._build_entry_key(item)
        content_fingerprint = self._build_content_fingerprint(item)
        if not entry_key or not content_fingerprint:
            return

        next_entry: Dict[str, Any] = {
            "content_fingerprint": content_fingerprint,
        }
        detail_url = normalize_optional_text(item.detail_url)
        if detail_url:
            next_entry["detail_url"] = detail_url
        source_image_url = normalize_optional_text(item.source_image_url)
        if source_image_url:
            next_entry["source_image_url"] = source_image_url

        if self._entries.get(entry_key) == next_entry:
            return

        self._entries[entry_key] = next_entry
        self._dirty = True

    def external_item_ids_for_site(self, site_name: str) -> set[str]:
        normalized_site_name = normalize_text(site_name).lower()
        if not normalized_site_name:
            return set()

        prefix = f"{normalized_site_name}|"
        return {
            key[len(prefix):]
            for key, value in self._entries.items()
            if key.startswith(prefix) and len(key) > len(prefix)
            and self._source_url_is_stable_for_prefilter(normalized_site_name, value)
        }

    def _source_url_is_stable_for_prefilter(self, site_name: str, entry: Dict[str, Any]) -> bool:
        source_image_url = normalize_optional_text(entry.get("source_image_url"))
        if not source_image_url:
            return False
        if site_name == "mj":
            thumbnail_match = self.MIDJOURNEY_THUMBNAIL_RE.search(source_image_url)
            if thumbnail_match and int(thumbnail_match.group("size")) < 640:
                return False
        return True

    def flush(self) -> None:
        if not self._dirty:
            return

        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.cache_path.with_suffix(f"{self.cache_path.suffix}.tmp")
        temp_path.write_text(
            json.dumps({"items": self._entries}, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temp_path.replace(self.cache_path)
        self._dirty = False

    def _build_entry_key(self, item: ScrapeItemPayload) -> str:
        site_name = normalize_text(item.site_name).lower()
        external_item_id = normalize_optional_text(item.external_item_id)
        if not site_name or not external_item_id:
            return ""
        return f"{site_name}|{external_item_id}"

    def _build_content_fingerprint(self, item: ScrapeItemPayload) -> str:
        site_name = normalize_text(item.site_name).lower()
        source_image_url = normalize_optional_text(item.source_image_url)
        if not site_name or not source_image_url:
            return ""

        author = item.author or None
        raw_payload = item.raw_payload if isinstance(item.raw_payload, dict) else {}
        raw_detail = raw_payload.get("detail") if isinstance(raw_payload, dict) else None
        stable_raw_detail = raw_detail if isinstance(raw_detail, dict) else None

        fingerprint_payload = {
            "site_name": site_name,
            "source_image_url": source_image_url,
            "detail_url": normalize_optional_text(item.detail_url),
            "prompt_text": normalize_optional_text(item.prompt_text),
            "like_count": int(item.like_count) if item.like_count is not None else None,
            "author": {
                "uid": normalize_optional_text(author.uid) if author else None,
                "name": normalize_optional_text(author.name) if author else None,
                "url": normalize_optional_text(author.url) if author else None,
                "avatar_url": normalize_optional_text(author.avatar_url) if author else None,
            },
            "raw_detail": stable_raw_detail,
        }
        serialized = json.dumps(fingerprint_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return sha256_text(serialized)

    def _load(self) -> None:
        if not self.cache_path.is_file():
            return

        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except Exception:
            self._entries = {}
            return

        items = payload.get("items")
        if not isinstance(items, dict):
            self._entries = {}
            return

        self._entries = {
            str(key): value
            for key, value in items.items()
            if isinstance(value, dict)
        }
