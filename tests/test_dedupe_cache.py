import tempfile
import unittest

from resource_filter.dedupe_cache import ScrapeItemDedupeCache
from resource_filter.models import AuthorPayload, ScrapeItemPayload


def build_item(
    *,
    prompt_text="原始 prompt",
    like_count=12,
    author_name="作者A",
    detail_url="https://example.com/item/1",
    source_image_url="https://img.example.com/1.jpg",
    external_item_id="item-1",
    raw_detail=None,
):
    return ScrapeItemPayload(
        site_name="xhs",
        source_image_url=source_image_url,
        detail_url=detail_url,
        prompt_text=prompt_text,
        like_count=like_count,
        external_item_id=external_item_id,
        author=AuthorPayload(
            uid="author-1",
            name=author_name,
            url="https://example.com/author/1",
            avatar_url="https://img.example.com/avatar.jpg",
        ),
        raw_payload={
            "feed": {
                "index": 3,
                "tab_name": "综合",
            },
            "detail": raw_detail
            or {
                "detail_url": detail_url,
                "source_image_url": source_image_url,
                "prompt_text": prompt_text,
                "image_urls": [source_image_url],
                "image_count": 1,
                "like_count": like_count,
            },
        },
    )


class ScrapeItemDedupeCacheTest(unittest.TestCase):
    def make_cache(self, name: str) -> ScrapeItemDedupeCache:
        temp_dir = tempfile.TemporaryDirectory(prefix="resource_filter_dedupe_test_")
        self.addCleanup(temp_dir.cleanup)
        return ScrapeItemDedupeCache(cache_path=f"{temp_dir.name}/{name}.json")

    def test_skip_when_stable_snapshot_is_identical(self):
        cache = self.make_cache("identical")
        item = build_item()

        self.assertFalse(cache.should_skip(item))
        cache.remember(item)
        self.assertTrue(cache.should_skip(build_item()))

    def test_do_not_skip_when_prompt_changes(self):
        cache = self.make_cache("prompt")
        cache.remember(build_item(prompt_text="旧 prompt"))

        self.assertFalse(cache.should_skip(build_item(prompt_text="新 prompt")))

    def test_do_not_skip_when_detail_payload_changes(self):
        cache = self.make_cache("detail")
        cache.remember(build_item(raw_detail={"image_urls": ["https://img.example.com/1.jpg"], "image_count": 1}))

        self.assertFalse(
            cache.should_skip(
                build_item(raw_detail={"image_urls": ["https://img.example.com/1.jpg", "https://img.example.com/2.jpg"], "image_count": 2})
            )
        )

    def test_ignore_feed_only_noise(self):
        cache = self.make_cache("feed-noise")
        cache.remember(build_item())
        noisy_feed_item = build_item()
        noisy_feed_item.raw_payload["feed"] = {"index": 99, "tab_name": "最新"}

        self.assertTrue(cache.should_skip(noisy_feed_item))

    def test_external_item_ids_for_site(self):
        cache = self.make_cache("external-ids")
        cache.remember(build_item(external_item_id="xhs-1"))
        mj_item = build_item(external_item_id="mj-1")
        mj_item.site_name = "mj"
        cache.remember(mj_item)

        self.assertEqual(cache.external_item_ids_for_site("mj"), {"mj-1"})
        self.assertEqual(cache.external_item_ids_for_site("xhs"), {"xhs-1"})

    def test_external_item_ids_ignore_legacy_entries_without_source_url(self):
        cache = self.make_cache("legacy-external-ids")
        cache._entries = {
            "mj|legacy-1": {"content_fingerprint": "old"},
            "mj|fresh-1": {"content_fingerprint": "new", "source_image_url": "https://cdn.midjourney.com/demo/0_0.png"},
        }

        self.assertEqual(cache.external_item_ids_for_site("mj"), {"fresh-1"})

    def test_external_item_ids_ignore_midjourney_thumbnail_entries(self):
        cache = self.make_cache("mj-thumbnail-external-ids")
        cache._entries = {
            "mj|thumbnail-1": {
                "content_fingerprint": "old",
                "source_image_url": "https://cdn.midjourney.com/demo/0_0_128_N.webp",
            },
            "mj|frame-1": {
                "content_fingerprint": "new",
                "source_image_url": "data:image/png;base64,abc",
            },
        }

        self.assertEqual(cache.external_item_ids_for_site("mj"), {"frame-1"})

    def test_external_item_ids_keep_midjourney_640_poster_entries(self):
        cache = self.make_cache("mj-poster-external-ids")
        cache._entries = {
            "mj|poster-1": {
                "content_fingerprint": "new",
                "source_image_url": "https://cdn.midjourney.com/video/demo/0_640_N.webp",
            },
        }

        self.assertEqual(cache.external_item_ids_for_site("mj"), {"poster-1"})


if __name__ == "__main__":
    unittest.main()
