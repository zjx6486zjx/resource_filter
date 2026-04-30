#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小红书智能爬虫 - 增强版
支持智能滚动、多重选择器、错误恢复等功能
集成配置管理、日志系统、异常处理和性能监控
"""

import json
import time
import os
import hashlib
import logging
import requests
from datetime import datetime
from urllib.parse import urlparse
from pathlib import Path
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from playwright_config import PlaywrightConfig

# 导入自定义模块
from .crawler_config import ScrollConfig, ClickConfig, SelectorConfig, PathConfig, BrowserConfig
from .crawler_logger import CrawlerLogger
from .crawler_exceptions import (
    CrawlerException, ElementNotFoundError, DOMError, ScrollError, ClickError,
    retry_on_exception, safe_execute, ErrorHandler
)


class XiaohongshuSmartCrawler:
    """
    智能小红书爬虫类
    支持动态加载、断点续传、智能定位和实时保存
    集成配置管理、日志系统、异常处理和性能监控
    """
    
    def __init__(self, user_data_dir=None, config_dir=None):
        """
        初始化爬虫
        
        Args:
            user_data_dir (str): 用户数据目录路径
            config_dir (str): 配置文件目录
        """
        # 设置默认用户数据目录为相对路径
        if user_data_dir is None:
            user_data_dir = "playwright_user_data"
        self.playwright_config = PlaywrightConfig(user_data_dir=user_data_dir)
        self.page = None
        self.crawled_data = []
        self.target_url = None
        self.url_hash = None
        self.results_file = None
        self.max_retries = 3
        self.scroll_attempts = 0
        self.max_scroll_attempts = 5
        
        # 配置管理
        self.config_dir = config_dir or os.path.dirname(__file__)
        self.scroll_config = ScrollConfig()
        self.click_config = ClickConfig()
        self.selector_config = SelectorConfig()
        self.path_config = PathConfig(base_dir=self.config_dir)
        self.browser_config = BrowserConfig()
        
        # 日志系统
        from datetime import datetime
        log_file = self.path_config.logs_dir / f"crawler_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        self.logger = CrawlerLogger(
            log_file=log_file,
            level=logging.INFO
        )
        
        # 异常处理
        self.error_handler = ErrorHandler(logger=self.logger)
        
        # 图片下载配置
        self.pics_dir = Path(__file__).parent / "pics"
        self.pics_dir.mkdir(exist_ok=True)
        
        # 创建按日期分组的子目录
        self.today_dir = self.pics_dir / datetime.now().strftime("%Y-%m-%d")
        self.today_dir.mkdir(exist_ok=True)
        
        # 图片下载会话
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Referer': 'https://www.xiaohongshu.com/'
        })
        
        # 下载统计信息
        self.download_stats = {
            'total': 0,
            'success': 0,
            'skipped': 0,
            'failed': 0
        }
        
        self.logger.info("爬虫初始化完成", extra={
            "user_data_dir": user_data_dir,
            "config_dir": self.config_dir,
            "pics_dir": str(self.pics_dir)
        })
        
    def get_url_hash(self, url):
        """
        生成URL的哈希值作为唯一标识
        
        Args:
            url (str): 目标URL
            
        Returns:
            str: URL哈希值
        """
        return hashlib.md5(url.encode()).hexdigest()[:8]
    
    def get_results_filename(self, url):
        """
        根据URL生成结果文件名
        
        Args:
            url (str): 目标URL
            
        Returns:
            str: 结果文件名
        """
        url_hash = self.get_url_hash(url)
        # 确保results目录存在
        results_dir = os.path.join(os.path.dirname(__file__), 'xhs', 'results')
        os.makedirs(results_dir, exist_ok=True)
        return os.path.join(results_dir, f"xiaohongshu_results_{url_hash}.json")
    
    def load_existing_results(self):
        """
        加载已有的爬取结果
        
        Returns:
            dict: 已有的爬取数据
        """
        if not self.results_file or not os.path.exists(self.results_file):
            return {'notes': [], 'crawl_info': {}}
            
        try:
            with open(self.results_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.crawled_data = data.get('notes', [])
                print(f"加载已有结果: 共 {len(self.crawled_data)} 个笔记")
                return data
        except Exception as e:
            print(f"加载结果文件失败: {e}")
            return {'notes': [], 'crawl_info': {}}
    
    def save_results(self):
        """
        实时保存爬取结果（按index顺序排序）
        """
        if not self.results_file:
            return
            
        try:
            # 按index顺序排序笔记
            sorted_notes = sorted(self.crawled_data, key=lambda x: x.get('index', 0))
            
            results_data = {
                'crawl_info': {
                    'total_count': len(sorted_notes),
                    'last_update': datetime.now().isoformat(),
                    'target_url': self.target_url,
                    'url_hash': self.url_hash
                },
                'notes': sorted_notes
            }
            
            with open(self.results_file, 'w', encoding='utf-8') as f:
                json.dump(results_data, f, ensure_ascii=False, indent=2)
                
            print(f"✓ 已保存 {len(sorted_notes)} 个笔记到 {self.results_file}")
                
        except Exception as e:
            print(f"保存结果失败: {e}")
    
    def get_crawled_indices(self):
        """
        获取已爬取的卡片索引集合，从结果文件中读取
        
        Returns:
            set: 已爬取的卡片索引
        """
        crawled_indices = set()
        
        # 先从内存中的crawled_data获取
        for note in self.crawled_data:
            if 'index' in note:
                crawled_indices.add(note['index'])
        
        # 从结果文件中读取已有的index
        try:
            if os.path.exists(self.results_file):
                with open(self.results_file, 'r', encoding='utf-8') as f:
                    existing_data = json.load(f)
                    for note in existing_data:
                        if 'index' in note:
                            crawled_indices.add(note['index'])
        except Exception as e:
            print(f"读取结果文件时出错: {e}")
        
        return crawled_indices
    
    @retry_on_exception(max_retries=2, delay=2.0)
    def start_crawler(self, target_url, headless=False):
        """
        启动爬虫
        
        Args:
            target_url (str): 目标URL
            headless (bool): 是否无头模式
        """
        try:
            self.target_url = target_url
            self.url_hash = self.get_url_hash(target_url)
            self.results_file = self.get_results_filename(target_url)
            
            self.logger.info("启动小红书智能爬虫", extra={"target_url": target_url})
            print(f"🚀 启动小红书智能爬虫...")
            print(f"📍 目标URL: {target_url}")
            print(f"URL标识: {self.url_hash}")
            print(f"结果文件: {self.results_file}")
            
            # 加载已有结果
            self.load_existing_results()
            
            # 启动浏览器
            self.logger.info("正在启动浏览器")
            print("🌐 正在启动浏览器...")
            browser_initialized = self.playwright_config.initialize_browser()
            if not browser_initialized:
                raise Exception("浏览器初始化失败，可能是在 asyncio 环境中使用了同步 API")
            
            self.page = self.playwright_config.get_page()
            if not self.page:
                raise Exception("无法获取页面实例")
                
            if target_url:
                self.page.goto(target_url)
            
            self.logger.info("页面加载完成")
            print(f"✅ 页面加载完成")
            
        except Exception as e:
            crawler_error = self.error_handler.handle_error(e, "启动爬虫")
            self.logger.error("启动爬虫失败", error=crawler_error)
            print(f"❌ 启动爬虫失败: {crawler_error}")
            raise
        
    def get_all_data_indices(self):
        """
        获取页面中所有的data-index
        
        Returns:
            set: 包含所有data-index的集合
        """
        try:
            indices = self.page.evaluate("""
                () => {
                    const sections = document.querySelectorAll('section[data-index]');
                    const indices = [];
                    sections.forEach(section => {
                        const dataIndex = section.getAttribute('data-index');
                        if (dataIndex) {
                            indices.push(parseInt(dataIndex));
                        }
                    });
                    return indices.sort((a, b) => a - b);
                }
            """)
            return set(indices) if indices else set()
        except Exception as e:
            print(f"获取data-index时出错: {e}")
            return set()
    
    def check_crawl_time_before_2024(self):
        """
        检查最近爬取的笔记中是否有crawl_time早于2024年的
        
        Returns:
            bool: 如果发现2024年之前的笔记返回True，否则返回False
        """
        try:
            # 检查内存中最近爬取的笔记
            for note in self.crawled_data[-3:]:  # 检查最近3个笔记
                crawl_time = note.get('crawl_time', '')
                if crawl_time:
                    # 提取年份进行比较
                    try:
                        year = int(crawl_time[:4])
                        if year < 2024:
                            print(f"⚠️ 发现2024年之前的笔记，crawl_time: {crawl_time}，年份: {year}")
                            return True
                    except (ValueError, IndexError):
                        # 如果无法解析年份，使用字符串比较作为备选
                        if crawl_time < '2024-01-01':
                            print(f"⚠️ 发现2024年之前的笔记，crawl_time: {crawl_time}")
                            return True
            
            # 检查结果文件中最近的笔记
            if os.path.exists(self.results_file):
                with open(self.results_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    notes = data.get('notes', [])
                    # 检查最近的几个笔记
                    for note in notes[-3:]:
                        crawl_time = note.get('crawl_time', '')
                        if crawl_time:
                            try:
                                year = int(crawl_time[:4])
                                if year < 2024:
                                    print(f"⚠️ 发现2024年之前的笔记，crawl_time: {crawl_time}，年份: {year}")
                                    return True
                            except (ValueError, IndexError):
                                if crawl_time < '2024-01-01':
                                    print(f"⚠️ 发现2024年之前的笔记，crawl_time: {crawl_time}")
                                    return True
        except Exception as e:
            print(f"检查crawl_time时出错: {e}")
        
        return False
    
    def smart_scroll_and_load(self, target_card_count=None):
        """
        智能滑动和加载更多内容，先读取结果文件获取已有index，
        如果当前页面data-index都已存在则继续滑动，
        如果发现新的data-index则逐个点击处理完毕后再继续滑动
        
        停止条件：
        1. 没有新笔记
        2. 达到目标数量
        3. 到达页面底部
        4. crawl_time早于2024年
        
        Args:
            target_card_count (int): 目标卡片数量，None表示尽可能多加载
            
        Returns:
            int: 当前卡片总数
        """
        print("开始智能滑动加载...")
        
        # 先滑动到顶部
        self.page.evaluate("window.scrollTo(0, 0)")
        time.sleep(1)
        
        # 读取结果文件获取已有的index
        crawled_indices = self.get_crawled_indices()
        print(f"从结果文件读取到已爬取的index: {sorted(crawled_indices)}")
        
        # 逐步向下滑动，触发懒加载
        scroll_step = 800  # 减小滚动步长，更精细地控制
        stable_count = 0
        
        for scroll_round in range(30):  # 最多滚动30轮
            # 检查页面底部状态
            page_info = self.page.evaluate("""
                () => {
                    const scrollTop = window.pageYOffset;
                    const scrollHeight = document.documentElement.scrollHeight;
                    const clientHeight = window.innerHeight;
                    const isAtBottom = scrollTop + clientHeight >= scrollHeight - 100;
                    
                    // 检查是否有加载指示器
                    const loadingElements = document.querySelectorAll('.loading, .feeds-loading, [class*="loading"]');
                    const hasLoadingIndicator = Array.from(loadingElements).some(el => 
                        el.offsetParent !== null && getComputedStyle(el).display !== 'none'
                    );
                    
                    return {
                        scrollTop,
                        scrollHeight,
                        clientHeight,
                        isAtBottom,
                        hasLoadingIndicator,
                        scrollPercentage: Math.round((scrollTop / (scrollHeight - clientHeight)) * 100)
                    };
                }
            """)
            
            print(f"滚动轮次 {scroll_round + 1}: 滚动进度 {page_info['scrollPercentage']}%, 是否到底部: {page_info['isAtBottom']}, 有加载指示器: {page_info['hasLoadingIndicator']}")
            
            # 解析当前页面的data-index
            current_page_indices = self.get_all_data_indices()
            print(f"当前页面data-index: {sorted(current_page_indices)}")
            
            # 检查当前页面的data-index是否都已在结果文件中
            new_indices = current_page_indices - crawled_indices
            
            if new_indices:
                print(f"✅ 发现新的data-index: {sorted(new_indices)}")
                print(f"开始逐个点击处理新发现的data-index...")
                
                # 逐个点击处理新的data-index
                for index in sorted(new_indices):
                    print(f"\n--- 处理新发现的data-index {index} ---")
                    try:
                        # 智能点击卡片（直接点击，不强制刷新页面）
                        if self.smart_click_card(index, after_scroll=False):
                            # 提取信息
                            note_info = self.extract_note_info()
                            note_info['index'] = index
                            
                            if note_info['title'] or note_info['desc'] or note_info['images']:
                                self.crawled_data.append(note_info)
                                print(f"✓ 成功提取data-index {index} 的笔记")
                                # 更新已爬取的索引
                                crawled_indices.add(index)
                            else:
                                print(f"✗ data-index {index} 的笔记信息为空")
                            
                            # 关闭弹框
                            self.close_modal()
                            
                            # 实时保存结果
                            self.save_results()
                            
                            time.sleep(1)
                        else:
                            print(f"✗ data-index {index} 点击失败")
                            
                    except Exception as e:
                        print(f"处理data-index {index} 时出错: {e}")
                        self.close_modal()
                
                print(f"当前页面所有新data-index处理完毕，继续滑动...")
                stable_count = 0
                
                # 检查是否有2024年之前的笔记，如果有则停止滑动
                if self.check_crawl_time_before_2024():
                    print(f"🛑 检测到2024年之前的笔记，停止滑动")
                    break
            else:
                print(f"❌ 当前页面所有data-index都已存在于结果文件中")
                stable_count += 1
            
            # 如果达到目标数量，停止滚动
            if target_card_count and len(crawled_indices) >= target_card_count:
                print(f"已达到目标卡片数量: {len(crawled_indices)}")
                break
            
            # 如果已经到底部，停止滚动
            if page_info['isAtBottom']:
                print(f"已到达页面底部，停止滚动")
                break
            
            # 正常滚动到下一个位置
            scroll_position = (scroll_round + 1) * scroll_step
            self.page.evaluate(f"window.scrollTo(0, {scroll_position})")
            time.sleep(2)  # 等待页面稳定
            
            # 如果连续3轮没有新data-index，尝试不同的策略
            if stable_count >= 3:
                print(f"连续 {stable_count} 轮无新data-index，尝试大幅滚动")
                # 尝试大幅滚动
                self.page.evaluate("window.scrollBy(0, 2000)")
                time.sleep(3)
                
                # 再次检查
                retry_data_indices = self.get_all_data_indices()
                new_after_big_scroll = retry_data_indices - crawled_indices
                if new_after_big_scroll:
                    print(f"✅ 大幅滚动后发现新data-index: {sorted(new_after_big_scroll)}")
                    stable_count = 0
                else:
                    print("❌ 大幅滚动后仍无新data-index")
                    # 如果大幅滚动也没有新内容，可能真的没有更多了
                    if stable_count >= 5:
                        print("多次尝试无新内容，停止滚动")
                        break
        
        # 最后滑动到页面顶部
        self.page.evaluate("window.scrollTo(0, 0)")
        time.sleep(2)
        
        # 最终统计
        final_indices = self.get_all_data_indices()
        final_crawled_indices = self.get_crawled_indices()
        
        print(f"🎯 智能滑动完成")
        print(f"📊 页面发现的data-index: {sorted(final_indices)}")
        print(f"📈 总共发现的data-index数量: {len(final_indices)}")
        print(f"🎯 已爬取的data-index数量: {len(final_crawled_indices)}")
        
        return len(final_indices)
    
    def get_note_cards(self, force_refresh=False):
        """
        获取页面中的笔记卡片（支持强制刷新）
        
        Args:
            force_refresh (bool): 是否强制重新解析页面
        
        Returns:
            list: 卡片元素列表，按data-index排序
        """
        try:
            if force_refresh:
                print("强制重新解析页面内容...")
                # 等待页面稳定
                time.sleep(1)
                # 触发页面重新渲染
                self.page.evaluate("window.dispatchEvent(new Event('resize'))")
                time.sleep(0.5)
            
            # 优先使用section[data-index]选择器，这是最准确的
            try:
                self.page.wait_for_selector('section[data-index]', timeout=5000)
                cards = self.page.query_selector_all('section[data-index]')
                
                if cards:
                    valid_cards = []
                    for card in cards:
                        try:
                            # 获取data-index属性
                            data_index = card.get_attribute('data-index')
                            if data_index:
                                # 为卡片添加索引信息
                                card._data_index = int(data_index)
                                valid_cards.append(card)
                        except Exception as e:
                            print(f"处理卡片时出错: {e}")
                            continue
                    
                    if valid_cards:
                        # 按data-index排序
                        valid_cards.sort(key=lambda x: getattr(x, '_data_index', 0))
                        print(f"使用选择器 'section[data-index]' 找到 {len(valid_cards)} 个有效卡片")
                        
                        # 打印卡片索引信息用于调试
                        indices = [getattr(card, '_data_index', 'N/A') for card in valid_cards]
                        print(f"所有卡片的data-index: {indices}")
                        
                        return valid_cards
            except PlaywrightTimeoutError:
                print("未找到section[data-index]元素，尝试其他选择器")
            
            # 如果section[data-index]不可用，尝试其他选择器
            fallback_selectors = [
                'section.note-item[data-index]',        # 优先使用有data-index的卡片
                'section.note-item',                    # 主要选择器 - 实际的卡片容器
                '.note-item[data-index]',              # 有data-index的备用选择器
                '.note-item',                          # 备用选择器
                'section[data-v-a264b01a][data-v-330d9cca]',  # 具体的Vue组件选择器
                '.feeds-container section',             # 容器内的section
                'section',                             # 通用section选择器
                '.title'                               # 原选择器作为后备
            ]
            
            for selector in fallback_selectors:
                try:
                    # 等待卡片加载
                    self.page.wait_for_selector(selector, timeout=5000)
                    cards = self.page.query_selector_all(selector)
                    if cards:
                        # 过滤掉不可见或无效的卡片，并获取data-index信息
                        valid_cards = []
                        for i, card in enumerate(cards):
                            try:
                                # 检查卡片是否有有效的内容
                                # 支持front.html中的结构：img, h3, p等元素
                                has_content = (
                                    card.query_selector('.title, .cover, a') or  # 原有结构
                                    card.query_selector('img') or               # front.html中的图片
                                    card.query_selector('h3') or                # front.html中的标题
                                    card.query_selector('p') or                 # front.html中的描述
                                    card.query_selector('[class*="title"]') or  # 包含title的类名
                                    card.query_selector('[class*="cover"]')     # 包含cover的类名
                                )
                                
                                if has_content:
                                    # 获取data-index属性
                                    data_index = card.get_attribute('data-index')
                                    if data_index:
                                        # 为卡片添加索引信息
                                        card._data_index = int(data_index)
                                    else:
                                        # 如果没有data-index，使用位置索引
                                        card._data_index = i + 1
                                    valid_cards.append(card)
                            except:
                                continue
                        
                        if valid_cards:
                            # 按data-index排序
                            valid_cards.sort(key=lambda x: getattr(x, '_data_index', 0))
                            print(f"使用选择器 '{selector}' 找到 {len(valid_cards)} 个有效卡片 (总共 {len(cards)} 个)")
                            
                            # 打印卡片索引信息用于调试
                            indices = [getattr(card, '_data_index', 'N/A') for card in valid_cards[:10]]
                            print(f"前10个卡片的data-index: {indices}")
                            
                            return valid_cards
                except PlaywrightTimeoutError:
                    continue
            
            print("未找到任何有效卡片")
            return []
        except Exception as e:
            print(f"获取卡片时出错: {e}")
            return []
    
    def debug_page_structure(self, target_index=None):
        """
        调试页面结构，帮助分析问题
        
        Args:
            target_index (int): 目标卡片索引，用于详细分析
        """
        try:
            print("\n=== 页面结构调试 ===")
            
            # 基本页面信息
            page_info = self.page.evaluate("""
                () => {
                    return {
                        url: window.location.href,
                        title: document.title,
                        readyState: document.readyState,
                        scrollHeight: document.documentElement.scrollHeight,
                        clientHeight: window.innerHeight,
                        scrollTop: window.pageYOffset
                    };
                }
            """)
            
            print(f"页面URL: {page_info['url']}")
            print(f"页面标题: {page_info['title']}")
            print(f"加载状态: {page_info['readyState']}")
            print(f"页面高度: {page_info['scrollHeight']}")
            print(f"视口高度: {page_info['clientHeight']}")
            print(f"滚动位置: {page_info['scrollTop']}")
            
            # 检查各种选择器的卡片数量
            selectors_to_check = [
                'section[data-index]',                  # front.html结构
                'section.note-item',
                '.note-item',
                'section[data-v-a264b01a][data-v-330d9cca]',
                '.feeds-container section',
                'section',                             # 通用section
                '.title'
            ]
            
            print("\n--- 选择器分析 ---")
            for selector in selectors_to_check:
                try:
                    elements = self.page.query_selector_all(selector)
                    print(f"{selector}: {len(elements)} 个元素")
                    
                    # 对于section[data-index]，显示前几个的data-index值
                    if selector == 'section[data-index]' and elements:
                        indices = []
                        for i, elem in enumerate(elements[:10]):  # 只检查前10个
                            try:
                                data_index = elem.get_attribute('data-index')
                                indices.append(data_index)
                            except:
                                indices.append('N/A')
                        print(f"  前10个data-index值: {indices}")
                        
                except Exception as e:
                    print(f"{selector}: 查询失败 - {e}")
            
            # 如果指定了目标索引，详细分析该卡片
            if target_index:
                print(f"\n--- 第 {target_index} 个卡片详细分析 ---")
                cards = self.get_note_cards()
                if target_index <= len(cards):
                    card = cards[target_index - 1]
                    
                    # 获取卡片的data-index
                    data_index = card.get_attribute('data-index')
                    print(f"卡片data-index: {data_index}")
                    
                    # 获取卡片的HTML结构
                    card_html = card.inner_html()
                    print(f"卡片HTML结构 (前500字符): {card_html[:500]}...")
                    
                    # 检查卡片内的可点击元素
                    clickable_elements = []
                    clickable_selectors = ['a', 'img', 'h3', 'p', '.title', '.cover']
                    for sel in clickable_selectors:
                        try:
                            elements = card.query_selector_all(sel)
                            if elements:
                                clickable_elements.append(f"{sel}: {len(elements)}个")
                        except:
                            pass
                    print(f"可点击元素: {', '.join(clickable_elements)}")
                    
                    # 检查卡片的可见性和位置
                    card_info = self.page.evaluate("""
                        (element) => {
                            const rect = element.getBoundingClientRect();
                            return {
                                visible: element.offsetParent !== null,
                                inViewport: rect.top >= 0 && rect.bottom <= window.innerHeight,
                                position: {
                                    top: rect.top,
                                    left: rect.left,
                                    width: rect.width,
                                    height: rect.height
                                }
                            };
                        }
                    """, card)
                    
                    print(f"卡片可见性: {card_info}")
                else:
                    print(f"目标卡片索引 {target_index} 超出范围 (总共 {len(cards)} 个卡片)")
            
        except Exception as e:
            print(f"调试页面结构时出错: {e}")
    
    def check_page_loading_status(self):
        """
        检查页面加载状态
        
        Returns:
            dict: 页面状态信息
        """
        try:
            status = self.page.evaluate("""
                () => {
                    // 检查文档加载状态
                    const readyState = document.readyState;
                    
                    // 检查是否有正在进行的网络请求
                    const performanceEntries = performance.getEntriesByType('navigation');
                    const loadComplete = performanceEntries.length > 0 && performanceEntries[0].loadEventEnd > 0;
                    
                    // 检查是否有懒加载元素
                    const lazyElements = document.querySelectorAll('[loading="lazy"], [data-lazy]');
                    
                    // 检查滚动容器
                    const scrollContainers = document.querySelectorAll('.feeds-container, .note-list, [class*="scroll"]');
                    
                    // 检查加载指示器
                    const loadingIndicators = document.querySelectorAll('.loading, .feeds-loading, [class*="loading"]');
                    const activeLoadingCount = Array.from(loadingIndicators).filter(el => 
                        el.offsetParent !== null && getComputedStyle(el).display !== 'none'
                    ).length;
                    
                    return {
                        readyState,
                        loadComplete,
                        lazyElementsCount: lazyElements.length,
                        scrollContainersCount: scrollContainers.length,
                        activeLoadingCount,
                        url: window.location.href,
                        timestamp: Date.now()
                    };
                }
            """)
            
            print(f"页面加载状态: {status}")
            return status
            
        except Exception as e:
            print(f"检查页面加载状态失败: {e}")
            return None
    
    def get_image_filename(self, url):
        """
        根据图片URL生成本地文件名
        
        Args:
            url (str): 图片URL
            
        Returns:
            str: 本地文件名
        """
        try:
            # 解析URL
            parsed_url = urlparse(url)
            
            # 获取文件扩展名
            path = parsed_url.path
            if '.' in path:
                ext = path.split('.')[-1].lower()
                # 确保是有效的图片扩展名
                if ext not in ['jpg', 'jpeg', 'png', 'gif', 'webp']:
                    ext = 'jpg'  # 默认扩展名
            else:
                ext = 'jpg'  # 默认扩展名
            
            # 使用URL的哈希值作为文件名，避免重复和特殊字符问题
            url_hash = hashlib.md5(url.encode()).hexdigest()
            filename = f"{url_hash}.{ext}"
            
            return filename
            
        except Exception as e:
            print(f"生成文件名失败: {e}")
            # 使用时间戳作为备用文件名
            timestamp = int(time.time() * 1000)
            return f"image_{timestamp}.jpg"
    
    def download_image(self, url, filename=None):
        """
        下载单个图片
        
        Args:
            url (str): 图片URL
            filename (str, optional): 指定的文件名，如果不提供则自动生成
            
        Returns:
            str or None: 成功时返回本地文件路径，失败时返回None
        """
        try:
            self.download_stats['total'] += 1
            
            if not filename:
                filename = self.get_image_filename(url)
            
            file_path = self.today_dir / filename
            
            # 如果文件已存在，跳过下载
            if file_path.exists():
                print(f"图片已存在，跳过下载: {filename}")
                self.download_stats['skipped'] += 1
                # 返回相对于xhs目录的路径
                relative_path = file_path.relative_to(Path(__file__).parent)
                return str(relative_path).replace('\\', '/')
            
            print(f"开始下载图片: {url}")
            
            # 下载图片
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            
            # 保存图片
            with open(file_path, 'wb') as f:
                f.write(response.content)
            
            print(f"图片下载成功: {filename}")
            self.download_stats['success'] += 1
            # 返回相对于xhs目录的路径
            relative_path = file_path.relative_to(Path(__file__).parent)
            return str(relative_path).replace('\\', '/')
            
        except Exception as e:
            print(f"下载图片失败 {url}: {e}")
            self.download_stats['failed'] += 1
            return None
    
    def download_note_images(self, note_data):
        """
        下载笔记中的所有图片
        
        Args:
            note_data (dict): 笔记数据
            
        Returns:
            list: 本地图片路径列表
        """
        local_images = []
        
        if 'images' in note_data and note_data['images']:
            print(f"开始下载笔记图片，共 {len(note_data['images'])} 张")
            
            for i, img_url in enumerate(note_data['images']):
                if img_url:  # 确保URL不为空
                    # 为每张图片生成唯一的文件名
                    base_filename = self.get_image_filename(img_url)
                    name, ext = base_filename.rsplit('.', 1)
                    filename = f"{name}_{i+1}.{ext}"
                    
                    local_path = self.download_image(img_url, filename)
                    if local_path:
                        local_images.append(local_path)
        
        return local_images
    
    def extract_note_info(self):
        """
        提取当前弹框中的笔记信息
        
        Returns:
            dict: 提取的笔记信息
        """
        note_info = {
            'title': '',
            'desc': '',
            'images': [],
            'local_images': [],  # 新增字段：本地图片路径
            'publish_time': '',
            'crawl_time': datetime.now().isoformat()
        }
        
        try:
            # 等待弹框加载
            self.page.wait_for_selector('.note-content', timeout=5000)
            
            # 提取标题
            try:
                title_element = self.page.query_selector('.note-content .title')
                if title_element:
                    note_info['title'] = title_element.inner_text().strip()
                    print(f"提取标题: {note_info['title'][:50]}...")
            except Exception as e:
                print(f"提取标题失败: {e}")
            
            # 提取描述
            try:
                desc_element = self.page.query_selector('.note-content .desc')
                if desc_element:
                    note_info['desc'] = desc_element.inner_text().strip()
                    print(f"提取描述: {note_info['desc'][:100]}...")
            except Exception as e:
                print(f"提取描述失败: {e}")
            
            # 提取发布时间
            try:
                date_element = self.page.query_selector('.date')
                if date_element:
                    note_info['publish_time'] = date_element.inner_text().strip()
                    print(f"提取发布时间: {note_info['publish_time']}")
            except Exception as e:
                print(f"提取发布时间失败: {e}")
            
            # 提取图片
            try:
                img_containers = self.page.query_selector_all('.img-container img')
                for img in img_containers:
                    src = img.get_attribute('src')
                    if src:
                        note_info['images'].append(src)
                print(f"提取到 {len(note_info['images'])} 张图片")
                
                # 下载图片并保存本地路径
                if note_info['images']:
                    note_info['local_images'] = self.download_note_images(note_info)
                    print(f"成功下载 {len(note_info['local_images'])} 张图片到本地")
                    
            except Exception as e:
                print(f"提取图片失败: {e}")
                
        except PlaywrightTimeoutError:
            print("弹框加载超时，可能页面结构发生变化")
        
        return note_info
    
    def close_modal(self):
        """
        关闭弹框
        
        Returns:
            bool: 是否成功关闭
        """
        try:
            # 尝试多种关闭按钮的选择器
            close_selectors = [
                '.close-box svg',
                '.close-circle .close svg',
                '[class*="close"]',
                'svg[width="18"][height="18"]',
                'svg[width="20"][height="20"]'
            ]
            
            for selector in close_selectors:
                try:
                    close_button = self.page.query_selector(selector)
                    if close_button and close_button.is_visible():
                        print(f"找到关闭按钮: {selector}")
                        close_button.click()
                        time.sleep(1)
                        return True
                except Exception as e:
                    continue
            
            # 如果找不到关闭按钮，尝试按ESC键
            print("未找到关闭按钮，尝试按ESC键")
            self.page.keyboard.press('Escape')
            time.sleep(1)
            return True
            
        except Exception as e:
            print(f"关闭弹框失败: {e}")
            return False
    
    def smart_click_card(self, data_index, after_scroll=False):
        """
        智能点击卡片（通过data-index直接查找）
        
        Args:
            data_index (int): 卡片的data-index值
            after_scroll (bool): 是否在滑动后调用（需要强制重新解析）
            
        Returns:
            bool: 是否成功点击
        """
        for retry in range(self.max_retries):
            try:
                # 如果是滑动后调用，强制重新解析页面
                force_refresh = after_scroll or retry > 0
                
                # 获取当前所有卡片
                cards = self.get_note_cards(force_refresh=force_refresh)
                print(f"当前页面共有 {len(cards)} 个卡片，查找data-index={data_index}的卡片")
                
                # 直接通过data-index属性查找卡片
                target_card = None
                for card in cards:
                    try:
                        card_data_index = card.get_attribute('data-index')
                        if card_data_index and int(card_data_index) == data_index:
                            target_card = card
                            print(f"找到目标卡片，data-index={data_index}")
                            break
                    except Exception as e:
                        continue
                
                # 如果没找到对应data-index的卡片
                if target_card is None:
                    print(f"未找到data-index={data_index}的卡片，可能需要滚动加载更多内容")
                    # 不进行强制加载，直接返回失败，让上层逻辑处理
                    return False
                
                card = target_card
                actual_data_index = card.get_attribute('data-index')
                print(f"准备点击卡片，目标data-index: {data_index}, 实际data-index: {actual_data_index}")
                
                # 检查卡片是否可见和可点击
                if not card.is_visible():
                    print(f"卡片 data-index={data_index} 不可见，尝试滚动到视图中...")
                    # 滚动到卡片位置
                    card.scroll_into_view_if_needed()
                    time.sleep(2)
                
                # 滚动到卡片位置 - 增加超时时间
                try:
                    card.scroll_into_view_if_needed(timeout=10000)
                    time.sleep(2)
                    
                    # 确保卡片在视口中心
                    self.page.evaluate('''(element) => {
                        element.scrollIntoView({
                            behavior: 'smooth',
                            block: 'center',
                            inline: 'center'
                        });
                    }''', card)
                    time.sleep(1)
                except Exception as scroll_error:
                    print(f"滚动到卡片失败: {scroll_error}")
                    # 尝试手动滚动到卡片位置
                    try:
                        card.scroll_into_view_if_needed()
                    except:
                        pass
                    time.sleep(2)
                
                # 尝试多种点击方式
                click_success = False
                
                # 方式1: 直接点击卡片
                try:
                    print(f"尝试直接点击data-index={data_index}的卡片...")
                    card.click(timeout=5000)
                    click_success = True
                except Exception as e:
                    print(f"直接点击失败: {e}")
                
                # 方式2: 点击卡片内的链接或图片
                if not click_success:
                    try:
                        # 查找卡片内的可点击元素
                        clickable_selectors = [
                            'a.cover',           # 封面链接
                            '.cover',            # 封面
                            'a.title',           # 标题链接
                            '.title',            # 标题
                            'a',                 # 任何链接（front.html中的链接）
                            'img',               # 图片
                            'h3',                # front.html中的标题
                            'p',                 # front.html中的描述
                            '[class*="title"]',  # 包含title的类名
                            '[class*="cover"]'   # 包含cover的类名
                        ]
                        
                        for selector in clickable_selectors:
                            clickable_element = card.query_selector(selector)
                            if clickable_element and clickable_element.is_visible():
                                print(f"尝试点击卡片内的 {selector} 元素...")
                                clickable_element.click(timeout=5000)
                                click_success = True
                                break
                    except Exception as e:
                        print(f"点击卡片内元素失败: {e}")
                
                # 方式3: 使用JavaScript点击
                if not click_success:
                    try:
                        print(f"尝试使用JavaScript点击data-index={data_index}的卡片...")
                        self.page.evaluate("(element) => element.click()", card)
                        click_success = True
                    except Exception as e:
                        print(f"JavaScript点击失败: {e}")
                
                if click_success:
                    time.sleep(3)  # 等待页面响应
                    print(f"成功点击data-index={data_index}的卡片")
                    return True
                else:
                    print(f"所有点击方式都失败了")
                
            except Exception as e:
                print(f"点击data-index={data_index}的卡片失败: {e}")
                
                # 在第一次失败时进行调试
                if retry == 0:
                    print(f"开始调试data-index={data_index}的卡片问题...")
                    self.debug_page_structure(target_index=data_index)
                    self.check_page_loading_status()
                
                if "Element is not attached to the DOM" in str(e) or "element is not visible" in str(e) or "Timeout" in str(e):
                    print(f"DOM元素问题，尝试重新加载 (重试 {retry + 1}/{self.max_retries})")
                    
                    # 不重新加载页面，避免重置状态
                    print("跳过重新加载，直接重试")
                else:
                    time.sleep(3)
        
        return False
    
    def _try_force_load_strategies(self):
        """尝试强制加载策略"""
        strategies = [
            ("滚动到底部", lambda: self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")),
            ("大幅滚动", lambda: self.page.evaluate("window.scrollBy(0, 3000)")),
            ("触发懒加载", self._trigger_lazy_loading),
            ("模拟用户交互", self._simulate_user_interaction)
        ]
        
        initial_count = len(self.get_note_cards())
        
        for strategy_name, strategy_func in strategies:
            try:
                print(f"尝试策略: {strategy_name}")
                strategy_func()
                time.sleep(3)
                
                new_count = len(self.get_note_cards())
                if new_count > initial_count:
                    print(f"策略 '{strategy_name}' 成功，新增 {new_count - initial_count} 个卡片")
                    return True
                    
            except Exception as e:
                print(f"策略 '{strategy_name}' 失败: {e}")
        
        return False
    
    def _trigger_lazy_loading(self):
        """触发懒加载"""
        self.page.evaluate("""
            () => {
                // 触发所有可能的懒加载事件
                window.dispatchEvent(new Event('scroll'));
                window.dispatchEvent(new Event('resize'));
                
                // 查找并触发懒加载元素
                const lazyElements = document.querySelectorAll('[loading="lazy"], [data-lazy]');
                lazyElements.forEach(el => {
                    el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                });
            }
        """)
    
    def _simulate_user_interaction(self):
        """模拟用户交互"""
        self.page.evaluate("""
            () => {
                // 触发各种可能的事件
                const events = ['scroll', 'resize', 'focus', 'mousemove'];
                events.forEach(eventType => {
                    window.dispatchEvent(new Event(eventType));
                });
            }
        """)
    
    def crawl_continuously(self, max_notes=None, start_from=1):
        """
        连续爬取笔记（支持动态加载和断点续传）
        
        Args:
            max_notes (int): 最大爬取数量，None表示持续爬取
            start_from (int): 从第几个卡片开始爬取
        """
        print("开始连续爬取笔记...")
        
        # 获取已爬取的卡片索引
        crawled_indices = self.get_crawled_indices()
        print(f"已爬取的卡片: {sorted(crawled_indices)}")
        
        consecutive_failures = 0
        max_consecutive_failures = 10
        last_processed_count = 0
        no_progress_rounds = 0
        max_no_progress_rounds = 3
        
        while True:
            # 检查是否达到最大数量
            if max_notes and len(self.crawled_data) >= max_notes:
                print(f"已达到最大爬取数量: {max_notes}")
                break
            
            # 获取当前所有可用的data-index
            available_indices = self.get_all_data_indices()
            crawled_indices = self.get_crawled_indices()  # 重新获取已爬取的索引
            
            print(f"\n当前页面data-index: {sorted(available_indices)} (共{len(available_indices)}个)")
            print(f"已爬取data-index: {sorted(crawled_indices)} (共{len(crawled_indices)}个)")
            
            # 找到未处理的data-index（不按顺序，随机处理）
            unprocessed_indices = available_indices - crawled_indices
            
            if not unprocessed_indices:
                print("当前页面没有未处理的卡片，尝试加载更多...")
                
                # 记录加载前的data-index数量
                before_count = len(available_indices)
                
                # 尝试加载更多卡片
                self.smart_scroll_and_load()
                
                # 检查加载后的data-index
                after_indices = self.get_all_data_indices()
                after_count = len(after_indices)
                
                print(f"加载前: {before_count}个，加载后: {after_count}个")
                
                if after_count > before_count:
                    print(f"成功加载新卡片，新增 {after_count - before_count} 个")
                    continue
                else:
                    no_progress_rounds += 1
                    print(f"未能加载到新卡片 (第{no_progress_rounds}轮)")
                    
                    if no_progress_rounds >= max_no_progress_rounds:
                        print("多轮尝试后仍无新卡片，可能已到达页面底部")
                        break
                    continue
            
            # 重置无进展计数
            no_progress_rounds = 0
            
            # 处理未爬取的卡片（不按顺序，提高效率）
            processed_in_this_round = 0
            unprocessed_list = list(unprocessed_indices)
            
            print(f"\n开始处理 {len(unprocessed_list)} 个未处理的卡片...")
            
            for current_index in unprocessed_list:
                # 检查是否达到最大数量
                if max_notes and len(self.crawled_data) >= max_notes:
                    print(f"已达到最大爬取数量: {max_notes}")
                    return
                
                print(f"\n--- 处理data-index {current_index} ---")
                processed_in_this_round += 1
            
                try:
                    # 智能点击卡片
                    if not self.smart_click_card(current_index, after_scroll=True):
                        print(f"✗ data-index {current_index} 点击失败")
                        consecutive_failures += 1
                        
                        if consecutive_failures >= max_consecutive_failures:
                            print(f"连续失败 {max_consecutive_failures} 次，停止爬取")
                            return
                        continue
                    
                    # 提取信息
                    note_info = self.extract_note_info()
                    note_info['index'] = current_index
                    
                    if note_info['title'] or note_info['desc'] or note_info['images']:
                        self.crawled_data.append(note_info)
                        print(f"✓ 成功提取data-index {current_index} 的笔记")
                        consecutive_failures = 0
                        
                        # 检查是否有2024年之前的笔记，如果有则停止爬取
                        if self.check_crawl_time_before_2024():
                            print(f"🛑 检测到2024年之前的笔记，停止爬取")
                            return
                    else:
                        print(f"✗ data-index {current_index} 的笔记信息为空")
                    
                    # 关闭弹框
                    self.close_modal()
                    
                    # 实时保存结果
                    self.save_results()
                    
                    time.sleep(1)  # 减少等待时间
                    
                except Exception as e:
                    print(f"处理data-index {current_index} 时出错: {e}")
                    self.close_modal()
                    consecutive_failures += 1
                    continue
            
            # 检查处理进度
            current_count = len(self.crawled_data)
            if current_count == last_processed_count:
                print(f"本轮未成功处理任何卡片")
            else:
                print(f"本轮成功处理了 {current_count - last_processed_count} 个卡片")
                last_processed_count = current_count
        
        print(f"\n爬取完成！共获取 {len(self.crawled_data)} 个有效笔记")
        self.save_results()
    
    def close(self):
        """
        关闭爬虫
        """
        try:
            # 关闭requests会话
            if hasattr(self, 'session') and self.session:
                self.session.close()
                print("HTTP会话已关闭")
            
            # 输出下载统计信息
            if hasattr(self, 'download_stats'):
                stats = self.download_stats
                print(f"\n=== 图片下载统计 ===")
                print(f"总计: {stats['total']} 张")
                print(f"成功: {stats['success']} 张")
                print(f"跳过: {stats['skipped']} 张")
                print(f"失败: {stats['failed']} 张")
                if stats['total'] > 0:
                    success_rate = (stats['success'] + stats['skipped']) / stats['total'] * 100
                    print(f"成功率: {success_rate:.1f}%")
            
            # 关闭浏览器
            if self.playwright_config:
                self.playwright_config.cleanup_sync_browser()
            
            self.logger.info("爬虫已关闭")
            print("🔒 爬虫已关闭")
            
        except Exception as e:
            crawler_error = self.error_handler.handle_error(e, "关闭爬虫")
            self.logger.error("关闭爬虫时出错", error=crawler_error)
            print(f"❌ 关闭爬虫时出错: {crawler_error}")

def main():
    """
    主函数
    """
    print("=== 小红书智能爬虫 ===")
    print("功能特色:")
    print("1. 动态加载 - 自动滑动加载更多内容")
    print("2. 智能定位 - 根据索引精确定位卡片")
    print("3. 实时保存 - 每爬取一个立即保存")
    print("4. 断点续传 - 自动跳过已爬取内容")
    print("5. URL标识 - 同一URL使用同一结果文件")
    print()
    
    # 目标URL
    target_url = input("请输入目标URL: ").strip()
    if not target_url:
        target_url = "https://www.xiaohongshu.com/user/profile/5c3ea26d000000000501bddb?xsec_token=ABbeT3r2esYwvxutCj6M0KNjK2VijWlxAr2shN0oTNG4M%3D&xsec_source=pc_search"
    
    # 创建爬虫实例
    crawler = XiaohongshuSmartCrawler()
    
    try:
        # 启动爬虫
        crawler.start_crawler(target_url, headless=False)
        
        # 等待用户确认
        print("\n请在浏览器中:")
        print("1. 完成登录（如果需要）")
        print("2. 确认页面加载完成")
        print("3. 准备好后按回车键开始爬取...")
        input()
        
        # 获取爬取参数
        try:
            max_notes_input = input("请输入要爬取的笔记数量（直接回车表示持续爬取）: ")
            max_notes = int(max_notes_input) if max_notes_input.strip() else None
        except ValueError:
            max_notes = None
        
        # 分析已有数据，建议起始位置
        crawled_indices = crawler.get_crawled_indices()
        if crawled_indices:
            suggested_start = max(crawled_indices) + 1
            print(f"建议从第 {suggested_start} 个卡片开始")
        else:
            suggested_start = 1
        
        try:
            start_input = input(f"从第几个卡片开始爬取（直接回车默认从第{suggested_start}个开始）: ")
            start_from = int(start_input) if start_input.strip() else suggested_start
        except ValueError:
            start_from = suggested_start
        
        print(f"\n开始爬取配置:")
        print(f"- 目标数量: {'持续爬取' if max_notes is None else max_notes}")
        print(f"- 起始位置: 第{start_from}个卡片")
        print(f"- 结果文件: {crawler.results_file}")
        print()
        
        # 开始爬取
        crawler.crawl_continuously(max_notes=max_notes, start_from=start_from)
        
        print(f"\n=== 爬取完成 ===")
        print(f"总共爬取: {len(crawler.crawled_data)} 个笔记")
        print(f"结果文件: {crawler.results_file}")
        
    except KeyboardInterrupt:
        print("\n用户中断爬取")
        crawler.save_results()
        print("进度已保存")
    except Exception as e:
        print(f"爬取过程中出错: {e}")
        crawler.save_results()
        print("进度已保存")
    finally:
        crawler.close()

if __name__ == "__main__":
    main()
