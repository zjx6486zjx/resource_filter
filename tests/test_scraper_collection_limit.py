from __future__ import annotations

import unittest

from resource_filter.models import ScrapeItemPayload
from resource_filter.scraper import CrawlSummary, PlaywrightSiteCrawler


class ScraperCollectionLimitTests(unittest.TestCase):
    def test_next_collection_limit_grows_one_candidate_at_a_time(self) -> None:
        crawler = PlaywrightSiteCrawler(
            adapter=object(),
            api_client=object(),
            max_items=20,
        )

        self.assertEqual(crawler._next_collection_limit(set(), CrawlSummary()), 1)
        self.assertEqual(crawler._next_collection_limit({"a"}, CrawlSummary(imported=1)), 2)
        self.assertEqual(crawler._next_collection_limit({"a", "b"}, CrawlSummary(imported=1, skipped=1)), 3)

    def test_next_collection_limit_stops_after_target_imports(self) -> None:
        crawler = PlaywrightSiteCrawler(
            adapter=object(),
            api_client=object(),
            max_items=2,
        )

        self.assertEqual(crawler._next_collection_limit({"a", "b"}, CrawlSummary(imported=2)), 2)

    def test_validate_source_image_promotes_thumbnail_before_import(self) -> None:
        crawler = PlaywrightSiteCrawler(adapter=object(), api_client=object(), max_items=1)
        original_url = "https://cdn.midjourney.com/demo/0_0.jpeg"
        thumbnail_url = "https://cdn.midjourney.com/demo/0_0_128_N.webp"
        item = ScrapeItemPayload(
            site_name="mj",
            source_image_url=thumbnail_url,
            raw_payload={"detail": {"source_image_url": thumbnail_url}},
        )

        class FakeResponse:
            ok = True
            status = 200
            headers = {"content-type": "image/png"}

            def body(self) -> bytes:
                return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + (640).to_bytes(4, "big") + (480).to_bytes(4, "big") + b"\x08\x02\x00\x00\x00"

        class FakeRequest:
            def __init__(self) -> None:
                self.urls: list[str] = []
                self.headers: list[dict[str, str]] = []

            def get(self, url: str, timeout: int = 15000, headers: dict[str, str] | None = None) -> FakeResponse:
                self.urls.append(url)
                self.headers.append(headers or {})
                return FakeResponse()

        class FakeContext:
            def __init__(self) -> None:
                self.request = FakeRequest()

        class FakePage:
            def __init__(self) -> None:
                self.context = FakeContext()

            def evaluate(self, script: str, *args) -> str:
                return "FakeChrome/135"

        page = FakePage()

        result = crawler._validate_source_image_before_import(page, item)

        self.assertTrue(result.ok)
        self.assertEqual(item.source_image_url, original_url)
        self.assertEqual(item.raw_payload["detail"]["source_image_url"], original_url)
        self.assertEqual(page.context.request.urls[0], original_url)
        self.assertEqual(page.context.request.headers[0]["Referer"], "https://www.midjourney.com/")

    def test_validate_source_image_allows_loaded_midjourney_image_after_http_403(self) -> None:
        crawler = PlaywrightSiteCrawler(adapter=object(), api_client=object(), max_items=1)
        image_url = "https://cdn.midjourney.com/demo-job/0_0.jpeg"
        item = ScrapeItemPayload(site_name="mj", source_image_url=image_url, detail_url="https://www.midjourney.com/jobs/demo-job")

        class FakeResponse:
            ok = False
            status = 403
            headers = {}

        class FakeRequest:
            def get(self, url: str, timeout: int = 15000, headers: dict[str, str] | None = None) -> FakeResponse:
                return FakeResponse()

        class FakeContext:
            def __init__(self) -> None:
                self.request = FakeRequest()

        class FakePage:
            def __init__(self) -> None:
                self.context = FakeContext()

            def evaluate(self, script: str, *args):
                if script == "navigator.userAgent":
                    return "FakeChrome/135"
                return {"width": 2048, "height": 2048}

        result = crawler._validate_source_image_before_import(FakePage(), item)

        self.assertTrue(result.ok)
        self.assertEqual((result.width, result.height), (2048, 2048))

    def test_validate_source_image_trusts_midjourney_original_url_after_http_403(self) -> None:
        crawler = PlaywrightSiteCrawler(adapter=object(), api_client=object(), max_items=1)
        image_url = "https://cdn.midjourney.com/9b6dbcb4-a139-4f50-94df-71ae95f6cd3f/0_0.jpeg"
        item = ScrapeItemPayload(site_name="mj", source_image_url=image_url)

        class FakeResponse:
            ok = False
            status = 403
            headers = {}

        class FakeRequest:
            def get(self, url: str, timeout: int = 15000, headers: dict[str, str] | None = None) -> FakeResponse:
                return FakeResponse()

        class FakeContext:
            def __init__(self) -> None:
                self.request = FakeRequest()

        class FakePage:
            def __init__(self) -> None:
                self.context = FakeContext()

            def evaluate(self, script: str, *args):
                if script == "navigator.userAgent":
                    return "FakeChrome/135"
                return None

        result = crawler._validate_source_image_before_import(FakePage(), item)

        self.assertTrue(result.ok)

    def test_validate_source_image_uses_midjourney_detail_metadata_before_http(self) -> None:
        crawler = PlaywrightSiteCrawler(adapter=object(), api_client=object(), max_items=1)
        image_url = "https://cdn.midjourney.com/9b6dbcb4-a139-4f50-94df-71ae95f6cd3f/0_0.jpeg"
        item = ScrapeItemPayload(
            site_name="mj",
            source_image_url=image_url,
            raw_payload={
                "detail": {
                    "source_image_url": image_url,
                    "source_image_width": 2048,
                    "source_image_height": 2048,
                }
            },
        )

        class FakeRequest:
            def get(self, url: str, timeout: int = 15000, headers: dict[str, str] | None = None):
                raise AssertionError("metadata should avoid HTTP validation")

        class FakeContext:
            def __init__(self) -> None:
                self.request = FakeRequest()

        class FakePage:
            def __init__(self) -> None:
                self.context = FakeContext()

        result = crawler._validate_source_image_before_import(FakePage(), item)

        self.assertTrue(result.ok)
        self.assertEqual((result.width, result.height), (2048, 2048))


if __name__ == "__main__":
    unittest.main()
