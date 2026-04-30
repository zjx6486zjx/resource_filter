from __future__ import annotations

import unittest
from unittest import mock

from resource_filter.adapters.xhs import XhsAdapter
from resource_filter.models import FeedCardRef


class _FakeTab:
    def __init__(self, text: str, *, visible: bool = True, attributes: dict[str, str] | None = None):
        self._text = text
        self._visible = visible
        self._attributes = attributes or {}

    def is_visible(self) -> bool:
        return self._visible

    def inner_text(self, timeout: int = 1000) -> str:
        return self._text

    def get_attribute(self, attribute_name: str, timeout: int = 1000) -> str | None:
        return self._attributes.get(attribute_name)


class _FakeTabs:
    def __init__(self, entries: list[_FakeTab]):
        self._entries = entries

    def count(self) -> int:
        return len(self._entries)

    def nth(self, index: int) -> _FakeTab:
        return self._entries[index]


class XhsAdapterTests(unittest.TestCase):
    def test_open_inspiration_preserves_search_result_url_even_when_keyword_is_present(self) -> None:
        adapter = XhsAdapter()
        page = mock.Mock()
        page.url = "https://www.xiaohongshu.com/search_result?keyword=demo&type=51"

        with mock.patch.object(adapter, "_pause") as pause, mock.patch.object(
            adapter,
            "_dismiss_popups",
        ) as dismiss, mock.patch.object(
            adapter,
            "_search_keyword",
        ) as search_keyword, mock.patch.object(
            adapter,
            "_switch_search_channel",
        ) as switch_channel, mock.patch.object(
            adapter,
            "_wait_for_feed",
        ) as wait_for_feed:
            adapter.open_inspiration(page, page.url, keyword="女明星 穿搭")

        page.goto.assert_called_once_with(page.url, wait_until="domcontentloaded")
        pause.assert_called_once_with(page, 1200, 260)
        dismiss.assert_called_once_with(page)
        search_keyword.assert_not_called()
        switch_channel.assert_not_called()
        wait_for_feed.assert_called_once_with(page)

    def test_collect_feed_cards_preserves_entry_search_result_channel(self) -> None:
        adapter = XhsAdapter()
        adapter._preserve_entry_search_results = True
        page = mock.Mock()
        expected = [FeedCardRef(index=0, detail_url="https://www.xiaohongshu.com/explore/demo")]

        with mock.patch.object(adapter, "_switch_search_channel") as switch_channel, mock.patch.object(
            adapter,
            "_resolve_target_tab_names",
            return_value=[],
        ), mock.patch.object(adapter, "_wait_for_feed"), mock.patch.object(
            adapter,
            "_collect_current_feed_cards",
            return_value=expected,
        ):
            result = adapter.collect_feed_cards(page, max_items=10, crawl_mode="inspiration", tab_limit=2)

        self.assertEqual(result, expected)
        switch_channel.assert_not_called()

    def test_resolve_target_tab_names_returns_empty_when_search_tabs_missing(self) -> None:
        adapter = XhsAdapter()
        page = mock.Mock()
        page.locator.return_value = _FakeTabs([])

        result = adapter._resolve_target_tab_names(page, None, 2)

        self.assertEqual(result, [])

    def test_resolve_target_tab_names_caps_to_available_tabs(self) -> None:
        adapter = XhsAdapter()
        page = mock.Mock()
        page.locator.return_value = _FakeTabs([_FakeTab("综合"), _FakeTab("张力"), _FakeTab("电影")])

        result = adapter._resolve_target_tab_names(page, None, 5)

        self.assertEqual(result, ["综合", "张力", "电影"])

    def test_resolve_target_tab_names_filters_missing_explicit_tabs(self) -> None:
        adapter = XhsAdapter()
        page = mock.Mock()
        page.locator.return_value = _FakeTabs([_FakeTab("综合"), _FakeTab("张力"), _FakeTab("电影")])

        result = adapter._resolve_target_tab_names(page, ["张力", "素材"], 5)

        self.assertEqual(result, ["张力"])

    def test_list_search_tab_names_reads_aria_details(self) -> None:
        adapter = XhsAdapter()
        page = mock.Mock()
        page.locator.return_value = _FakeTabs(
            [
                _FakeTab("", attributes={"aria-details": "综合"}),
                _FakeTab("", attributes={"aria-details": "张力"}),
            ]
        )

        result = adapter._list_search_tab_names(page)

        self.assertEqual(result, ["综合", "张力"])

    def test_normalize_note_url_rejects_listing_pages(self) -> None:
        adapter = XhsAdapter()

        self.assertIsNone(adapter._normalize_note_url("https://www.xiaohongshu.com/explore", adapter.EXPLORE_URL))
        self.assertIsNone(
            adapter._normalize_note_url("https://www.xiaohongshu.com/search_result?keyword=女明星", adapter.EXPLORE_URL)
        )
        self.assertEqual(
            adapter._normalize_note_url("/explore/69eb6371000000003701daaa", adapter.EXPLORE_URL),
            "https://www.xiaohongshu.com/explore/69eb6371000000003701daaa",
        )

    def test_open_feed_card_prefers_clicking_visible_card(self) -> None:
        adapter = XhsAdapter()
        page = mock.Mock()
        card_ref = FeedCardRef(index=0, detail_url="https://www.xiaohongshu.com/explore/69eb6371000000003701daaa")
        card = mock.Mock()
        click_target = mock.Mock()

        with mock.patch.object(adapter, "_resolve_feed_card", return_value=card) as resolve_card, mock.patch.object(
            adapter,
            "_first_visible",
            return_value=click_target,
        ) as first_visible, mock.patch.object(
            adapter,
            "_click_locator_like_human",
        ) as click_like_human, mock.patch.object(
            adapter,
            "_pause",
        ) as pause, mock.patch.object(
            adapter,
            "_dismiss_popups",
        ) as dismiss_popups:
            adapter._open_feed_card(page, card_ref)

        resolve_card.assert_called_once_with(page, card_ref)
        first_visible.assert_called_once()
        click_like_human.assert_called_once_with(page, click_target)
        pause.assert_called_once_with(page, 1000, 260)
        dismiss_popups.assert_not_called()
        page.goto.assert_not_called()

    def test_open_feed_card_falls_back_to_detail_url_when_click_fails(self) -> None:
        adapter = XhsAdapter()
        page = mock.Mock()
        card_ref = FeedCardRef(index=0, detail_url="https://www.xiaohongshu.com/explore/69eb6371000000003701daaa")

        with mock.patch.object(adapter, "_resolve_feed_card", side_effect=RuntimeError("missing")) as resolve_card:
            with mock.patch.object(adapter, "_pause") as pause, mock.patch.object(adapter, "_dismiss_popups") as dismiss:
                adapter._open_feed_card(page, card_ref)

        resolve_card.assert_called_once_with(page, card_ref)
        page.goto.assert_called_once_with(card_ref.detail_url, wait_until="domcontentloaded")
        pause.assert_called_once_with(page, 1000, 260)
        dismiss.assert_not_called()

    def test_collect_feed_cards_falls_back_to_current_feed_when_tabs_missing(self) -> None:
        adapter = XhsAdapter()
        page = mock.Mock()
        expected = [FeedCardRef(index=0, detail_url="https://www.xiaohongshu.com/explore/demo")]

        with mock.patch.object(adapter, "_switch_search_channel") as switch_channel, mock.patch.object(
            adapter,
            "_resolve_target_tab_names",
            return_value=[],
        ) as resolve_tabs, mock.patch.object(adapter, "_wait_for_feed") as wait_for_feed, mock.patch.object(
            adapter,
            "_load_all_cards",
        ) as load_all_cards, mock.patch.object(
            adapter,
            "_collect_current_feed_cards",
            return_value=expected,
        ) as collect_current_feed_cards, mock.patch.object(
            adapter,
            "_activate_tab",
        ) as activate_tab:
            result = adapter.collect_feed_cards(page, max_items=10, crawl_mode="inspiration", tab_limit=2)

        self.assertEqual(result, expected)
        switch_channel.assert_called_once_with(page, channel_id="image", channel_label="图文")
        resolve_tabs.assert_called_once_with(page, None, 2)
        wait_for_feed.assert_called_once_with(page)
        load_all_cards.assert_not_called()
        collect_current_feed_cards.assert_called_once_with(page, max_items=10)
        activate_tab.assert_not_called()

    def test_prepare_feed_for_card_does_not_preload_cards(self) -> None:
        adapter = XhsAdapter()
        page = mock.Mock()
        card_ref = FeedCardRef(index=20, detail_url="https://www.xiaohongshu.com/explore/demo")

        with mock.patch.object(adapter, "_wait_for_feed") as wait_for_feed, mock.patch.object(
            adapter,
            "_load_all_cards",
        ) as load_all_cards, mock.patch.object(
            adapter,
            "_activate_tab",
        ) as activate_tab:
            adapter._prepare_feed_for_card(page, card_ref)

        wait_for_feed.assert_called_once_with(page)
        load_all_cards.assert_not_called()
        activate_tab.assert_not_called()

    def test_preview_fallback_item_uses_card_metadata_when_detail_is_blocked(self) -> None:
        adapter = XhsAdapter()
        page = mock.Mock()
        page.url = "https://www.xiaohongshu.com/login"
        card_ref = FeedCardRef(
            index=2,
            detail_url="https://www.xiaohongshu.com/explore/69eb6371000000003701daaa",
            preview_image_url="https://example.com/preview.webp",
            title="女明星穿搭",
            author_name="作者",
            author_url="https://www.xiaohongshu.com/user/profile/demo",
            like_count=123,
            external_item_id="69eb6371000000003701daaa",
        )

        item = adapter._build_preview_fallback_item(page, card_ref, card_ref.detail_url or "")

        self.assertIsNotNone(item)
        assert item is not None
        self.assertEqual(item.source_image_url, "https://example.com/preview.webp")
        self.assertEqual(item.detail_url, card_ref.detail_url)
        self.assertEqual(item.prompt_text, "女明星穿搭")
        self.assertEqual(item.like_count, 123)
        self.assertEqual(item.external_item_id, "69eb6371000000003701daaa")
        self.assertEqual(item.raw_payload["detail"]["fallback_reason"], "detail_not_ready")

    def test_extract_item_falls_back_to_preview_when_detail_never_becomes_ready(self) -> None:
        adapter = XhsAdapter()
        page = mock.Mock()
        page.url = "https://www.xiaohongshu.com/search_result?keyword=demo"
        card_ref = FeedCardRef(
            index=0,
            detail_url="https://www.xiaohongshu.com/explore/69eb6371000000003701daaa",
            preview_image_url="https://example.com/preview.webp",
            title="女明星穿搭",
        )

        with mock.patch.object(adapter, "_prepare_feed_for_card") as prepare, mock.patch.object(
            adapter,
            "_open_feed_card",
        ) as open_card, mock.patch.object(
            adapter,
            "_wait_for_detail_ready",
            return_value=False,
        ) as wait_ready, mock.patch.object(
            adapter,
            "_return_to_feed",
        ) as return_to_feed:
            item = adapter.extract_item_from_feed(page, card_ref)

        self.assertEqual(item.source_image_url, "https://example.com/preview.webp")
        self.assertEqual(item.raw_payload["detail"]["fallback_reason"], "detail_not_ready")
        prepare.assert_called_once_with(page, card_ref)
        open_card.assert_called_once_with(page, card_ref)
        wait_ready.assert_called_once_with(page, card_ref)
        return_to_feed.assert_called_once()


if __name__ == "__main__":
    unittest.main()
