#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
整合爬虫系统
将热点新闻、天辰网热点榜单和豆包搜索功能整合到一个优化的类中
"""

import json
import logging
import os
import sys
import time
import subprocess
import asyncio
import queue
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from urllib.parse import urlencode
import schedule
import threading
import requests

script_dir = Path(__file__).resolve().parent
sys.path.append(str(script_dir.parent))

from bs4 import BeautifulSoup
from logger_config import LoggerConfig
from playwright_config import PlaywrightConfig

# 初始化日志配置
logger_config = LoggerConfig()
logger = logger_config.setup_logger()


class CrawlerConfig:
    """爬虫配置类"""
    
    # 热点新闻平台配置
    HOT_NEWS_PLATFORMS = {
        "douyin_hot.json": [
            {"url": "https://dabenshi.cn/other/api/hot.php", "params": {"type": "douyinhot"}},
            {"url": "https://api.cenguigui.cn/api/juhe/hotlist.php", "params": {"type": "douyin"}},
            {"url": "https://www.tianchenw.com/hot/douyin"},
        ],
        "zhihu_hot.json": [
            {"url": "https://api.cenguigui.cn/api/juhe/hotlist.php", "params": {"type": "zhihu"}},
            {"url": "https://www.tianchenw.com/hot/zhihu/"},
        ],
        "toutiao_hot.json": [
            {"url": "https://dabenshi.cn/other/api/hot.php", "params": {"type": "toutiaoHot"}},
            {"url": "https://www.tianchenw.com/hot/toutiao"},
        ],
        "weibo_hot.json": [
            {"url": "https://api.cenguigui.cn/api/juhe/hotlist.php", "params": {"type": "weibo"}},
            {"url": "https://www.tianchenw.com/hot/weibo"},
        ],
        "baidu_hot.json": [
            {"url": "https://dabenshi.cn/other/api/hot.php", "params": {"type": "baidu"}},
            {"url": "https://www.tianchenw.com/hot/baidu"},
            {"url": "https://api.cenguigui.cn/api/juhe/hotlist.php", "params": {"type": "baidu"}},
        ],
    }
    
    # URL配置
    TIANCHEN_HOT_URL = "https://www.tianchenw.com/hot"
    DOUBAO_SEARCH_URL = "https://www.doubao.com/chat/search"
    
    # 超时配置
    PAGE_LOAD_TIMEOUT = 30000
    WAIT_TIMEOUT = 5000
    SELECTOR_TIMEOUT = 10000
    REQUEST_TIMEOUT = 30
    
    # 请求间隔
    REQUEST_INTERVAL = 1
    TASK_INTERVAL = 2


class DataProcessor:
    """数据处理器"""
    
    @staticmethod
    def extract_json_from_pre_tag(html_content: str) -> Optional[Dict]:
        """从HTML的<pre>标签中提取JSON数据，或者直接解析JSON字符串"""
        # 尝试直接解析JSON
        try:
            # 清理可能存在的BOM或其他空白字符
            cleaned_content = html_content.strip()
            if cleaned_content.startswith('{') or cleaned_content.startswith('['):
                return json.loads(cleaned_content)
        except json.JSONDecodeError:
            pass # 继续尝试从HTML中提取
            
        try:
            soup = BeautifulSoup(html_content, "html.parser")
            pre_tag = soup.find("pre")
            
            if pre_tag:
                json_text = pre_tag.get_text()
                logger.info("成功找到 <pre> 标签并提取 JSON 数据")
                return json.loads(json_text)
            else:
                # 尝试查找是否包含JSON结构（以{开头）
                text = soup.get_text().strip()
                if (text.startswith('{') and text.endswith('}')) or (text.startswith('[') and text.endswith(']')):
                     try:
                        return json.loads(text)
                     except:
                        pass
                logger.warning("未找到 <pre> 标签且无法直接解析为JSON")
        except json.JSONDecodeError as e:
            logger.error(f"提取的内容不是有效的JSON格式: {e}")
        except Exception as e:
            logger.error(f"解析HTML时出错: {e}", exc_info=True)
        return None
    
    @staticmethod
    def extract_tianchen_hotlist(html_content: str) -> Dict[str, List[Dict]]:
        """提取天辰网热点榜单数据"""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            # 修复类型错误：使用正确的lambda函数签名
            hot_lists = soup.find_all('ul', id=lambda x: bool(x and isinstance(x, str) and x.endswith('-hot')))
            
            result = {}
            for ul in hot_lists:
                list_id = ul.get('id')
                platform_name = list_id.replace('-hot', '') if list_id else 'unknown'
                
                items = []
                for li in ul.find_all('li'):
                    link_elem = li.find('a')
                    if link_elem:
                        title = link_elem.get_text(strip=True)
                        href = link_elem.get('href', '')
                        
                        if title:
                            items.append({
                                'title': title,
                                'url': href
                            })
                
                if items:
                    result[platform_name] = items
            
            return result
        except Exception as e:
            logger.error(f"解析天辰网热点榜单失败: {e}", exc_info=True)
            return {}
    
    @staticmethod
    def extract_doubao_search_results(html_content: str) -> List[Dict]:
        """提取豆包搜索结果"""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            chat_items = soup.find_all("div", {"data-testid": "skill-page-search-item"})
            
            result = []
            for item in chat_items:
                try:
                    title = item.find("div", {"data-testid": "skill-page-search-item-title"})
                    desc = item.find("div", {"data-testid": "skill-page-search-item-desc"})
                    pic = item.find("img", {"data-testid": "skill-page-search-item-pic"})
                    pic_url = pic["src"] if pic else None
                    
                    if title and desc:
                        result.append({
                            "title": title.get_text(strip=True),
                            "desc": desc.get_text(strip=True),
                            "pic": pic_url,
                            "timestamp": datetime.now().isoformat()
                        })
                except Exception as e:
                    logger.warning(f"解析搜索项时出错: {e}")
                    continue
            
            return result
        except Exception as e:
            logger.error(f"解析豆包搜索结果失败: {e}", exc_info=True)
            return []


class FileManager:
    """文件管理器"""
    
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.data_dir = base_dir / "data"
        self.hot_news_dir = self.data_dir / "hot_news"
    
    def ensure_directories(self):
        """确保目录存在"""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.hot_news_dir.mkdir(parents=True, exist_ok=True)
    
    def clear_hot_news_files(self):
        """清理旧的热点新闻文件"""
        try:
            for item in self.hot_news_dir.iterdir():
                if item.is_file():
                    item.unlink()
            logger.info("已清理旧的热点新闻文件")
        except Exception as e:
            logger.error(f"清理热点新闻文件失败: {e}")
    
    def save_data(self, data: Any, filename: str, subfolder: str = "") -> bool:
        """保存数据到文件"""
        try:
            if subfolder:
                output_path = self.data_dir / subfolder / filename
            else:
                output_path = self.data_dir / filename
            
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            with open(output_path, "w", encoding="utf-8") as file:
                if isinstance(data, str):
                    file.write(data)
                else:
                    json.dump(data, file, ensure_ascii=False, indent=2)
            
            logger.info(f"数据已成功保存到 {output_path}")
            return True
        except Exception as e:
            logger.error(f"保存文件时出错: {e}", exc_info=True)
            return False
    
    def load_data(self, filename: str, subfolder: str = "") -> Optional[Dict]:
        """从文件加载数据"""
        try:
            if subfolder:
                file_path = self.data_dir / subfolder / filename
            else:
                file_path = self.data_dir / filename
            
            if file_path.exists():
                with open(file_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            return None
        except Exception as e:
            logger.error(f"加载文件失败: {e}")
            return None
    
    def merge_hot_news_files(self) -> Dict[str, List[Dict]]:
        """合并本地热点新闻JSON文件"""
        result = {}
        try:
            for file_path in self.hot_news_dir.glob("*.json"):
                file_name = file_path.stem
                logger.info(f"处理文件: {file_path}")
                
                with open(file_path, "r", encoding="utf-8") as f:
                    file_data = json.load(f)
                
                if "data" in file_data and isinstance(file_data["data"], list):
                    items = []
                    for item in file_data["data"]:
                        if "index" in item and "title" in item:
                            items.append({
                                "number": str(item["index"]),
                                "content": item["title"]
                            })
                    result[file_name] = items
                    logger.debug(f"已合并 {file_name} 数据: {len(items)} 条")
        except Exception as e:
            logger.error(f"合并热点新闻文件失败: {e}")
        
        return result


class WebCrawler:
    """网页爬虫核心类"""
    
    def __init__(self):
        self.playwright_config = None
        self.page = None
        self._thread_local = threading.local()
        self._lock = threading.Lock()
    
    def _get_thread_specific_browser(self):
        """获取线程特定的浏览器实例"""
        if not hasattr(self._thread_local, 'playwright_config'):
            with self._lock:
                if not hasattr(self._thread_local, 'playwright_config'):
                    logger.info(f"为线程 {threading.current_thread().name} 创建新的浏览器实例")
                    self._thread_local.playwright_config = PlaywrightConfig()
                    self._thread_local.playwright_config.initialize_browser()
                    self._thread_local.page = self._thread_local.playwright_config.get_default_page()
        
        return self._thread_local.playwright_config, self._thread_local.page
    
    def fetch_page_content_with_requests(self, url: str, params: Optional[Dict] = None) -> Optional[str]:
        """使用requests获取页面内容（用于简单API请求）"""
        try:
            if params:
                url += "?" + urlencode(params)
            
            logger.info(f"使用requests访问URL: {url}")
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            response = requests.get(url, headers=headers, timeout=CrawlerConfig.REQUEST_TIMEOUT)
            response.raise_for_status()
            
            logger.info("requests请求成功")
            return response.text
            
        except Exception as e:
            logger.error(f"requests请求失败: {e}")
            return None
    
    def fetch_page_content_with_playwright(self, url: str, params: Optional[Dict] = None) -> Optional[str]:
        """使用Playwright获取页面内容（用于复杂页面）"""
        try:
            if params:
                url += "?" + urlencode(params)
            
            # 获取线程特定的浏览器实例
            playwright_config, page = self._get_thread_specific_browser()
            
            if page is None:
                logger.error("无法获取页面实例")
                return None
            
            logger.info(f"使用Playwright访问URL: {url}")
            
            page.goto(url, wait_until="load", timeout=CrawlerConfig.PAGE_LOAD_TIMEOUT)
            page.wait_for_timeout(CrawlerConfig.WAIT_TIMEOUT)
            page.wait_for_selector("body", timeout=CrawlerConfig.SELECTOR_TIMEOUT)
            
            logger.info("Playwright页面加载成功")
            return page.content()
            
        except Exception as e:
            logger.error(f"Playwright获取页面失败: {e}", exc_info=True)
            return None
    
    def fetch_page_content(self, url: str, params: Optional[Dict] = None, use_playwright: bool = False) -> Optional[str]:
        """获取页面内容，优先使用requests，复杂页面使用Playwright"""
        if use_playwright:
            return self.fetch_page_content_with_playwright(url, params)
        else:
            # 先尝试requests
            content = self.fetch_page_content_with_requests(url, params)
            if content is None:
                logger.info("requests失败，尝试使用Playwright")
                return self.fetch_page_content_with_playwright(url, params)
            return content
    
    def cleanup(self):
        """清理资源"""
        if hasattr(self._thread_local, 'playwright_config'):
            try:
                self._thread_local.playwright_config.quit_browser()
            except Exception as e:
                logger.error(f"清理浏览器资源失败: {e}")


class IntegratedCrawler:
    """整合爬虫主类"""
    
    def __init__(self):
        self.script_dir = script_dir
        self.file_manager = FileManager(self.script_dir)
        self.web_crawler = WebCrawler()
        self.data_processor = DataProcessor()
        
        # 确保目录存在
        self.file_manager.ensure_directories()
    
    def crawl_hot_news_for_platform(self, platform_name: str, urls: List[Dict]) -> bool:
        """爬取指定平台的热点新闻"""
        logger.info(f"开始爬取 {platform_name}...")
        
        for url_config in urls:
            try:
                # 对于API请求，优先使用requests
                html_content = self.web_crawler.fetch_page_content(
                    url_config["url"], 
                    url_config.get("params"),
                    use_playwright=False
                )
                
                if html_content:
                    extracted_data = self.data_processor.extract_json_from_pre_tag(html_content)
                    
                    if (isinstance(extracted_data, dict) and 
                        "error" not in extracted_data and 
                        "data" in extracted_data):
                        
                        success = self.file_manager.save_data(
                            extracted_data, platform_name, "hot_news"
                        )
                        if success:
                            logger.info(f"成功爬取并保存 {platform_name}")
                            return True
                
                time.sleep(CrawlerConfig.REQUEST_INTERVAL)
            except Exception as e:
                logger.error(f"爬取 {platform_name} 失败: {e}")
                continue
        
        logger.warning(f"未能成功爬取 {platform_name}")
        return False
    
    def crawl_all_hot_news(self) -> Dict[str, str]:
        """爬取所有平台热点新闻"""
        logger.info("开始执行热点新闻爬取任务...")
        
        # 清理旧文件
        self.file_manager.clear_hot_news_files()
        
        results = {}
        for platform_name, urls in CrawlerConfig.HOT_NEWS_PLATFORMS.items():
            try:
                success = self.crawl_hot_news_for_platform(platform_name, urls)
                results[platform_name] = "success" if success else "failed"
                time.sleep(CrawlerConfig.REQUEST_INTERVAL)
            except Exception as e:
                logger.error(f"爬取 {platform_name} 异常: {e}")
                results[platform_name] = "error"
        
        logger.info("热点新闻爬取任务完成")
        return results
    
    def crawl_tianchen_hotlist(self) -> Optional[Dict]:
        """爬取天辰网热点榜单"""
        logger.info("开始执行天辰网热点榜单爬取任务...")
        
        try:
            # 对于复杂页面，使用Playwright
            html_content = self.web_crawler.fetch_page_content(
                CrawlerConfig.TIANCHEN_HOT_URL, 
                use_playwright=True
            )
            if not html_content:
                return None
            
            # 提取天辰网数据
            tianchen_data = self.data_processor.extract_tianchen_hotlist(html_content)
            
            # 合并本地热点新闻文件
            merged_data = self.file_manager.merge_hot_news_files()
            tianchen_data.update(merged_data)
            
            if tianchen_data:
                # 保存最新数据
                self.file_manager.save_data(tianchen_data, "tianchen_hotlist.json")
                
                # 处理历史数据归档
                self._archive_tianchen_data(tianchen_data)
                
                logger.info(f"成功爬取天辰网热点榜单，包含 {len(tianchen_data)} 个平台")
                return tianchen_data
            
        except Exception as e:
            logger.error(f"天辰网热点榜单爬取失败: {e}", exc_info=True)
        
        return None
    
    def crawl_doubao_search(self) -> Optional[List[Dict]]:
        """爬取豆包搜索结果"""
        logger.info("开始执行豆包搜索爬取任务...")
        
        try:
            # 对于复杂页面，使用Playwright
            html_content = self.web_crawler.fetch_page_content(
                CrawlerConfig.DOUBAO_SEARCH_URL, 
                use_playwright=True
            )
            if not html_content:
                return None
            
            search_results = self.data_processor.extract_doubao_search_results(html_content)
            
            if search_results:
                # 保存最新数据
                self.file_manager.save_data(search_results, "doubao_news_search.json")
                
                # 处理历史数据归档
                self._archive_doubao_data(search_results)
                
                logger.info(f"成功爬取豆包搜索结果，共 {len(search_results)} 条")
                return search_results
            else:
                logger.warning("未获取到任何豆包搜索数据")
        
        except Exception as e:
            logger.error(f"豆包搜索爬取失败: {e}", exc_info=True)
        
        return None
    
    def crawl_doubao_chat(self) -> Optional[Dict]:
        """使用DoubaoCrawler3爬取豆包聊天数据"""
        try:
            logger.info("开始使用DoubaoCrawler3爬取豆包聊天数据...")
            
            # 导入DoubaoCrawler类
            from doubao_crawler3 import DoubaoCrawler
            
            # 获取线程特定的浏览器实例
            playwright_config, page = self.web_crawler._get_thread_specific_browser()
            if not page:
                logger.error("无法获取页面实例")
                return None
            
            # 创建DoubaoCrawler实例
            crawler = DoubaoCrawler(page=page, target_url="https://www.doubao.com/chat/search")
            
            # 执行爬取
            result = crawler.run()
            
            if result.get("status") == "success":
                data = result.get("data", [])
                
                logger.info(f"豆包聊天爬取完成，获取 {len(data)} 个标签页数据")
                return {
                    "status": "success",
                    "data": data,
                    "count": len(data),
                    "timestamp": result.get("timestamp")
                }
            else:
                error_msg = result.get("message", "未知错误")
                logger.error(f"豆包聊天爬取失败: {error_msg}")
                return {
                    "status": "failed",
                    "error": error_msg,
                    "timestamp": datetime.now().isoformat()
                }
                
        except Exception as e:
            logger.error(f"豆包聊天爬取异常: {e}", exc_info=True)
            return {
                "status": "error",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
    
    def _archive_tianchen_data(self, data: Dict):
        """归档天辰网数据"""
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            all_data = self.file_manager.load_data("all_date_tianchen_hotlist.json") or {}
            
            if today not in all_data:
                # 读取旧数据
                last_data = self.file_manager.load_data("tianchen_hotlist.json") or {}
                all_data[today] = last_data
                
                # 保存归档数据
                self.file_manager.save_data(all_data, "all_date_tianchen_hotlist.json")
                
                # 保存旧数据备份
                self.file_manager.save_data(last_data, "last_tianchen_hotlist.json")
        except Exception as e:
            logger.error(f"归档天辰网数据失败: {e}")
    
    def _archive_doubao_data(self, data: List[Dict]):
        """归档豆包数据"""
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            all_data = self.file_manager.load_data("all_doubao_news_search.json") or {}
            
            if today not in all_data:
                # 读取旧数据
                last_data = self.file_manager.load_data("doubao_news_search.json") or []
                all_data[today] = last_data
                
                # 保存归档数据
                self.file_manager.save_data(all_data, "all_doubao_news_search.json")
                
                # 保存旧数据备份
                self.file_manager.save_data(last_data, "last_doubao_news_search.json")
        except Exception as e:
            logger.error(f"归档豆包数据失败: {e}")
    
    def run_integrated_crawl(self) -> Dict[str, Any]:
        """执行整合爬取任务"""
        logger.info("开始执行整合爬取任务...")
        
        results = {
            "status": "success",
            "timestamp": datetime.now().isoformat(),
            "tasks": {
                "hot_news": {"status": "pending", "data": None},
                "tianchen_hotlist": {"status": "pending", "data": None},
                "doubao_search": {"status": "pending", "data": None},
                "doubao_chat": {"status": "pending", "data": None}
            },
            "errors": [],
            "summary": {}
        }
        
        # 任务1: 热点新闻爬取
        try:
            logger.info("=" * 50)
            logger.info("第1步：执行热点新闻爬取")
            logger.info("=" * 50)
            
            hot_news_results = self.crawl_all_hot_news()
            results["tasks"]["hot_news"]["data"] = hot_news_results
            
            success_count = sum(1 for status in hot_news_results.values() if status == "success")
            total_count = len(hot_news_results)
            
            if success_count > 0:
                results["tasks"]["hot_news"]["status"] = "completed"
                results["summary"]["hot_news"] = f"成功爬取 {success_count}/{total_count} 个平台"
            else:
                results["tasks"]["hot_news"]["status"] = "failed"
                results["errors"].append("热点新闻爬取：所有平台都失败")
            
        except Exception as e:
            error_msg = f"热点新闻爬取异常: {e}"
            logger.error(error_msg, exc_info=True)
            results["tasks"]["hot_news"]["status"] = "error"
            results["errors"].append(error_msg)
        
        time.sleep(CrawlerConfig.TASK_INTERVAL)
        
        # 任务2: 天辰网热点榜单爬取
        try:
            logger.info("=" * 50)
            logger.info("第2步：执行天辰网热点榜单爬取")
            logger.info("=" * 50)
            
            tianchen_data = self.crawl_tianchen_hotlist()
            
            if tianchen_data:
                results["tasks"]["tianchen_hotlist"]["status"] = "completed"
                results["tasks"]["tianchen_hotlist"]["data"] = len(tianchen_data)
                results["summary"]["tianchen_hotlist"] = f"成功爬取 {len(tianchen_data)} 个平台的热点榜单"
            else:
                results["tasks"]["tianchen_hotlist"]["status"] = "failed"
                results["errors"].append("天辰网热点榜单爬取失败")
            
        except Exception as e:
            error_msg = f"天辰网热点榜单爬取异常: {e}"
            logger.error(error_msg, exc_info=True)
            results["tasks"]["tianchen_hotlist"]["status"] = "error"
            results["errors"].append(error_msg)
        
        time.sleep(CrawlerConfig.TASK_INTERVAL)
        
        # 任务3: 豆包搜索爬取
        try:
            logger.info("=" * 50)
            logger.info("第3步：执行豆包搜索爬取")
            logger.info("=" * 50)
            
            doubao_data = self.crawl_doubao_search()
            
            if doubao_data:
                results["tasks"]["doubao_search"]["status"] = "completed"
                results["tasks"]["doubao_search"]["data"] = len(doubao_data)
                results["summary"]["doubao_search"] = f"成功爬取 {len(doubao_data)} 条搜索结果"
            else:
                results["tasks"]["doubao_search"]["status"] = "failed"
                results["errors"].append("豆包搜索爬取失败")
            
        except Exception as e:
            error_msg = f"豆包搜索爬取异常: {e}"
            logger.error(error_msg, exc_info=True)
            results["tasks"]["doubao_search"]["status"] = "error"
            results["errors"].append(error_msg)
        
        time.sleep(CrawlerConfig.TASK_INTERVAL)
        
        # 任务4: 豆包聊天爬取
        try:
            logger.info("=" * 50)
            logger.info("第4步：执行豆包聊天爬取")
            logger.info("=" * 50)
            
            doubao_chat_result = self.crawl_doubao_chat()
            
            if doubao_chat_result and doubao_chat_result.get("status") == "success":
                results["tasks"]["doubao_chat"]["status"] = "completed"
                results["tasks"]["doubao_chat"]["data"] = doubao_chat_result.get("count", 0)
                results["summary"]["doubao_chat"] = f"成功爬取 {doubao_chat_result.get('count', 0)} 个标签页数据"
            else:
                results["tasks"]["doubao_chat"]["status"] = "failed"
                error_msg = doubao_chat_result.get("error", "豆包聊天爬取失败") if doubao_chat_result else "豆包聊天爬取失败"
                results["errors"].append(error_msg)
            
        except Exception as e:
            error_msg = f"豆包聊天爬取异常: {e}"
            logger.error(error_msg, exc_info=True)
            results["tasks"]["doubao_chat"]["status"] = "error"
            results["errors"].append(error_msg)
        
        # 确定整体状态
        completed_tasks = sum(1 for task in results["tasks"].values() 
                            if task["status"] == "completed")
        total_tasks = len(results["tasks"])
        
        if completed_tasks == total_tasks:
            results["status"] = "success"
        elif completed_tasks > 0:
            results["status"] = "partial_success"
        else:
            results["status"] = "failed"
        
        # 生成总结
        results["summary"]["overall"] = f"完成 {completed_tasks}/{total_tasks} 个爬取任务"
        
        logger.info("=" * 50)
        logger.info(f"整合爬取任务执行完成，状态: {results['status']}")
        logger.info(f"总结: {results['summary']['overall']}")
        if results["errors"]:
            logger.warning(f"遇到 {len(results['errors'])} 个错误")
        logger.info("=" * 50)
        
        return results
    
    def cleanup(self):
        """清理资源"""
        self.web_crawler.cleanup()


def run_additional_scripts():
    """依次执行额外的脚本"""
    scripts = [
        "obtain_daily_data2.py",
        "obtain_daily_doubao_data4.py", 
        "obtain_daily_doubao_data3.py"
    ]
    
    results = []
    for script in scripts:
        try:
            script_path = script_dir / script
            logger.info(f"开始执行脚本: {script}")
            
            # 使用subprocess执行脚本
            result = subprocess.run(
                [sys.executable, str(script_path)],
                cwd=str(script_dir),
                capture_output=True,
                text=True,
                timeout=60000  
            )
            
            if result.returncode == 0:
                logger.info(f"脚本 {script} 执行成功")
                results.append({"script": script, "status": "success", "output": result.stdout})
            else:
                logger.error(f"脚本 {script} 执行失败，返回码: {result.returncode}")
                logger.error(f"错误输出: {result.stderr}")
                results.append({"script": script, "status": "failed", "error": result.stderr})
                
        except subprocess.TimeoutExpired:
            logger.error(f"脚本 {script} 执行超时")
            results.append({"script": script, "status": "timeout", "error": "执行超时"})
        except Exception as e:
            logger.error(f"执行脚本 {script} 时发生异常: {e}")
            results.append({"script": script, "status": "error", "error": str(e)})
    
    return results


def run_integrated_crawler() -> Dict[str, Any]:
    """运行整合爬虫的主函数"""
    crawler = None
    try:
        # 执行主爬虫任务
        crawler = IntegratedCrawler()
        main_result = crawler.run_integrated_crawl()
        
        # 执行额外的脚本
        logger.info("主爬虫任务完成，开始执行额外脚本...")
        additional_results = run_additional_scripts()
        
        # 合并结果
        main_result["additional_scripts"] = additional_results
        
        # 更新总体状态
        failed_scripts = [r for r in additional_results if r["status"] != "success"]
        if failed_scripts:
            if main_result["status"] == "success":
                main_result["status"] = "partial_success"
            main_result["errors"].extend([f"脚本 {r['script']} 执行失败: {r.get('error', '未知错误')}" for r in failed_scripts])
        
        logger.info("所有任务执行完成")
        return main_result
        
    except Exception as e:
        logger.error(f"整合爬虫运行失败: {e}", exc_info=True)
        return {
            "status": "failed",
            "error": str(e),
            "timestamp": datetime.now().isoformat(),
            "tasks": {},
            "errors": [f"系统错误: {e}"],
            "summary": {"overall": "系统初始化失败"}
        }
    finally:
        # 确保清理资源
        if crawler:
            try:
                crawler.cleanup()
            except Exception as e:
                logger.error(f"清理爬虫资源失败: {e}")


class CrawlerScheduler:
    """爬虫调度器类"""
    
    def __init__(self):
        self.is_running = False
        self._scheduler_thread = None
        logger.info("爬虫调度器初始化完成")
    
    def run_crawler_task(self):
        """执行爬虫任务"""
        try:
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            logger.info(f"开始执行定时爬虫任务 - {current_time}")
            
            # 执行整合爬虫
            result = run_integrated_crawler()
            
            # 记录执行结果
            status = result.get("status", "unknown")
            summary = result.get("summary", {}).get("overall", "无总结信息")
            
            if status == "success":
                logger.info(f"定时爬虫任务执行成功 - {summary}")
            elif status == "partial_success":
                logger.warning(f"定时爬虫任务部分成功 - {summary}")
                if result.get("errors"):
                    logger.warning(f"遇到错误: {result['errors']}")
            else:
                logger.error(f"定时爬虫任务执行失败 - {summary}")
                if result.get("errors"):
                    logger.error(f"错误详情: {result['errors']}")
            
            logger.info(f"定时爬虫任务完成 - {current_time}")
            
        except Exception as e:
            logger.error(f"定时爬虫任务执行异常: {e}", exc_info=True)
    
    def setup_schedule(self):
        """设置定时任务"""
        # 每天早上7点执行
        schedule.every().day.at("07:00").do(self.run_crawler_task)
        
        # 每天晚上8点执行
        schedule.every().day.at("20:00").do(self.run_crawler_task)
        
        logger.info("定时任务已设置：每天07:00和20:00执行爬虫任务")
    
    def start(self):
        """启动调度器"""
        # 检测是否在asyncio事件循环中
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                logger.warning("检测到正在运行的asyncio循环，将在新线程中启动调度器")
                self._scheduler_thread = self._start_in_thread()
                return
        except RuntimeError:
            # 没有运行的事件循环，可以正常启动
            pass
        
        self._start_scheduler()
    
    def _start_in_thread(self):
        """在新线程中启动调度器"""
        def run_scheduler():
            self._start_scheduler()
        
        scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
        scheduler_thread.start()
        logger.info("调度器已在后台线程中启动")
        return scheduler_thread
    
    def _start_scheduler(self):
        """实际启动调度器的方法"""
        self.is_running = True
        self.setup_schedule()
        
        logger.info("爬虫调度器已启动，等待执行定时任务...")
        logger.info("下次执行时间:")
        
        # 显示下次执行时间
        jobs = schedule.get_jobs()
        for job in jobs:
            logger.info(f"  - {job.next_run}")
        
        try:
            while self.is_running:
                schedule.run_pending()
                time.sleep(60)  # 每分钟检查一次
        except KeyboardInterrupt:
            logger.info("收到中断信号，正在停止调度器...")
            self.stop()
    
    def stop(self):
        """停止调度器"""
        self.is_running = False
        schedule.clear()
        
        # 等待调度器线程结束
        if self._scheduler_thread and self._scheduler_thread.is_alive():
            logger.info("等待调度器线程结束...")
            self._scheduler_thread.join(timeout=10)
            if self._scheduler_thread.is_alive():
                logger.warning("调度器线程未能在超时时间内结束")
        
        logger.info("爬虫调度器已停止")
    
    def run_once(self):
        """立即执行一次爬虫任务（用于测试）"""
        logger.info("手动执行爬虫任务...")
        self.run_crawler_task()


def start_scheduler():
    """启动定时调度器"""
    scheduler = CrawlerScheduler()
    
    try:
        # 启动调度器
        scheduler.start()
    except Exception as e:
        logger.error(f"调度器启动失败: {e}", exc_info=True)
    finally:
        scheduler.stop()


if __name__ == "__main__":
    # 检查命令行参数
    if len(sys.argv) > 1 and sys.argv[1] == "--once":
        # 执行一次爬取任务
        logger.info("执行单次爬虫任务...")
        result = run_integrated_crawler()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        # 启动定时任务
        logger.info("启动定时爬虫调度器...")
        start_scheduler()