from __future__ import annotations

import unittest

from resource_filter.adapters.mj import MjAdapter, PlaywrightTimeoutError
from resource_filter.models import FeedCardRef


class MjAdapterTests(unittest.TestCase):
    def test_goto_page_uses_commit_and_stops_after_domcontentloaded_timeout(self) -> None:
        adapter = MjAdapter()

        class FakePage:
            def __init__(self) -> None:
                self.calls: list[tuple[str, object]] = []

            def goto(self, url: str, *, wait_until: str, timeout: int) -> None:
                self.calls.append(("goto", (url, wait_until, timeout)))

            def wait_for_load_state(self, state: str, *, timeout: int) -> None:
                self.calls.append(("wait_for_load_state", (state, timeout)))
                raise PlaywrightTimeoutError("slow page")

            def evaluate(self, script: str) -> None:
                self.calls.append(("evaluate", script))

        page = FakePage()

        adapter._goto_page(page, "https://www.midjourney.com/explore?tab=video_top")

        self.assertEqual(
            page.calls,
            [
                ("goto", ("https://www.midjourney.com/explore?tab=video_top", "commit", 90000)),
                ("wait_for_load_state", ("domcontentloaded", 15000)),
                ("evaluate", "window.stop()"),
            ],
        )

    def test_collect_visible_cards_skips_cached_jobs_without_losing_progress(self) -> None:
        adapter = MjAdapter()

        class FakeLocatorCollection:
            def __init__(self, items: list[object]) -> None:
                self.items = items

            @property
            def first(self) -> object:
                return self.items[0] if self.items else FakeEmptyLocator()

            def count(self) -> int:
                return len(self.items)

            def nth(self, index: int) -> object:
                return self.items[index]

        class FakeEmptyLocator:
            @property
            def first(self) -> "FakeEmptyLocator":
                return self

            def count(self) -> int:
                return 0

            def get_attribute(self, _name: str, timeout: int = 1500) -> None:
                return None

            def inner_text(self, timeout: int = 1500) -> str:
                return ""

        class FakeImageLocator:
            @property
            def first(self) -> "FakeImageLocator":
                return self

            def get_attribute(self, name: str, timeout: int = 1500) -> str | None:
                return "https://cdn.midjourney.com/demo.webp" if name == "src" else None

        class FakeCardLocator:
            def __init__(self, author_name: str) -> None:
                self.author_name = author_name

            def inner_text(self, timeout: int = 1500) -> str:
                return self.author_name

        class FakeAnchor:
            def __init__(self, job_id: str, author_name: str) -> None:
                self.job_id = job_id
                self.author_name = author_name

            def get_attribute(self, name: str, timeout: int = 1500) -> str | None:
                if name == "href":
                    return f"/jobs/{self.job_id}?index=0"
                return None

            def locator(self, selector: str) -> object:
                if selector == adapter.FEED_CARD_IMAGE_SELECTOR:
                    return FakeImageLocator()
                if selector == "xpath=..":
                    return FakeCardLocator(self.author_name)
                return FakeLocatorCollection([])

        class FakePage:
            def locator(self, _selector: str) -> FakeLocatorCollection:
                return FakeLocatorCollection(
                    [
                        FakeAnchor("11111111-1111-4111-8111-111111111111", "cached-author"),
                        FakeAnchor("22222222-2222-4222-8222-222222222222", "new-author"),
                    ]
                )

        references = []

        discovered = adapter._collect_visible_cards(
            FakePage(),
            references,
            seen_job_ids=set(),
            max_items=1,
            skipped_cached_job_ids={"11111111-1111-4111-8111-111111111111"},
        )

        self.assertEqual(discovered, 2)
        self.assertEqual(len(references), 1)
        self.assertEqual(references[0].external_item_id, "22222222-2222-4222-8222-222222222222")

    def test_normalize_inspiration_entry_url_adds_default_tab(self) -> None:
        adapter = MjAdapter()

        result = adapter._normalize_inspiration_entry_url("https://www.midjourney.com/explore")

        self.assertEqual(result, "https://www.midjourney.com/explore?tab=top")

    def test_extract_job_id_from_href(self) -> None:
        adapter = MjAdapter()

        result = adapter._extract_job_id_from_href("/jobs/812e0c98-6fc1-4055-a51f-78f7588b6104?index=0")

        self.assertEqual(result, "812e0c98-6fc1-4055-a51f-78f7588b6104")

    def test_promote_midjourney_thumbnail_candidates_prefers_original_jpeg(self) -> None:
        adapter = MjAdapter()

        result = adapter._promoted_midjourney_image_candidates(
            "https://cdn.midjourney.com/e0e76c2c-50a5-4d60-a1ba-ad39f34cc1b6/0_3_128_N.webp"
        )

        self.assertEqual(
            result[0],
            "https://cdn.midjourney.com/e0e76c2c-50a5-4d60-a1ba-ad39f34cc1b6/0_3.jpeg",
        )

    def test_select_largest_srcset_url(self) -> None:
        adapter = MjAdapter()

        result = adapter._select_largest_srcset_url(
            "https://cdn.midjourney.com/demo/0_0_128_N.webp 128w, "
            "https://cdn.midjourney.com/demo/0_0_640_N.webp 640w"
        )

        self.assertEqual(result, "https://cdn.midjourney.com/demo/0_0_640_N.webp")

    def test_resolve_best_midjourney_image_url_uses_available_original_candidate(self) -> None:
        adapter = MjAdapter()

        class FakeResponse:
            ok = True
            headers = {"content-type": "image/png"}

        class FakeRequest:
            def __init__(self) -> None:
                self.urls: list[str] = []
                self.headers: list[dict[str, str]] = []

            def head(self, url: str, timeout: int = 10000, headers: dict[str, str] | None = None) -> FakeResponse:
                self.urls.append(url)
                self.headers.append(headers or {})
                return FakeResponse()

        class FakeContext:
            def __init__(self) -> None:
                self.request = FakeRequest()

        class FakePage:
            def __init__(self) -> None:
                self.context = FakeContext()

        page = FakePage()

        result = adapter._resolve_best_midjourney_image_url(
            page,
            "https://cdn.midjourney.com/e0e76c2c-50a5-4d60-a1ba-ad39f34cc1b6/0_3_128_N.webp",
        )

        self.assertEqual(
            result,
            "https://cdn.midjourney.com/e0e76c2c-50a5-4d60-a1ba-ad39f34cc1b6/0_3.jpeg",
        )
        self.assertEqual(page.context.request.urls, [result])
        self.assertEqual(page.context.request.headers[0]["Referer"], "https://www.midjourney.com/")

    def test_extract_source_image_url_falls_back_to_job_id_original(self) -> None:
        adapter = MjAdapter()

        class FakeEmptyLocator:
            @property
            def first(self) -> "FakeEmptyLocator":
                return self

            def count(self) -> int:
                return 0

            def get_attribute(self, name: str, timeout: int = 1500) -> None:
                return None

            def evaluate(self, expression: str, timeout: int = 1500) -> None:
                return None

        class FakePage:
            def locator(self, selector: str) -> FakeEmptyLocator:
                return FakeEmptyLocator()

        result, media_payload = adapter._extract_source_image_url(
            FakePage(),
            None,
            expected_job_id="6bab0135-7b4f-4b3d-b330-9d4068881872",
        )

        self.assertEqual(
            result,
            "https://cdn.midjourney.com/6bab0135-7b4f-4b3d-b330-9d4068881872/0_0.jpeg",
        )
        self.assertEqual(media_payload, {})

    def test_build_scrape_item_combines_prompt_and_parameters(self) -> None:
        adapter = MjAdapter()
        card_ref = FeedCardRef(
            index=3,
            preview_image_url="https://cdn.midjourney.com/video/demo/0_640_N.webp",
            detail_url="https://www.midjourney.com/jobs/812e0c98-6fc1-4055-a51f-78f7588b6104?index=0",
            author_name="u1833751626",
            external_item_id="812e0c98-6fc1-4055-a51f-78f7588b6104",
        )

        result = adapter._build_scrape_item(
            card_ref,
            detail_url=card_ref.detail_url,
            prompt_body="1girl, semi-realistic oil painting",
            prompt_parameters=["--duration 5.2s", "--ar 2:3", "--motion low"],
            source_image_url="https://cdn.midjourney.com/e0e76c2c-50a5-4d60-a1ba-ad39f34cc1b6/0_3_128_N.webp",
            author_name="u1833751626",
        )

        self.assertEqual(result.site_name, "mj")
        self.assertEqual(result.external_item_id, "812e0c98-6fc1-4055-a51f-78f7588b6104")
        self.assertEqual(
            result.prompt_text,
            "1girl, semi-realistic oil painting\n--duration 5.2s --ar 2:3 --motion low",
        )
        self.assertEqual(
            result.source_image_url,
            "https://cdn.midjourney.com/e0e76c2c-50a5-4d60-a1ba-ad39f34cc1b6/0_3_128_N.webp",
        )
        self.assertEqual(result.author.name, "u1833751626")
        self.assertEqual(result.raw_payload["detail"]["prompt_parameters"], ["--duration 5.2s", "--ar 2:3", "--motion low"])

    def test_select_video_poster_source_url_uses_public_image_url(self) -> None:
        adapter = MjAdapter()

        poster_url = adapter._select_video_poster_source_url(
            object(),
            {"poster_url": "https://cdn.midjourney.com/video/demo/0_640_N.webp"},
        )

        self.assertEqual(poster_url, "https://cdn.midjourney.com/video/demo/0_640_N.webp")

    def test_select_video_poster_source_url_derives_from_video_url(self) -> None:
        adapter = MjAdapter()

        poster_url = adapter._select_video_poster_source_url(
            object(),
            {"video_url": "https://cdn.midjourney.com/video/1237d4c2-0dd7-4989-b59f-fd72eb123f8f/0.mp4"},
        )

        self.assertEqual(
            poster_url,
            "https://cdn.midjourney.com/video/1237d4c2-0dd7-4989-b59f-fd72eb123f8f/0_640_N.webp",
        )

    def test_select_video_poster_source_url_ignores_stale_video_metadata(self) -> None:
        adapter = MjAdapter()

        poster_url = adapter._select_video_poster_source_url(
            object(),
            {"video_url": "https://cdn.midjourney.com/video/old-job/0.mp4"},
            expected_job_id="8576ded3-b218-465d-be46-6b5add5da4cb",
        )

        self.assertEqual(
            poster_url,
            "https://cdn.midjourney.com/video/8576ded3-b218-465d-be46-6b5add5da4cb/0_640_N.webp",
        )

    def test_select_best_detail_image_url_prefers_lightbox_original_for_job(self) -> None:
        adapter = MjAdapter()

        class FakeImage:
            def __init__(self, payload: dict[str, object]) -> None:
                self.payload = payload

            def evaluate(self, _expression: str, timeout: int = 1500) -> dict[str, object]:
                return self.payload

            def get_attribute(self, name: str, timeout: int = 1500) -> str | None:
                value = self.payload.get(name)
                return str(value) if value else None

        class FakeLocatorCollection:
            def __init__(self, items: list[FakeImage]) -> None:
                self.items = items

            def count(self) -> int:
                return len(self.items)

            def nth(self, index: int) -> FakeImage:
                return self.items[index]

        class FakePage:
            def locator(self, _selector: str) -> FakeLocatorCollection:
                return FakeLocatorCollection(
                    [
                        FakeImage(
                            {
                                "src": "https://cdn.midjourney.com/old-job/0_0.jpeg",
                                "current_src": "https://cdn.midjourney.com/old-job/0_0.jpeg",
                                "visible": True,
                                "natural_width": 2048,
                                "natural_height": 2048,
                            }
                        ),
                        FakeImage(
                            {
                                "src": "https://cdn.midjourney.com/9b6dbcb4-a139-4f50-94df-71ae95f6cd3f/0_0_384_N.webp?method=shortest&qst=6&quality=15",
                                "current_src": "https://cdn.midjourney.com/9b6dbcb4-a139-4f50-94df-71ae95f6cd3f/0_0_384_N.webp?method=shortest&qst=6&quality=15",
                                "visible": True,
                                "natural_width": 384,
                                "natural_height": 384,
                            }
                        ),
                        FakeImage(
                            {
                                "src": "https://cdn.midjourney.com/9b6dbcb4-a139-4f50-94df-71ae95f6cd3f/0_0.jpeg",
                                "current_src": "https://cdn.midjourney.com/9b6dbcb4-a139-4f50-94df-71ae95f6cd3f/0_0.jpeg",
                                "visible": True,
                                "natural_width": 2048,
                                "natural_height": 2048,
                            }
                        ),
                    ]
                )

        result = adapter._select_best_detail_image_url(
            FakePage(),
            expected_job_id="9b6dbcb4-a139-4f50-94df-71ae95f6cd3f",
        )

        self.assertEqual(
            result,
            "https://cdn.midjourney.com/9b6dbcb4-a139-4f50-94df-71ae95f6cd3f/0_0.jpeg",
        )


if __name__ == "__main__":
    unittest.main()
