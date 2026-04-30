from __future__ import annotations

import unittest

from resource_filter.adapters.taobao import TaobaoAdapter
from resource_filter.models import FeedCardRef


class TaobaoAdapterTests(unittest.TestCase):
    def test_normalize_inspiration_entry_url_uses_default_search_page(self) -> None:
        adapter = TaobaoAdapter()

        result = adapter._normalize_inspiration_entry_url("")

        self.assertEqual(result, "https://uland.taobao.com/sem/tbsearch")

    def test_normalize_image_url_promotes_alicdn_to_https(self) -> None:
        adapter = TaobaoAdapter()

        self.assertEqual(
            adapter._normalize_image_url("//img.alicdn.com/img/O1CN-demo.jpg"),
            "https://img.alicdn.com/img/O1CN-demo.jpg",
        )
        self.assertEqual(
            adapter._normalize_image_url("http://img.alicdn.com/img/O1CN-demo.jpg"),
            "https://img.alicdn.com/img/O1CN-demo.jpg",
        )

    def test_normalize_image_url_strips_alicdn_avif_transform(self) -> None:
        adapter = TaobaoAdapter()

        self.assertEqual(
            adapter._normalize_image_url(
                "https://g-search3.alicdn.com/img/bao/uploaded/i4/demo.jpg_580x580q90.jpg_.avif"
            ),
            "https://g-search3.alicdn.com/img/bao/uploaded/i4/demo.jpg",
        )
        self.assertIsNone(adapter._normalize_image_url("https://g-search3.alicdn.com/img/bao/uploaded/i4/demo.avif"))

    def test_normalize_image_url_skips_taobao_badges_and_atmosphere_images(self) -> None:
        adapter = TaobaoAdapter()

        self.assertIsNone(
            adapter._normalize_image_url(
                "https://img.alicdn.com/imgextra/i2/O1CN-demo_!!6000000002329-2-tps-64-32.png"
            )
        )
        self.assertIsNone(
            adapter._normalize_image_url(
                "https://img.alicdn.com/i2/O1CN-demo_!!4611686018427384654-2-atmosphere_center_image_storag-merlin-224-48.png"
            )
        )

    def test_extract_external_item_id_prefers_card_dom_id(self) -> None:
        adapter = TaobaoAdapter()

        result = adapter._extract_external_item_id(
            dom_id="item_id_903032644568",
            detail_url="https://click.simba.taobao.com/cc_im?skuId=5927797615864",
            image_url="https://img.alicdn.com/img/O1CN-demo.jpg",
        )

        self.assertEqual(result, "903032644568")

    def test_extract_external_item_id_reads_encoded_simba_url(self) -> None:
        adapter = TaobaoAdapter()
        detail_url = (
            "https://click.simba.taobao.com/cc_im?"
            "p=%B9%C5%B7%E7%20%B3%C9%C8%CB%20%BA%BA%B7%FE"
            "&a=xxc%3Dad_ztc%26skuId%3D5903863338090%26priceTId%3Ddemo"
        )

        result = adapter._extract_external_item_id(
            dom_id="",
            detail_url=detail_url,
            image_url="https://img.alicdn.com/img/O1CN-demo.jpg",
        )

        self.assertEqual(result, "5903863338090")

    def test_normalize_detail_url_shortens_ad_tracking_url(self) -> None:
        adapter = TaobaoAdapter()
        detail_url = (
            "https://click.simba.taobao.com/cc_im?"
            "p=%B9%C5%B7%E7%20%B3%C9%C8%CB%20%BA%BA%B7%FE"
            "&a=xxc%3Dad_ztc%26skuId%3D5903863338090%26priceTId%3Ddemo"
        )

        result = adapter._normalize_detail_url(detail_url, external_item_id="5903863338090")

        self.assertEqual(result, "https://item.taobao.com/item.htm?id=5903863338090")

    def test_build_scrape_item_uses_thumbnail_without_detail_fetch(self) -> None:
        adapter = TaobaoAdapter()
        card_ref = FeedCardRef(
            index=2,
            preview_image_url="https://img.alicdn.com/img/O1CN-demo.jpg",
            detail_url="https://item.taobao.com/item.htm?id=903032644568",
            title="成人汉服古装中国风",
            author_name="沿调旗舰店",
            like_count=2000,
            external_item_id="903032644568",
        )

        result = adapter._build_scrape_item(card_ref)

        self.assertEqual(result.site_name, "taobao")
        self.assertEqual(result.external_item_id, "903032644568")
        self.assertEqual(result.source_image_url, "https://img.alicdn.com/img/O1CN-demo.jpg")
        self.assertIsNone(result.detail_url)
        self.assertEqual(result.prompt_text, "成人汉服古装中国风")
        self.assertEqual(result.author.name, "沿调旗舰店")
        self.assertTrue(result.raw_payload["thumbnail_only"])
        self.assertEqual(result.raw_payload["feed"]["product_detail_url"], "https://item.taobao.com/item.htm?id=903032644568")
        self.assertIsNone(result.raw_payload["detail"])


if __name__ == "__main__":
    unittest.main()
