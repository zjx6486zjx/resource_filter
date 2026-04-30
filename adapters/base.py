from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, List, TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Page
else:
    try:
        from playwright.sync_api import Page
    except ModuleNotFoundError:
        Page = Any

from resource_filter.models import FeedCardRef, ScrapeItemPayload


class SiteAdapter(ABC):
    site_name: str

    @abstractmethod
    def open_inspiration(self, page: Page, entry_url: str, **kwargs) -> None:
        """打开站点灵感/首页作品流。"""

    @abstractmethod
    def open_author_page(self, page: Page, author_url: str, **kwargs) -> None:
        """打开作者主页作品流。"""

    @abstractmethod
    def collect_feed_cards(self, page: Page, max_items: int | None = None, **kwargs) -> List[FeedCardRef]:
        """在当前作品流页面收集待处理卡片引用。"""

    @abstractmethod
    def extract_item_from_feed(self, page: Page, card_ref: FeedCardRef, **kwargs) -> ScrapeItemPayload:
        """从作品流卡片进入详情并抽取结构化数据。"""
