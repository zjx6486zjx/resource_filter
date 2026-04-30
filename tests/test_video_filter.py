from __future__ import annotations

import unittest

from resource_filter.models import ScrapeItemPayload
from resource_filter.scraper import PlaywrightSiteCrawler


class VideoFilterTests(unittest.TestCase):
    def test_video_source_url_is_filtered(self) -> None:
        crawler = PlaywrightSiteCrawler(adapter=None, api_client=None)
        item = ScrapeItemPayload(site_name="xhs", source_image_url="https://example.com/a.mp4?token=1")

        self.assertTrue(crawler._is_video_item(item))

    def test_video_media_type_in_raw_payload_is_filtered(self) -> None:
        crawler = PlaywrightSiteCrawler(adapter=None, api_client=None)
        item = ScrapeItemPayload(
            site_name="xhs",
            source_image_url="https://example.com/a",
            raw_payload={"detail": {"media_type": "video"}},
        )

        self.assertTrue(crawler._is_video_item(item))

    def test_data_image_source_with_video_metadata_is_not_filtered(self) -> None:
        crawler = PlaywrightSiteCrawler(adapter=None, api_client=None)
        item = ScrapeItemPayload(
            site_name="mj",
            source_image_url="data:image/png;base64,abc",
            raw_payload={"detail": {"media_type": "video", "video_url": "https://cdn.midjourney.com/video/demo/0.mp4"}},
        )

        self.assertFalse(crawler._is_video_item(item))

    def test_midjourney_video_path_image_thumbnail_is_not_filtered_by_url_path(self) -> None:
        crawler = PlaywrightSiteCrawler(adapter=None, api_client=None)
        item = ScrapeItemPayload(
            site_name="mj",
            source_image_url="https://cdn.midjourney.com/video/demo/0_640_N.webp",
        )

        self.assertFalse(crawler._is_video_item(item))


if __name__ == "__main__":
    unittest.main()
