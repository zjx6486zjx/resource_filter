from __future__ import annotations

import unittest

from resource_filter.adapters.baidu import BaiduAdapter
from resource_filter.models import FeedCardRef
from resource_filter.utils import sha256_text


class BaiduAdapterTests(unittest.TestCase):
    def test_normalize_inspiration_entry_url_uses_default_search_page(self) -> None:
        adapter = BaiduAdapter()

        result = adapter._normalize_inspiration_entry_url("")

        self.assertEqual(result, "https://image.baidu.com/")

    def test_normalize_search_result_url_updates_keyword(self) -> None:
        adapter = BaiduAdapter()

        result = adapter._normalize_inspiration_entry_url(
            "https://image.baidu.com/search/index?tn=baiduimage&word=old",
            keyword="赵露思",
        )

        self.assertIn("tn=baiduimage", result)
        self.assertIn("word=%E8%B5%B5%E9%9C%B2%E6%80%9D", result)

    def test_normalize_image_url_promotes_protocol_relative_and_https(self) -> None:
        adapter = BaiduAdapter()

        self.assertEqual(
            adapter._normalize_image_url("//img1.baidu.com/it/u=1&fm=253"),
            "https://img1.baidu.com/it/u=1&fm=253",
        )
        self.assertEqual(
            adapter._normalize_image_url("http://img1.baidu.com/it/u=1&fm=253"),
            "https://img1.baidu.com/it/u=1&fm=253",
        )

    def test_extract_external_item_id_prefers_stable_baidu_fields(self) -> None:
        adapter = BaiduAdapter()

        result = adapter._extract_external_item_id(
            ext={"cs": "895422020,4047521542", "objurl": "https://example.com/demo.jpg"},
            detail_url="https://image.baidu.com/search/detail?demo=1",
            image_url="https://img1.baidu.com/it/u=1&fm=253",
        )

        self.assertEqual(result, sha256_text("baidu|cs|895422020,4047521542"))

    def test_build_scrape_item_does_not_save_prompt(self) -> None:
        adapter = BaiduAdapter()
        card_ref = FeedCardRef(
            index=2,
            preview_image_url="https://img1.baidu.com/it/u=1&fm=253",
            detail_url="https://image.baidu.com/search/detail?demo=1",
            title="百度图片 - 更多高清美图",
            author_url="http://www.douyin.com/note/7380665804875943206",
            external_item_id="demo-id",
            raw_payload={
                "show_ext": {
                    "url": "https://img1.baidu.com/it/u=1&fm=253",
                    "objurl": "https://example.com/original.jpg",
                    "fromurl": "http://www.douyin.com/note/7380665804875943206",
                    "title": "百度图片 - 更多高清美图",
                }
            },
        )

        result = adapter._build_scrape_item(card_ref)

        self.assertEqual(result.site_name, "baidu")
        self.assertEqual(result.external_item_id, "demo-id")
        self.assertEqual(result.source_image_url, "https://img1.baidu.com/it/u=1&fm=253")
        self.assertIsNone(result.prompt_text)
        self.assertIsNone(result.author)
        self.assertTrue(result.raw_payload["thumbnail_only"])
        self.assertEqual(result.raw_payload["feed"]["source_page_url"], "http://www.douyin.com/note/7380665804875943206")
        self.assertEqual(result.raw_payload["feed"]["original_image_url"], "https://example.com/original.jpg")


if __name__ == "__main__":
    unittest.main()
