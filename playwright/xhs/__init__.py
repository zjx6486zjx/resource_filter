# -*- coding: utf-8 -*-
"""
XHS (小红书) 爬虫模块
包含爬虫配置、日志、异常处理、性能监控等功能
"""

__version__ = "1.0.0"
__author__ = "XHS Crawler Team"

# 导出主要类和函数
from .crawler_config import ScrollConfig, ClickConfig, SelectorConfig, PathConfig, BrowserConfig
from .crawler_logger import CrawlerLogger
from .crawler_exceptions import (
    CrawlerException, ElementNotFoundError, DOMError, ScrollError, ClickError,
    retry_on_exception, safe_execute, ErrorHandler
)
from .browser_session import BrowserSession
# 导出服务类
from .embedding_service import EmbeddingSearchService
from .keyword_service import KeywordService
from .image_service import ImageService
# 导出核心处理类
from .processor import XHSProcessor, quick_process_all, quick_search
from .crawler import XiaohongshuSmartCrawler
from .batch_processor import XHSBatchProcessor

__all__ = [
    'ScrollConfig', 'ClickConfig', 'SelectorConfig', 'PathConfig', 'BrowserConfig',
    'CrawlerLogger',
    'CrawlerException', 'ElementNotFoundError', 'DOMError', 'ScrollError', 'ClickError',
    'retry_on_exception', 'safe_execute', 'ErrorHandler',
    'BrowserSession',
    # 服务类
    'EmbeddingSearchService', 'KeywordService', 'ImageService',
    # 核心处理类
    'XHSProcessor', 'quick_process_all', 'quick_search',
    'XiaohongshuSmartCrawler', 'XHSBatchProcessor'
]