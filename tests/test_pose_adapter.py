from __future__ import annotations

import unittest

from resource_filter.adapters.pose import PoseAdapter
from resource_filter.models import FeedCardRef


class PoseAdapterTests(unittest.TestCase):
    def test_normalize_inspiration_entry_url_adds_default_page_and_page_size(self) -> None:
        adapter = PoseAdapter()

        result = adapter._normalize_inspiration_entry_url("https://www.photopose.art/zh/poses")

        self.assertEqual(result, "https://www.photopose.art/zh/poses?page=1&pageSize=96")

    def test_build_page_url_updates_page_keeps_page_size(self) -> None:
        adapter = PoseAdapter()

        result = adapter._build_page_url(
            "https://www.photopose.art/zh/poses?page=1&pageSize=96",
            page_number=3,
            page_size=96,
        )

        self.assertEqual(result, "https://www.photopose.art/zh/poses?page=3&pageSize=96")

    def test_extract_next_data_from_html(self) -> None:
        adapter = PoseAdapter()

        result = adapter._extract_next_data_from_html(
            '<html><script id="__NEXT_DATA__" type="application/json">'
            '{"props":{"pageProps":{"poses":[{"id":"demo"}]}}}'
            "</script></html>"
        )

        self.assertEqual(result["props"]["pageProps"]["poses"][0]["id"], "demo")

    def test_build_scrape_item_uses_localized_fields_from_pose_detail(self) -> None:
        adapter = PoseAdapter()
        card_ref = FeedCardRef(
            index=0,
            preview_image_url="https://example.com/thumb.jpg",
            detail_url="https://www.photopose.art/zh/poses/demo-id",
            title="fallback title",
            external_item_id="demo-id",
        )
        pose = {
            "id": "demo-id",
            "title": "Tai Chi Pose",
            "title_i18n": {"zh": "太极姿势"},
            "description": "Graceful movement",
            "description_i18n": {"zh": "强调平衡与宁静的动作。"},
            "image_url": "https://example.com/full.png",
            "thumbnail_url": "https://example.com/thumb.jpg",
            "difficulty": "easy",
            "created_at": "2025-05-20T19:26:13.456713+00:00",
            "updated_at": "2025-05-21T07:50:08.873294+00:00",
            "categories": [
                {
                    "id": "cat-1",
                    "name": "Wellness Photography",
                    "name_i18n": {"zh": "健康摄影"},
                    "description_i18n": {"zh": "健康类摄影"},
                }
            ],
            "tags": [
                {
                    "id": "tag-1",
                    "name": "Tai Chi",
                    "name_i18n": {"zh": "太极"},
                }
            ],
            "user": {
                "id": "user-1",
                "full_name": "aa",
                "avatar_url": "https://example.com/avatar.png",
            },
        }

        result = adapter._build_scrape_item(
            card_ref,
            pose,
            locale="zh",
            detail_url=card_ref.detail_url,
        )

        self.assertEqual(result.site_name, "pose")
        self.assertEqual(result.external_item_id, "demo-id")
        self.assertEqual(result.source_image_url, "https://example.com/full.png")
        self.assertEqual(result.prompt_text, "太极姿势\n强调平衡与宁静的动作。")
        self.assertEqual(result.author.uid, "user-1")
        self.assertEqual(result.author.name, "aa")
        self.assertEqual(result.raw_payload["detail"]["categories"][0]["name"], "健康摄影")
        self.assertEqual(result.raw_payload["detail"]["tags"][0]["name"], "太极")


if __name__ == "__main__":
    unittest.main()
