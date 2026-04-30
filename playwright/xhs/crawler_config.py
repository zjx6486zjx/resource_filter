#!/usr/bin/env python3
"""
爬虫配置管理模块
统一管理所有配置参数，提高代码可维护性
"""

import os
from dataclasses import dataclass
from typing import Dict, List, Optional
from pathlib import Path

@dataclass
class ScrollConfig:
    """滚动配置"""
    max_rounds: int = 30
    scroll_step: int = 1000
    stable_rounds_threshold: int = 4
    wait_time: float = 2.0
    large_scroll_step: int = 2000
    bottom_detection_threshold: int = 100

@dataclass
class ClickConfig:
    """点击配置"""
    max_retries: int = 3
    timeout: int = 10000
    scroll_timeout: int = 30000
    wait_after_click: float = 2.0
    retry_delay_multiplier: int = 2

@dataclass
class SelectorConfig:
    """选择器配置"""
    card_selectors: List[str] = None
    loading_selectors: List[str] = None
    no_more_selectors: List[str] = None
    
    def __post_init__(self):
        if self.card_selectors is None:
            self.card_selectors = [
                'section.note-item',
                '.note-item',
                'section[data-v-a264b01a][data-v-330d9cca]',
                '.feeds-container section',
                '.title'
            ]
        
        if self.loading_selectors is None:
            self.loading_selectors = [
                '.loading',
                '.feeds-loading',
                '[class*="loading"]'
            ]
        
        if self.no_more_selectors is None:
            self.no_more_selectors = [
                '.no-more',
                '.end-tip',
                '.load-end',
                '[class*="no-more"]',
                '[class*="end"]'
            ]

@dataclass
class PathConfig:
    """路径配置"""
    base_dir: Path = None
    results_dir: Path = None
    logs_dir: Path = None
    user_data_dir: Path = None
    
    def __post_init__(self):
        # 确保 base_dir 是 Path 对象
        if self.base_dir is None:
            self.base_dir = Path(__file__).parent
        elif isinstance(self.base_dir, str):
            self.base_dir = Path(self.base_dir)
        
        # 确保其他路径也是 Path 对象
        if self.results_dir is None:
            self.results_dir = self.base_dir / "xhs" / "results"
        elif isinstance(self.results_dir, str):
            self.results_dir = Path(self.results_dir)
        
        if self.logs_dir is None:
            self.logs_dir = self.base_dir / "logs"
        elif isinstance(self.logs_dir, str):
            self.logs_dir = Path(self.logs_dir)
        
        if self.user_data_dir is None:
            self.user_data_dir = self.base_dir / "playwright_user_data"
        elif isinstance(self.user_data_dir, str):
            self.user_data_dir = Path(self.user_data_dir)
        
        # 确保目录存在
        self.results_dir.mkdir(exist_ok=True)
        self.logs_dir.mkdir(exist_ok=True)

@dataclass
class BrowserConfig:
    """浏览器配置"""
    headless: bool = False
    viewport_width: int = 1920
    viewport_height: int = 1080
    user_agent: str = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    timeout: int = 30000

class CrawlerConfig:
    """
    爬虫主配置类
    集中管理所有配置参数
    """
    
    def __init__(self, config_file: Optional[str] = None):
        """
        初始化配置
        
        Args:
            config_file: 可选的配置文件路径
        """
        self.scroll = ScrollConfig()
        self.click = ClickConfig()
        self.selector = SelectorConfig()
        self.path = PathConfig()
        self.browser = BrowserConfig()
        
        # 如果提供了配置文件，加载配置
        if config_file and os.path.exists(config_file):
            self._load_from_file(config_file)
    
    def _load_from_file(self, config_file: str):
        """从文件加载配置"""
        # 这里可以实现从JSON/YAML文件加载配置的逻辑
        pass
    
    def get_default_url(self) -> str:
        """获取默认URL"""
        return f"file://{self.path.base_dir}/front.html"
    
    def get_results_file(self, url_hash: str) -> Path:
        """获取结果文件路径"""
        return self.path.results_dir / f"xiaohongshu_results_{url_hash}.json"
    
    def get_log_file(self) -> Path:
        """获取日志文件路径"""
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self.path.logs_dir / f"crawler_{timestamp}.log"
    
    def update_scroll_config(self, **kwargs):
        """更新滚动配置"""
        for key, value in kwargs.items():
            if hasattr(self.scroll, key):
                setattr(self.scroll, key, value)
    
    def update_click_config(self, **kwargs):
        """更新点击配置"""
        for key, value in kwargs.items():
            if hasattr(self.click, key):
                setattr(self.click, key, value)
    
    def to_dict(self) -> Dict:
        """转换为字典格式"""
        return {
            'scroll': self.scroll.__dict__,
            'click': self.click.__dict__,
            'selector': self.selector.__dict__,
            'browser': self.browser.__dict__
        }
    
    def print_config(self):
        """打印当前配置"""
        print("=== 爬虫配置信息 ===")
        print(f"滚动配置: {self.scroll}")
        print(f"点击配置: {self.click}")
        print(f"选择器配置: 卡片选择器数量={len(self.selector.card_selectors)}")
        print(f"路径配置: 基础目录={self.path.base_dir}")
        print(f"浏览器配置: 无头模式={self.browser.headless}")

# 全局默认配置实例
default_config = CrawlerConfig()