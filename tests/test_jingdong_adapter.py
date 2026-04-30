from __future__ import annotations

import html
import json
import unittest

from resource_filter.adapters.jingdong import JingdongAdapter
from resource_filter.models import FeedCardRef


class JingdongAdapterTests(unittest.TestCase):
    def test_normalize_inspiration_entry_url_uses_default_search_page(self) -> None:
        adapter = JingdongAdapter()

        result = adapter._normalize_inspiration_entry_url("")

        self.assertEqual(result, "https://re.jd.com/search")

    def test_parse_data_item_decodes_html_escaped_json(self) -> None:
        adapter = JingdongAdapter()
        raw_data_item = html.escape(
            json.dumps(
                {
                    "id": "10097166151949",
                    "spuId": "10097166151941",
                    "title": "奥蒙威女童汉服裙",
                    "imageUrl": "jfs/t1/137113/9/demo.jpg",
                    "landUrl": "https://item.jd.com/10097166151949.html",
                    "shopName": "奥蒙威童装旗舰店",
                }
            )
        )

        result = adapter._parse_data_item(raw_data_item)

        self.assertEqual(result["spuId"], "10097166151941")
        self.assertEqual(result["title"], "奥蒙威女童汉服裙")

    def test_normalize_image_url_builds_360buyimg_url_and_strips_transform(self) -> None:
        adapter = JingdongAdapter()

        self.assertEqual(
            adapter._normalize_image_url("jfs/t1/137113/9/demo.jpg"),
            "https://m.360buyimg.com/mobilecms/s500x500_jfs/t1/137113/9/demo.jpg!q70.dpg",
        )
        self.assertEqual(
            adapter._normalize_image_url("//m.360buyimg.com/mobilecms/s500x500_jfs/t1/demo.jpg!q70.dpg"),
            "https://m.360buyimg.com/mobilecms/s500x500_jfs/t1/demo.jpg!q70.dpg",
        )
        self.assertIsNone(
            adapter._normalize_image_url("https://storage.360buyimg.com/component-libray/images/lazyLoadding.png")
        )

    def test_extract_external_item_id_prefers_spu_id(self) -> None:
        adapter = JingdongAdapter()

        result = adapter._extract_external_item_id(
            data_item={"id": "10097166151949", "spuId": "10097166151941"},
            detail_url="https://item.jd.com/10097166151949.html",
            image_url="https://m.360buyimg.com/mobilecms/s500x500_jfs/t1/demo.jpg",
        )

        self.assertEqual(result, "10097166151941")

    def test_build_scrape_item_uses_data_item_metadata(self) -> None:
        adapter = JingdongAdapter()
        card_ref = FeedCardRef(
            index=2,
            preview_image_url="https://m.360buyimg.com/mobilecms/s500x500_jfs/t1/demo.jpg",
            detail_url="https://item.jd.com/10097166151949.html",
            title="奥蒙威女童汉服裙",
            author_name="奥蒙威童装旗舰店",
            like_count=500,
            external_item_id="10097166151941",
            raw_payload={
                "data_item": {
                    "id": "10097166151949",
                    "spuId": "10097166151941",
                    "shopId": "12993259",
                    "price": "79.00",
                }
            },
        )

        result = adapter._build_scrape_item(card_ref)

        self.assertEqual(result.site_name, "jingdong")
        self.assertEqual(result.external_item_id, "10097166151941")
        self.assertIsNone(result.detail_url)
        self.assertEqual(result.prompt_text, "奥蒙威女童汉服裙")
        self.assertEqual(result.author.name, "奥蒙威童装旗舰店")
        self.assertEqual(result.author.uid, "12993259")
        self.assertTrue(result.raw_payload["thumbnail_only"])
        self.assertEqual(result.raw_payload["feed"]["product_detail_url"], "https://item.jd.com/10097166151949.html")
        self.assertEqual(result.raw_payload["feed"]["spu_id"], "10097166151941")


if __name__ == "__main__":
    unittest.main()
