from __future__ import annotations


class SkipScrapeItem(Exception):
    """Raised when a discovered item should be skipped without marking the crawl as failed."""
