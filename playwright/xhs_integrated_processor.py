#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
XHS集成处理器 - 一站式小红书内容处理工具
功能：
1. 全流程处理results中所有URL（爬取→笔记生成→关键词生成→embedding）
2. 输入单个URL进行全流程处理
"""

import json
import os
import sys
import time
import threading
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple
import re

# 添加路径
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.append(project_root)
sys.path.append(os.path.join(project_root, "func"))
sys.path.append(os.path.join(project_root, "func", "playwright", "web_server"))
sys.path.append(os.path.join(project_root, "func", "playwright", "web_server", "src"))

# 导入处理模块
from xhs.crawler import XiaohongshuSmartCrawler
from xhs.image_service import ImageService
from xhs.keyword_service import KeywordService
from xhs.embedding_service import EmbeddingSearchService
from xhs.blogger_discovery import XiaohongshuBloggerDiscovery
from api.token_manager import TokenManager


class XHSIntegratedProcessor:
    """
    XHS集成处理器 - 统一处理小红书内容的完整流程
    """
    
    def __init__(self):
        """
        初始化集成处理器
        """
        # 设置results目录路径（指向xhs/xhs/results目录）
        self.results_dir = Path(__file__).parent / "xhs" / "xhs" / "results"
        self.results_dir.mkdir(parents=True, exist_ok=True)
        
        # 初始化服务
        self.crawler = XiaohongshuSmartCrawler()
        self.image_service = ImageService()
        self.keyword_service = KeywordService()
        self.embedding_service = EmbeddingSearchService()
        self.token_manager = TokenManager()
        # 初始化 LLM Client，用于 token 状态查询
        from api.llm_client import LLMApiClient
        self.llm_client = LLMApiClient()
        
        print(f"🚀 XHS集成处理器已初始化")
        print(f"📁 结果目录: {self.results_dir}")
        self._show_token_status()
    
    def get_all_result_files(self) -> List[Path]:
        """
        获取results目录下的所有JSON文件
        
        Returns:
            List[Path]: JSON文件路径列表
        """
        json_files = list(self.results_dir.glob("*.json"))
        json_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        return json_files
    
    def extract_urls_from_file(self, json_file: Path) -> List[str]:
        """
        从JSON文件中提取所有小红书URL
        
        Args:
            json_file: JSON文件路径
            
        Returns:
            List[str]: URL列表
        """
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            urls = []
            if isinstance(data, dict):
                # 检查crawl_info中的target_url
                crawl_info = data.get('crawl_info', {})
                if isinstance(crawl_info, dict) and 'target_url' in crawl_info:
                    target_url = crawl_info['target_url']
                    if isinstance(target_url, str) and ('xiaohongshu.com' in target_url or 'xhslink.com' in target_url):
                        urls.append(target_url)
                
                # 兼容旧格式：检查直接的url字段
                if 'url' in data:
                    url = data['url']
                    if isinstance(url, str) and ('xiaohongshu.com' in url or 'xhslink.com' in url):
                        urls.append(url)
                
                # 检查notes字段中的url
                if 'notes' in data and isinstance(data['notes'], list):
                    for note in data['notes']:
                        if isinstance(note, dict) and 'url' in note:
                            url = note['url']
                            if isinstance(url, str) and ('xiaohongshu.com' in url or 'xhslink.com' in url):
                                urls.append(url)
            elif isinstance(data, list):
                # 兼容列表格式
                for item in data:
                    if isinstance(item, dict) and 'url' in item:
                        url = item['url']
                        if isinstance(url, str) and ('xiaohongshu.com' in url or 'xhslink.com' in url):
                            urls.append(url)
            
            # 去重并返回
            return list(set(urls))
            
        except Exception as e:
            print(f"❌ 提取URL失败 {json_file.name}: {e}")
            return []
    
    def _crawl_in_thread(self, url: str) -> Optional[str]:
        """
        在子线程中执行爬虫操作，避免 asyncio 循环冲突
        
        Args:
            url: 要爬取的URL
            
        Returns:
            Optional[str]: 结果文件路径，失败返回None
        """
        try:
            # 创建新的爬虫实例（避免线程间共享）
            crawler = XiaohongshuSmartCrawler()
            
            # 使用爬虫爬取
            crawler.start_crawler(url, headless=True)
            
            # 执行智能滑动和加载
            crawler.smart_scroll_and_load()
            
            # 保存结果
            crawler.save_results()
            
            # 获取结果文件路径
            result_file = crawler.results_file
            
            # 清理浏览器资源
            try:
                if hasattr(crawler, 'playwright_config') and crawler.playwright_config:
                    crawler.playwright_config.cleanup()
            except Exception as cleanup_error:
                print(f"⚠️ 清理资源时出错: {cleanup_error}")
            
            return result_file if result_file and Path(result_file).exists() else None
            
        except Exception as e:
            print(f"❌ 子线程爬取异常: {e}")
            return None
    
    def crawl_url(self, url: str, max_retries: int = 2) -> Optional[str]:
        """
        爬取单个URL
        
        Args:
            url: 要爬取的URL
            max_retries: 最大重试次数
            
        Returns:
            Optional[str]: 爬取结果文件路径，失败返回None
        """
        for attempt in range(max_retries + 1):
            try:
                print(f"🔍 正在爬取URL (尝试 {attempt + 1}/{max_retries + 1}): {url}")
                
                # 在子线程中运行爬虫，避免 asyncio 循环冲突
                result_container = [None]
                exception_container = [None]
                
                def thread_target():
                    try:
                        result_container[0] = self._crawl_in_thread(url)
                    except Exception as e:
                        exception_container[0] = e
                
                # 创建并启动子线程
                thread = threading.Thread(target=thread_target, daemon=True)
                thread.start()
                thread.join(timeout=300)  # 5分钟超时
                
                # 检查线程是否超时
                if thread.is_alive():
                    print(f"⚠️ 爬取超时，线程仍在运行")
                    return None
                
                # 检查是否有异常
                if exception_container[0]:
                    raise exception_container[0]
                
                # 检查结果
                result_file = result_container[0]
                if result_file and Path(result_file).exists():
                    print(f"✅ 爬取成功: {result_file}")
                    return result_file
                else:
                    print(f"⚠️ 爬取失败，未生成结果文件")
                    
            except Exception as e:
                print(f"❌ 爬取异常 (尝试 {attempt + 1}): {e}")
                
            if attempt < max_retries:
                wait_time = (attempt + 1) * 2
                print(f"⏳ 等待 {wait_time} 秒后重试...")
                time.sleep(wait_time)
        
        print(f"❌ 爬取最终失败: {url}")
        return None
    
    def process_images(self, json_file_path: str, max_notes: Optional[int] = None) -> bool:
        """
        处理JSON文件中的图片
        
        Args:
            json_file_path: JSON文件路径
            max_notes: 最大处理笔记数量
            
        Returns:
            bool: 处理是否成功
        """
        try:
            print(f"🖼️ 开始图片处理: {Path(json_file_path).name}")
            result = self.image_service.process_images_in_json(
                json_file_path, 
                max_notes=max_notes
            )
            if result:
                print(f"✅ 图片处理完成")
                return True
            else:
                print(f"⚠️ 图片处理未完成")
                return False
        except Exception as e:
            print(f"❌ 图片处理失败: {e}")
            return False
    
    def generate_keywords(self, json_file_path: str) -> bool:
        """
        生成关键词
        
        Args:
            json_file_path: JSON文件路径
            
        Returns:
            bool: 生成是否成功
        """
        try:
            print(f"🔑 开始关键词生成: {Path(json_file_path).name}")
            result = self.keyword_service.generate_keywords_for_json(json_file_path)
            if result:
                print(f"✅ 关键词生成完成")
                return True
            else:
                print(f"⚠️ 关键词生成未完成")
                return False
        except Exception as e:
            print(f"❌ 关键词生成失败: {e}")
            return False
    
    def generate_embeddings(self, json_file_path: str) -> bool:
        """
        生成向量嵌入
        
        Args:
            json_file_path: JSON文件路径
            
        Returns:
            bool: 生成是否成功
        """
        try:
            print(f"🧮 开始向量生成: {Path(json_file_path).name}")
            result = self.embedding_service.generate_embeddings_for_json(json_file_path)
            if result:
                print(f"✅ 向量生成完成")
                return True
            else:
                print(f"⚠️ 向量生成未完成")
                return False
        except Exception as e:
            print(f"❌ 向量生成失败: {e}")
            return False
    
    def check_processing_status(self, json_file_path: str, strict: bool = False) -> Dict[str, bool]:
        """
        检查JSON文件中各个处理步骤的完成状态
        
        Args:
            json_file_path: JSON文件路径
            strict: 是否使用严格模式（要求100%完成）
            
        Returns:
            Dict[str, bool]: 各步骤完成状态
        """
        try:
            with open(json_file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            print(f"❌ 读取JSON文件失败: {e}")
            return {}
        
        notes = data.get('notes', [])
        if not notes:
            return {}
        
        # 统计各步骤完成情况
        status = {
            'crawl': len(notes) > 0,  # 有笔记就说明爬取成功
            'images': False,          # 图片处理（包含pic_results, pic_content, new_note）
            'keywords': False,        # 关键词生成
            'embeddings': False       # 向量嵌入
        }
        
        # 检查每个笔记的处理状态
        pic_results_count = 0
        pic_content_count = 0
        new_note_count = 0
        keywords_count = 0
        embeddings_count = 0
        
        # 统计有图片的笔记数量（需要图片处理的笔记）
        notes_with_images = 0
        
        for note in notes:
            # 检查是否有图片需要处理（本地图片或网络图片）
            has_local_images = bool(note.get('local_images'))
            has_network_images = bool(note.get('images'))
            has_any_images = has_local_images or has_network_images
            
            if has_any_images:
                notes_with_images += 1
                
            # 统计各字段完成情况
            if note.get('pic_results'):
                pic_results_count += 1
            if note.get('pic_content'):
                pic_content_count += 1
            if note.get('new_note'):
                new_note_count += 1
            if note.get('keywords'):
                keywords_count += 1
            if note.get('embedding') or note.get('embeddings'):
                embeddings_count += 1
        
        # 计算阈值
        total_notes = len(notes)
        # 对于图片处理，只考虑有图片的笔记
        if strict:
            image_threshold = notes_with_images
        else:
            image_threshold = max(1, notes_with_images * 0.8) if notes_with_images > 0 else 0
        
        # 对于关键词和嵌入，使用更合理的判断逻辑：
        # 1. 如果总笔记数 <= 5，要求100%完成
        # 2. 如果总笔记数 > 5，要求至少80%完成，但至少要有5个完成
        if strict:
            general_threshold = total_notes
        elif total_notes <= 5:
            general_threshold = total_notes
        else:
            general_threshold = max(5, int(total_notes * 0.8))
        
        # 图片处理：只有当有图片的笔记都完成了pic_results, pic_content, new_note时才算完成
        if notes_with_images == 0:
            status['images'] = True  # 没有图片需要处理，认为已完成
        else:
            status['images'] = (pic_results_count >= image_threshold and 
                               pic_content_count >= image_threshold and 
                               new_note_count >= image_threshold)
        
        # 关键词和嵌入的判断：使用更智能的逻辑
        # 1. 如果没有任何笔记有关键词，认为未完成
        # 2. 如果有关键词但数量不足阈值，检查是否至少有一定比例完成
        # 3. 对于小数据集，降低要求
        
        # 计算关键词阈值
        if strict:
            keywords_threshold = total_notes
        elif total_notes <= 10:
            keywords_threshold = max(1, int(total_notes * 0.5))
        else:
            keywords_threshold = general_threshold
            
        # 计算嵌入阈值
        if strict:
            embeddings_threshold = total_notes
        elif total_notes <= 10:
            embeddings_threshold = max(1, int(total_notes * 0.5))
        else:
            embeddings_threshold = general_threshold
        
        # 判断关键词完成状态
        if keywords_count == 0:
            status['keywords'] = False
        else:
            status['keywords'] = keywords_count >= keywords_threshold
            
        # 判断嵌入完成状态
        if embeddings_count == 0:
            status['embeddings'] = False
        else:
            status['embeddings'] = embeddings_count >= embeddings_threshold
            
        # 添加调试信息（可选，在需要时取消注释）
        # print(f"📊 状态检查详情: 总笔记={total_notes}, 关键词={keywords_count}/{keywords_threshold}, 嵌入={embeddings_count}/{embeddings_threshold}")
        # print(f"📊 图片笔记={notes_with_images}, 图片处理={pic_results_count}/{pic_content_count}/{new_note_count}")
        
        return status
    
    def process_existing_json_file(self, json_file_path: str, max_notes: Optional[int] = None, force_reprocess: bool = False) -> Dict[str, bool]:
        """
        处理现有JSON文件中的所有笔记，按正确顺序执行全流程处理
        
        执行顺序：
        1. 检查处理状态
        2. 调用pic理解相关的服务，生成pic_results
        3. 总结pic_content
        4. 生成new_note
        5. 生成keywords
        6. 生成两个embedding
        
        Args:
            json_file_path: JSON文件路径
            max_notes: 最大处理笔记数量，None表示处理全部
            force_reprocess: 是否强制重新处理所有步骤
            
        Returns:
            Dict[str, bool]: 各步骤处理结果
        """
        print(f"\n🚀 开始处理现有JSON文件: {Path(json_file_path).name}")
        print("=" * 80)
        
        results = {
            'crawl': True,  # 文件已存在，认为爬取已完成
            'images': False,
            'keywords': False,
            'embeddings': False
        }
        
        # 检查文件是否存在
        if not Path(json_file_path).exists():
            print(f"❌ 文件不存在: {json_file_path}")
            results['crawl'] = False
            return results
        
        # 检查当前处理状态
        status = {}
        if not force_reprocess:
            print("\n🔍 检查当前处理状态...")
            status = self.check_processing_status(json_file_path)
            print(f"📊 处理状态检查结果:")
            print(f"  📝 爬取: {'✅' if status.get('crawl') else '❌'}")
            print(f"  🖼️ 图片处理: {'✅' if status.get('images') else '❌'}")
            print(f"  🔑 关键词: {'✅' if status.get('keywords') else '❌'}")
            print(f"  🧮 向量嵌入: {'✅' if status.get('embeddings') else '❌'}")
        
        # 步骤2-4: 图片处理（包含pic理解、pic_content总结、new_note生成）
        print("\n🖼️ 步骤2-4: 图片处理（pic理解 → pic_content总结 → new_note生成）")
        if force_reprocess or not status.get('images'):
            results['images'] = self.process_images(json_file_path, max_notes=max_notes)
            if results['images']:
                print(f"✅ 图片处理完成（包含pic理解、内容总结、新笔记生成）")
            else:
                print(f"⚠️ 图片处理未完全完成")
        else:
            print(f"✅ 图片处理已完成，跳过")
            results['images'] = True
        
        # 步骤5: 关键词生成
        print("\n🔑 步骤5: 生成keywords")
        
        # 检查实际的关键词完成情况
        current_status = self.check_processing_status(json_file_path, strict=True)
        actual_keywords_complete = current_status.get('keywords', False)
        
        if force_reprocess or not status.get('keywords') or not actual_keywords_complete:
            print(f"🔄 开始关键词生成 (force_reprocess={force_reprocess}, status_check={status.get('keywords')}, actual_complete={actual_keywords_complete})")
            results['keywords'] = self.generate_keywords(json_file_path)
            if results['keywords']:
                print(f"✅ 关键词生成完成")
            else:
                print(f"⚠️ 关键词生成未完成")
        else:
            print(f"✅ 关键词已生成，跳过")
            results['keywords'] = True
        
        # 步骤6: 向量嵌入生成
        print("\n🧮 步骤6: 生成两个embedding")
        
        # 重新检查实际的嵌入完成情况
        current_status = self.check_processing_status(json_file_path, strict=True)
        actual_embeddings_complete = current_status.get('embeddings', False)
        
        if force_reprocess or not status.get('embeddings') or not actual_embeddings_complete:
            print(f"🔄 开始向量嵌入生成 (force_reprocess={force_reprocess}, status_check={status.get('embeddings')}, actual_complete={actual_embeddings_complete})")
            results['embeddings'] = self.generate_embeddings(json_file_path)
            if results['embeddings']:
                print(f"✅ 向量嵌入生成完成")
            else:
                print(f"⚠️ 向量嵌入生成未完成")
        else:
            print(f"✅ 向量嵌入已生成，跳过")
            results['embeddings'] = True
        
        # 最终状态检查
        print("\n🔍 最终状态检查...")
        final_status = self.check_processing_status(json_file_path)
        
        # 显示最终结果
        print("\n" + "=" * 80)
        print(f"📊 JSON文件处理完成: {Path(json_file_path).name}")
        print(f"📝 爬取: {'✅ 成功' if results['crawl'] else '❌ 失败'}")
        print(f"🖼️ 图片处理: {'✅ 成功' if results['images'] else '❌ 失败'}")
        print(f"🔑 关键词: {'✅ 成功' if results['keywords'] else '❌ 失败'}")
        print(f"🧮 向量嵌入: {'✅ 成功' if results['embeddings'] else '❌ 失败'}")
        
        print(f"\n📋 最终数据完整性检查:")
        print(f"  📝 笔记数据: {'✅' if final_status.get('crawl') else '❌'}")
        print(f"  🖼️ 图片处理: {'✅' if final_status.get('images') else '❌'}")
        print(f"  🔑 关键词: {'✅' if final_status.get('keywords') else '❌'}")
        print(f"  🧮 向量嵌入: {'✅' if final_status.get('embeddings') else '❌'}")
        
        self._show_token_status()
        
        return results
    
    def process_single_url_full_pipeline(self, url: str, max_notes: Optional[int] = None, force_reprocess: bool = False) -> Dict[str, bool]:
        """
        对单个URL进行全流程处理（按正确顺序执行）
        
        执行顺序：
        1. 爬取note，更新json信息
        2. 调用pic理解相关的服务，生成pic_results
        3. 总结pic_content
        4. 生成new_note
        5. 生成keywords
        6. 生成两个embedding
        
        Args:
            url: 要处理的URL
            max_notes: 最大处理笔记数量，None表示处理全部
            force_reprocess: 是否强制重新处理所有步骤
            
        Returns:
            Dict[str, bool]: 各步骤处理结果
        """
        print(f"\n🚀 开始单URL全流程处理: {url}")
        print("=" * 80)
        
        results = {
            'crawl': False,
            'images': False,
            'keywords': False,
            'embeddings': False
        }
        
        # 步骤1: 爬取URL，更新JSON信息
        print("\n📝 步骤1: 爬取note，更新JSON信息")
        result_file = self.crawl_url(url)
        if result_file:
            results['crawl'] = True
            print(f"✅ 爬取完成，结果文件: {result_file}")
        else:
            print(f"❌ 爬取失败，终止处理")
            return results
        
        # 检查当前处理状态
        status = {}
        if not force_reprocess:
            print("\n🔍 检查当前处理状态...")
            status = self.check_processing_status(result_file)
            print(f"📊 处理状态检查结果:")
            print(f"  📝 爬取: {'✅' if status.get('crawl') else '❌'}")
            print(f"  🖼️ 图片处理: {'✅' if status.get('images') else '❌'}")
            print(f"  🔑 关键词: {'✅' if status.get('keywords') else '❌'}")
            print(f"  🧮 向量嵌入: {'✅' if status.get('embeddings') else '❌'}")
        
        # 步骤2-4: 图片处理（包含pic理解、pic_content总结、new_note生成）
        print("\n🖼️ 步骤2-4: 图片处理（pic理解 → pic_content总结 → new_note生成）")
        if force_reprocess or not status.get('images'):
            results['images'] = self.process_images(result_file, max_notes=max_notes)
            if results['images']:
                print(f"✅ 图片处理完成（包含pic理解、内容总结、新笔记生成）")
            else:
                print(f"⚠️ 图片处理未完全完成")
        else:
            print(f"✅ 图片处理已完成，跳过")
            results['images'] = True
        
        # 步骤5: 关键词生成
        print("\n🔑 步骤5: 生成keywords")
        
        # 检查实际的关键词完成情况
        current_status = self.check_processing_status(result_file, strict=True)
        actual_keywords_complete = current_status.get('keywords', False)
        
        if force_reprocess or not status.get('keywords') or not actual_keywords_complete:
            print(f"🔄 开始关键词生成 (force_reprocess={force_reprocess}, status_check={status.get('keywords')}, actual_complete={actual_keywords_complete})")
            results['keywords'] = self.generate_keywords(result_file)
            if results['keywords']:
                print(f"✅ 关键词生成完成")
            else:
                print(f"⚠️ 关键词生成未完成")
        else:
            print(f"✅ 关键词已生成，跳过")
            results['keywords'] = True
        
        # 步骤6: 向量嵌入生成
        print("\n🧮 步骤6: 生成两个embedding")
        
        # 重新检查实际的嵌入完成情况
        current_status = self.check_processing_status(result_file, strict=True)
        actual_embeddings_complete = current_status.get('embeddings', False)
        
        if force_reprocess or not status.get('embeddings') or not actual_embeddings_complete:
            print(f"🔄 开始向量嵌入生成 (force_reprocess={force_reprocess}, status_check={status.get('embeddings')}, actual_complete={actual_embeddings_complete})")
            results['embeddings'] = self.generate_embeddings(result_file)
            if results['embeddings']:
                print(f"✅ 向量嵌入生成完成")
            else:
                print(f"⚠️ 向量嵌入生成未完成")
        else:
            print(f"✅ 向量嵌入已生成，跳过")
            results['embeddings'] = True
        
        # 最终状态检查
        print("\n🔍 最终状态检查...")
        final_status = self.check_processing_status(result_file)
        
        # 显示最终结果
        print("\n" + "=" * 80)
        print(f"📊 单URL全流程处理完成: {url}")
        print(f"📝 爬取: {'✅ 成功' if results['crawl'] else '❌ 失败'}")
        print(f"🖼️ 图片处理: {'✅ 成功' if results['images'] else '❌ 失败'}")
        print(f"🔑 关键词: {'✅ 成功' if results['keywords'] else '❌ 失败'}")
        print(f"🧮 向量嵌入: {'✅ 成功' if results['embeddings'] else '❌ 失败'}")
        
        print(f"\n📋 最终数据完整性检查:")
        print(f"  📝 笔记数据: {'✅' if final_status.get('crawl') else '❌'}")
        print(f"  🖼️ 图片处理: {'✅' if final_status.get('images') else '❌'}")
        print(f"  🔑 关键词: {'✅' if final_status.get('keywords') else '❌'}")
        print(f"  🧮 向量嵌入: {'✅' if final_status.get('embeddings') else '❌'}")
        
        self._show_token_status()
        
        return results
    
    def process_all_urls_full_pipeline(self, max_notes_per_file: Optional[int] = 10) -> Dict[str, int]:
        """
        处理results目录中所有文件的URL，进行全流程处理
        
        Args:
            max_notes_per_file: 每个文件最大处理笔记数量，None表示处理全部
            
        Returns:
            Dict[str, int]: 处理统计结果
        """
        print(f"\n🚀 开始全流程批量处理")
        print("=" * 60)
        
        # 获取所有JSON文件
        json_files = self.get_all_result_files()
        if not json_files:
            print("❌ 未找到任何JSON文件")
            return {'total_files': 0, 'total_urls': 0, 'processed_urls': 0, 'failed_urls': 0}
        
        print(f"📁 找到 {len(json_files)} 个JSON文件")
        
        # 提取所有URL
        all_urls = set()  # 使用set去重
        for json_file in json_files:
            urls = self.extract_urls_from_file(json_file)
            all_urls.update(urls)
            print(f"📄 {json_file.name}: 提取到 {len(urls)} 个URL")
        
        all_urls = list(all_urls)
        print(f"\n📊 总计发现 {len(all_urls)} 个唯一URL")
        
        if not all_urls:
            print("❌ 未找到任何有效URL")
            return {'total_files': len(json_files), 'total_urls': 0, 'processed_urls': 0, 'failed_urls': 0}
        
        # 处理每个URL
        stats = {
            'total_files': len(json_files),
            'total_urls': len(all_urls),
            'processed_urls': 0,
            'failed_urls': 0
        }
        
        for i, url in enumerate(all_urls, 1):
            print(f"\n🔄 处理进度: {i}/{len(all_urls)}")
            print(f"🔗 当前URL: {url}")
            
            try:
                # 对每个URL进行全流程处理
                result = self.process_single_url_full_pipeline(url, max_notes=max_notes_per_file)
                
                if result['crawl']:  # 至少爬取成功才算处理成功
                    stats['processed_urls'] += 1
                else:
                    stats['failed_urls'] += 1
                    
            except Exception as e:
                print(f"❌ URL处理异常: {e}")
                stats['failed_urls'] += 1
            
            # 显示进度
            print(f"\n📈 当前统计: 成功 {stats['processed_urls']}, 失败 {stats['failed_urls']}")
            self._show_token_status()
            
            # 短暂休息，避免请求过于频繁
            if i < len(all_urls):
                time.sleep(2)
        
        # 显示最终统计
        print("\n" + "=" * 60)
        print(f"🎉 全流程批量处理完成！")
        print(f"📁 处理文件数: {stats['total_files']}")
        print(f"🔗 发现URL数: {stats['total_urls']}")
        print(f"✅ 成功处理: {stats['processed_urls']}")
        print(f"❌ 处理失败: {stats['failed_urls']}")
        print(f"📊 成功率: {stats['processed_urls']/stats['total_urls']*100:.1f}%" if stats['total_urls'] > 0 else "📊 成功率: 0%")
        self._show_token_status()
        
        return stats
    
    def search_content(self, query: str, top_k: int = 10) -> Dict:
        """
        搜索相似内容
        
        Args:
            query: 搜索查询
            top_k: 返回结果数量
            
        Returns:
            Dict: 搜索结果
        """
        try:
            print(f"🔍 搜索内容: {query}")
            results = self.embedding_service.search_similar_content(
                query=query,
                top_k=top_k,
                results_dir=str(self.results_dir)
            )
            print(f"✅ 搜索完成，找到 {len(results.get('title_results', []))} 个相关结果")
            return results
        except Exception as e:
            print(f"❌ 搜索失败: {e}")
            return {'title_results': [], 'keywords_results': []}
    
    def _show_token_status(self):
        """显示Token使用状态"""
        try:
            # 获取当前可用模型列表
            models_to_check = self.llm_client.vision_models + self.llm_client.chat_models
            # 去重
            models_to_check = list(set(models_to_check))
            
            daily_limit = self.token_manager.daily_limit
            has_usage = False
            
            print(f"💰 Token状态 (限额 {daily_limit:,}/模型):")
            
            # Sort models by usage (descending) to show most used first
            model_usages = []
            for model in models_to_check:
                usage = self.token_manager.get_model_usage_today(model)
                if usage > 0:
                    model_usages.append((model, usage))
            
            model_usages.sort(key=lambda x: x[1], reverse=True)
            
            for model, usage in model_usages:
                has_usage = True
                percentage = (usage / daily_limit) * 100
                status_emoji = "🟢" if percentage < 50 else "🟡" if percentage < 80 else "🔴"
                # Shorten model name if too long for cleaner display? No, keep full name for clarity.
                print(f"  {status_emoji} {model}: {usage:,} ({percentage:.1f}%)")
            
            if not has_usage:
                print(f"  ⚪ 暂无消耗")
                
        except Exception as e:
            print(f"💰 Token状态: ❓ 无法获取 ({e})")
    
    def _show_detailed_token_stats(self):
        """显示详细Token统计"""
        try:
            print(f"📅 日期: {self.token_manager.get_today_key()}")
            daily_limit = self.token_manager.daily_limit
            print(f"📊 每日限额: {daily_limit:,} tokens")
            
            models_to_check = self.llm_client.vision_models + self.llm_client.chat_models
            models_to_check = list(set(models_to_check))
            
            total_used = 0
            
            for model in models_to_check:
                usage = self.token_manager.get_model_usage_today(model)
                if usage > 0:
                    percentage = (usage / daily_limit) * 100
                    status = "🟢" if percentage < 50 else "🟡" if percentage < 80 else "🔴"
                    remaining = daily_limit - usage
                    print(f"  {status} {model}: {usage:,} ({percentage:.1f}%)")
                    total_used += usage
            
            total_percentage = (total_used / daily_limit) * 100
            print(f"📈 总计已用: {total_used:,} ({total_percentage:.1f}%)")
                
        except Exception as e:
            print(f"❌ 无法获取详细统计: {e}")


def main():
    """
    主函数 - 交互式菜单
    """
    print("🎯 XHS集成处理器")
    print("=" * 50)
    
    try:
        processor = XHSIntegratedProcessor()
    except Exception as e:
        print(f"❌ 初始化失败: {e}")
        return
    
    while True:
        print("\n📋 请选择功能:")
        print("1. 🔄 全流程处理results中所有URL")
        print("2. 🎯 输入单个URL进行全流程处理")
        print("3. 📄 处理现有JSON文件")
        print("4. 🔍 检查处理状态服务")
        print("5. 🔍 搜索相似内容")
        print("6. 📊 查看Token使用情况")
        print("7. 📁 查看results目录文件")
        print("8. 🚪 退出")
        print("9. 🔍 发掘潜在博主")
        print("10. 🔄 全流程处理发掘的博主")
        
        choice = input("\n请输入选择 (1-10): ").strip()
        
        if choice == "1":
            print("\n🔄 开始全流程批量处理...")
            print("💡 提示: 设置最大处理数量是为了控制Token消耗和避免内存不足")
            print("   - 每个笔记大约消耗1000-3000 tokens")
            print("   - 建议首次使用时设置较小数量进行测试")
            max_notes_input = input("请输入每个文件最大处理笔记数量 (直接回车处理全部, 建议10): ").strip()
            
            if max_notes_input == "":
                max_notes = None
                print("⚠️  将处理所有笔记，可能消耗大量Token和时间")
            elif max_notes_input.isdigit():
                max_notes = int(max_notes_input)
            else:
                print("❌ 输入无效，使用默认值10")
                max_notes = 10
            
            confirm = input(f"\n确认开始处理? 这可能需要较长时间和消耗Token (y/n): ").strip().lower()
            if confirm == 'y':
                stats = processor.process_all_urls_full_pipeline(max_notes_per_file=max_notes)
                print(f"\n📊 处理完成，统计结果: {stats}")
            else:
                print("❌ 处理已取消")
        
        elif choice == "2":
            print("\n🎯 单URL全流程处理")
            url = input("请输入小红书URL: ").strip()
            
            if not url:
                print("❌ URL不能为空")
                continue
            
            if 'xiaohongshu.com' not in url and 'xhslink.com' not in url:
                print("⚠️ 警告: 这似乎不是小红书URL")
                confirm = input("是否继续处理? (y/n): ").strip().lower()
                if confirm != 'y':
                    continue
            
            # 询问处理数量
            max_notes_input = input("请输入最大处理笔记数量 (直接回车处理全部, 建议10): ").strip()
            if max_notes_input == "":
                max_notes = None
            elif max_notes_input.isdigit():
                max_notes = int(max_notes_input)
            else:
                print("❌ 输入无效，使用默认值None")
                max_notes = None
            
            result = processor.process_single_url_full_pipeline(url, max_notes=max_notes)
            print(f"\n📊 处理结果: {result}")
        
        elif choice == "3":
            print("\n📄 处理现有JSON文件")
            # 显示所有JSON文件
            json_files = processor.get_all_result_files()
            if not json_files:
                print("❌ 未找到任何JSON文件")
                continue
            
            print(f"\n📁 找到 {len(json_files)} 个JSON文件:")
            for i, file in enumerate(json_files, 1):
                size = file.stat().st_size / 1024  # KB
                mtime = datetime.fromtimestamp(file.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                print(f"  {i}. {file.name} ({size:.1f}KB, {mtime})")
            
            # 让用户选择文件
            file_choice = input(f"\n请选择要处理的文件编号 (1-{len(json_files)}) 或输入 'all' 处理全部: ").strip()
            
            if file_choice.lower() == 'all':
                # 处理所有文件
                max_notes_input = input("请输入每个文件最大处理笔记数量 (直接回车处理全部, 建议10): ").strip()
                max_notes = int(max_notes_input) if max_notes_input.isdigit() else None
                
                force_reprocess = input("是否强制重新处理所有步骤? (y/n): ").strip().lower() == 'y'
                
                print(f"\n🔄 开始处理 {len(json_files)} 个文件...")
                for i, json_file in enumerate(json_files, 1):
                    print(f"\n📄 处理文件 {i}/{len(json_files)}: {json_file.name}")
                    result = processor.process_existing_json_file(str(json_file), max_notes=max_notes, force_reprocess=force_reprocess)
                    print(f"📊 处理结果: {result}")
                
                print("\n🎉 所有文件处理完成！")
            
            elif file_choice.isdigit():
                file_index = int(file_choice) - 1
                if 0 <= file_index < len(json_files):
                    selected_file = json_files[file_index]
                    
                    # 询问处理参数
                    max_notes_input = input("请输入最大处理笔记数量 (直接回车处理全部, 建议10): ").strip()
                    max_notes = int(max_notes_input) if max_notes_input.isdigit() else None
                    
                    force_reprocess = input("是否强制重新处理所有步骤? (y/n): ").strip().lower() == 'y'
                    
                    # 处理选中的文件
                    result = processor.process_existing_json_file(str(selected_file), max_notes=max_notes, force_reprocess=force_reprocess)
                    print(f"\n📊 处理结果: {result}")
                else:
                    print("❌ 无效的文件编号")
            else:
                print("❌ 无效的选择")
        
        elif choice == "4":
            print("\n🔍 检查处理状态服务")
            print("📋 请选择检查模式:")
            print("1. 📊 检查所有文件的处理状态")
            print("2. 🔄 检查并重新处理未完成的步骤")
            print("3. ⚡ 强制重新处理所有步骤")
            
            check_choice = input("请选择 (1-3): ").strip()
            
            if check_choice == "1":
                # 检查所有文件的处理状态
                json_files = processor.get_all_result_files()
                if not json_files:
                    print("❌ 未找到任何JSON文件")
                    continue
                
                print(f"\n📁 检查 {len(json_files)} 个文件的处理状态...")
                total_stats = {'complete': 0, 'partial': 0, 'incomplete': 0}
                
                for json_file in json_files:
                    status = processor.check_processing_status(str(json_file))
                    print(f"\n📄 {json_file.name}:")
                    print(f"  爬取: {'✅' if status['crawl'] else '❌'}")
                    print(f"  图片处理: {'✅' if status['images'] else '❌'}")
                    print(f"  关键词: {'✅' if status['keywords'] else '❌'}")
                    print(f"  向量嵌入: {'✅' if status['embeddings'] else '❌'}")
                    
                    completed_steps = sum(status.values())
                    if completed_steps == 4:
                        total_stats['complete'] += 1
                        print(f"  状态: 🎉 完全处理 (4/4)")
                    elif completed_steps > 0:
                        total_stats['partial'] += 1
                        print(f"  状态: ⚠️ 部分处理 ({completed_steps}/4)")
                    else:
                        total_stats['incomplete'] += 1
                        print(f"  状态: ❌ 未处理 (0/4)")
                
                print(f"\n📊 总体状态统计:")
                print(f"  🎉 完全处理: {total_stats['complete']} 个文件")
                print(f"  ⚠️ 部分处理: {total_stats['partial']} 个文件")
                print(f"  ❌ 未处理: {total_stats['incomplete']} 个文件")
            
            elif check_choice == "2":
                # 检查并重新处理未完成的步骤
                print("\n🔄 检查并重新处理未完成的步骤...")
                max_notes_input = input("请输入每个文件最大处理笔记数量 (直接回车处理全部, 建议10): ").strip()
                max_notes = int(max_notes_input) if max_notes_input.isdigit() else None
                
                stats = processor.process_all_urls_full_pipeline(max_notes_per_file=max_notes)
                print(f"\n📊 重新处理完成，统计结果: {stats}")
            
            elif check_choice == "3":
                # 强制重新处理所有步骤
                print("\n⚡ 强制重新处理所有步骤...")
                print("⚠️ 警告: 这将重新处理所有文件，可能消耗大量Token")
                confirm = input("确认继续? (y/n): ").strip().lower()
                if confirm != 'y':
                    print("❌ 操作已取消")
                    continue
                
                max_notes_input = input("请输入每个文件最大处理笔记数量 (直接回车处理全部, 建议10): ").strip()
                max_notes = int(max_notes_input) if max_notes_input.isdigit() else None
                
                # 获取所有JSON文件并强制重新处理
                json_files = processor.get_all_result_files()
                if not json_files:
                    print("❌ 未找到任何JSON文件")
                    continue
                
                for json_file in json_files:
                    # 提取URL并强制重新处理
                    urls = processor.extract_urls_from_file(json_file)
                    for url in urls:
                        print(f"\n🔄 强制重新处理: {url}")
                        result = processor.process_single_url_full_pipeline(url, max_notes=max_notes, force_reprocess=True)
                        print(f"📊 处理结果: {result}")
                
                print("\n🎉 强制重新处理完成！")
            
            else:
                print("❌ 无效选择")
        
        elif choice == "5":
            print("\n🔍 搜索相似内容")
            query = input("请输入搜索关键词: ").strip()
            
            if not query:
                print("❌ 搜索关键词不能为空")
                continue
            
            top_k = input("请输入返回结果数量 (默认5): ").strip()
            top_k = int(top_k) if top_k.isdigit() else 5
            
            results = processor.search_content(query, top_k=top_k)
            
            # 显示搜索结果
            title_results = results.get('title_results', [])
            if title_results:
                print(f"\n🏷️ 标题相似度搜索结果 (前3条):")
                for i, result in enumerate(title_results[:3], 1):
                    print(f"  {i}. {result.get('title', '无标题')} (相似度: {result.get('similarity', 0):.3f})")
                    print(f"     {result.get('desc', '无描述')[:100]}...")
            
            keywords_results = results.get('keywords_results', [])
            if keywords_results:
                print(f"\n🔑 关键词相似度搜索结果 (前3条):")
                for i, result in enumerate(keywords_results[:3], 1):
                    print(f"  {i}. {result.get('title', '无标题')} (相似度: {result.get('similarity', 0):.3f})")
                    print(f"     关键词: {result.get('keywords', '无关键词')}")
        
        elif choice == "6":
            print(f"\n💰 Token使用情况:")
            processor._show_token_status()
            processor._show_detailed_token_stats()
        
        elif choice == "7":
            print(f"\n📁 results目录文件:")
            files = processor.get_all_result_files()
            if files:
                for i, file in enumerate(files, 1):
                    size = file.stat().st_size / 1024  # KB
                    mtime = datetime.fromtimestamp(file.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                    print(f"  {i}. {file.name} ({size:.1f}KB, {mtime})")
            else:
                print("  📭 目录为空")
        
        elif choice == "8":
            print("\n👋 再见！")
            break
            
        elif choice == "9":
            print("\n🔍 发掘潜在博主")
            keyword = input("请输入搜索关键词: ").strip()
            if not keyword:
                print("❌ 关键词不能为空")
                continue
                
            max_notes_input = input("请输入处理笔记数量 (默认10): ").strip()
            max_notes = int(max_notes_input) if max_notes_input.isdigit() else 10
            
            try:
                print(f"\n🚀 启动发掘任务: 关键词='{keyword}', 笔记数={max_notes}")
                # 不传参数，让 PlaywrightConfig 使用默认的 user_data_dir (即 func/playwright/playwright_user_data)
                # 这样可以复用已有的登录状态
                discovery = XiaohongshuBloggerDiscovery()
                discovery.start(keyword, max_notes=max_notes)
                print("\n✅ 发掘任务完成")
                print(f"📁 结果文件位置: {discovery.bloggers_file}")
            except Exception as e:
                print(f"\n❌ 发掘任务异常: {e}")

        elif choice == "10":
            print("\n🔄 全流程处理已发掘的博主")
            
            try:
                # 定位文件
                # 注意：这里需要确保路径与 XiaohongshuBloggerDiscovery 中一致
                # XiaohongshuBloggerDiscovery 位于 func/playwright/xhs/blogger_discovery.py
                # 它的 results_dir = Path(__file__).parent / "xhs" / "results" / "bloggers"
                # 即 func/playwright/xhs/xhs/results/bloggers
                # XHSIntegratedProcessor 位于 func/playwright/xhs_integrated_processor.py
                # 它的 results_dir = func/playwright/xhs/xhs/results
                
                # 统一使用 social_bot 的数据存储路径
                bloggers_file = Path(__file__).resolve().parent.parent.parent / "social_bot" / "data_store" / "xhs" / "discovered_bloggers.json"

                if not bloggers_file.exists():
                    print(f"❌ 未找到发掘结果文件: {bloggers_file}")
                    print("💡 请先使用功能 9 发掘博主")
                    continue
                
                # 读取文件
                with open(bloggers_file, 'r', encoding='utf-8') as f:
                    bloggers = json.load(f)
                
                if not bloggers:
                    print("⚠️ 发掘记录为空")
                    continue
                
                print(f"📊 发现 {len(bloggers)} 个已记录的博主")
                
                # 筛选未处理的（这里只是简单列出，实际可以通过文件检查是否已处理）
                # 或者直接全部询问
                
                count = 0
                for user_id, info in bloggers.items():
                    count += 1
                    print(f"{count}. {info.get('nickname')} (ID: {user_id}) - {info.get('gender')}")
                    
                confirm = input("\n是否对所有博主进行全流程处理? (y/n): ").strip().lower()
                if confirm != 'y':
                    continue
                    
                max_notes_input = input("请输入每个博主最大处理笔记数量 (默认10): ").strip()
                max_notes = int(max_notes_input) if max_notes_input.isdigit() else 10
                
                # 处理
                success_count = 0
                fail_count = 0
                
                for i, (user_id, info) in enumerate(bloggers.items(), 1):
                    url = info.get('url')
                    nickname = info.get('nickname')
                    
                    if not url:
                        print(f"⚠️ 跳过无效URL: {nickname}")
                        continue
                        
                    print(f"\n🔄 [{i}/{len(bloggers)}] 处理博主: {nickname}")
                    print(f"🔗 URL: {url}")
                    
                    try:
                        result = processor.process_single_url_full_pipeline(url, max_notes=max_notes)
                        if result['crawl']:
                            success_count += 1
                        else:
                            fail_count += 1
                    except Exception as e:
                        print(f"❌ 处理异常: {e}")
                        fail_count += 1
                        
                    # 休息一下
                    time.sleep(2)
                    
                print("\n" + "=" * 60)
                print(f"🎉 批量处理完成")
                print(f"✅ 成功: {success_count}")
                print(f"❌ 失败: {fail_count}")
                
            except Exception as e:
                print(f"\n❌ 处理异常: {e}")
        
        else:
            print("❌ 无效选择，请重新输入")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 用户中断，程序退出")
    except Exception as e:
        print(f"\n❌ 程序异常: {e}")