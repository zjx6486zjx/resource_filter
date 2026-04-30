#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小红书处理器模块
整合爬取、图片处理、关键词生成和向量化功能的核心模块
"""

import json
import os
import sys
import time
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple

# 添加路径以导入服务模块
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.append(project_root)
sys.path.append(os.path.join(project_root, "func"))
sys.path.append(os.path.join(project_root, "func", "src"))

# 导入各个处理模块
from .crawler import XiaohongshuSmartCrawler
from .image_service import ImageService
from .keyword_service import KeywordService
from .embedding_service import EmbeddingSearchService
from api.token_manager import TokenManager


class XHSProcessor:
    """
    小红书处理器核心类
    整合所有处理功能的统一接口
    """
    
    def __init__(self, results_dir: Optional[str] = None):
        """
        初始化处理器
        
        Args:
            results_dir: 结果目录路径，默认为当前目录下的xhs/results
        """
        if results_dir:
            self.results_dir = Path(results_dir)
        else:
            # 修改路径：从xhs/results改为results
            self.results_dir = Path(__file__).parent.parent / "results"
        
        self.results_dir.mkdir(parents=True, exist_ok=True)
        
        # 初始化服务
        self.crawler = None
        self.image_service = ImageService()
        self.keyword_service = KeywordService()
        self.embedding_service = EmbeddingSearchService()
        self.token_manager = TokenManager()
        
        print(f"🚀 小红书处理器初始化完成")
        print(f"📁 结果目录: {self.results_dir}")
    
    def get_all_result_files(self) -> List[Path]:
        """
        获取results目录下的所有JSON文件
        
        Returns:
            List[Path]: JSON文件路径列表
        """
        json_files = list(self.results_dir.glob("*.json"))
        return json_files
    
    def extract_urls_from_file(self, json_file: Path) -> Optional[str]:
        """
        从单个结果文件中提取URL
        
        Args:
            json_file: JSON文件路径
            
        Returns:
            Optional[str]: 提取的URL，失败时返回None
        """
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            crawl_info = data.get('crawl_info', {})
            target_url = crawl_info.get('target_url')
            
            return target_url
        except Exception as e:
            print(f"❌ 读取文件失败 {json_file.name}: {e}")
            return None
    
    def crawl_url(self, url: str, max_retries: int = 2) -> Optional[str]:
        """
        爬取指定URL
        
        Args:
            url: 目标URL
            max_retries: 最大重试次数
            
        Returns:
            Optional[str]: 成功时返回结果文件路径，失败时返回None
        """
        import threading
        import asyncio
        
        print(f"🔍 开始爬取: {url}")
        
        def run_crawler_in_thread():
            """在新线程中运行爬虫以避免asyncio冲突"""
            for attempt in range(max_retries + 1):
                try:
                    # 初始化爬虫
                    self.crawler = XiaohongshuSmartCrawler()
                    
                    # 启动爬虫
                    self.crawler.start_crawler(url, headless=True)
                    
                    # 智能滚动加载
                    total_cards = self.crawler.smart_scroll_and_load(target_card_count=50)
                    print(f"📊 发现 {total_cards} 个卡片")
                    
                    # 获取结果文件路径
                    result_file = self.crawler.results_file
                    
                    # 关闭爬虫
                    if self.crawler.playwright_config:
                        self.crawler.playwright_config.close()
                    
                    print(f"✅ 爬取完成: {result_file}")
                    return result_file
                    
                except Exception as e:
                    print(f"❌ 爬取失败 (尝试 {attempt + 1}/{max_retries + 1}): {e}")
                    
                    # 确保清理资源
                    try:
                        if self.crawler and self.crawler.playwright_config:
                            self.crawler.playwright_config.close()
                    except:
                        pass
                    
                    if attempt < max_retries:
                        print(f"⏳ 等待 5 秒后重试...")
                        time.sleep(5)
            
            return None
        
        # 检查是否在asyncio循环中
        try:
            loop = asyncio.get_running_loop()
            print("🔄 检测到asyncio循环，在新线程中运行爬虫...")
            # 在新线程中运行爬虫
            result = [None]
            
            def thread_target():
                result[0] = run_crawler_in_thread()
            
            thread = threading.Thread(target=thread_target)
            thread.start()
            thread.join()
            
            return result[0]
            
        except RuntimeError:
            # 没有运行的asyncio循环，直接运行
            return run_crawler_in_thread()
    
    def process_images(self, json_file_path: str, max_notes: Optional[int] = None) -> bool:
        """
        处理图片内容
        
        Args:
            json_file_path: JSON文件路径
            max_notes: 最大处理笔记数量
            
        Returns:
            bool: 是否成功
        """
        print(f"🖼️ 处理图片: {os.path.basename(json_file_path)}")
        
        try:
            success = self.image_service.process_json_file(json_file_path, max_notes)
            if success:
                print(f"✅ 图片处理完成")
                return True
            else:
                print(f"❌ 图片处理失败")
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
            bool: 是否成功
        """
        print(f"🔑 生成关键词: {os.path.basename(json_file_path)}")
        
        try:
            success = self.keyword_service.generate_keywords_for_json(json_file_path)
            if success:
                print(f"✅ 关键词生成完成")
                return True
            else:
                print(f"❌ 关键词生成失败")
                return False
        except Exception as e:
            print(f"❌ 关键词生成异常: {e}")
            return False
    
    def generate_embeddings(self, json_file_path: str) -> bool:
        """
        生成向量
        
        Args:
            json_file_path: JSON文件路径
            
        Returns:
            bool: 是否成功
        """
        print(f"🧮 生成向量: {os.path.basename(json_file_path)}")
        
        try:
            success = self.embedding_service.generate_embeddings_for_json(json_file_path)
            if success:
                print(f"✅ 向量生成完成")
                return True
            else:
                print(f"❌ 向量生成失败")
                return False
        except Exception as e:
            print(f"❌ 向量生成异常: {e}")
            return False
    
    def process_single_file(self, 
                           json_file_path: str,
                           url: Optional[str] = None,
                           enable_crawl: bool = True,
                           enable_images: bool = True,
                           enable_keywords: bool = True,
                           enable_embeddings: bool = True,
                           max_notes: Optional[int] = None) -> Dict[str, bool]:
        """
        处理单个文件的完整流程
        
        Args:
            json_file_path: JSON文件路径
            url: 目标URL（如果为None则从文件中提取）
            enable_crawl: 是否启用爬取
            enable_images: 是否启用图片处理
            enable_keywords: 是否启用关键词生成
            enable_embeddings: 是否启用向量生成
            max_notes: 最大处理笔记数量
            
        Returns:
            Dict[str, bool]: 各步骤的执行结果
        """
        print(f"\n{'='*60}")
        print(f"📄 处理文件: {os.path.basename(json_file_path)}")
        
        # 如果没有提供URL，尝试从文件中提取
        if url is None and enable_crawl:
            url = self.extract_urls_from_file(Path(json_file_path))
            if url:
                print(f"🎯 提取到URL: {url}")
            else:
                print(f"❌ 无法提取URL，跳过爬取步骤")
                enable_crawl = False
        
        print(f"{'='*60}")
        
        results = {
            'crawl': True,
            'images': True,
            'keywords': True,
            'embeddings': True
        }
        
        # 步骤1: 爬取
        if enable_crawl and url:
            result_file = self.crawl_url(url)
            if result_file:
                json_file_path = result_file  # 更新为新的文件路径
                results['crawl'] = True
            else:
                results['crawl'] = False
                print(f"❌ 爬取失败，跳过后续步骤")
                return results
        elif not enable_crawl:
            print(f"⏭️ 跳过爬取步骤")
        
        # 步骤2: 图片处理
        if enable_images:
            results['images'] = self.process_images(json_file_path, max_notes)
        else:
            print(f"⏭️ 跳过图片处理步骤")
        
        # 步骤3: 关键词生成
        if enable_keywords:
            results['keywords'] = self.generate_keywords(json_file_path)
        else:
            print(f"⏭️ 跳过关键词生成步骤")
        
        # 步骤4: 向量生成
        if enable_embeddings:
            results['embeddings'] = self.generate_embeddings(json_file_path)
        else:
            print(f"⏭️ 跳过向量生成步骤")
        
        return results
    
    def process_all_files(self, 
                         enable_crawl: bool = True,
                         enable_images: bool = True,
                         enable_keywords: bool = True,
                         enable_embeddings: bool = True,
                         max_notes: Optional[int] = None,
                         target_files: Optional[List[str]] = None) -> Dict[str, int]:
        """
        批量处理所有文件
        
        Args:
            enable_crawl: 是否启用爬取
            enable_images: 是否启用图片处理
            enable_keywords: 是否启用关键词生成
            enable_embeddings: 是否启用向量生成
            max_notes: 最大处理笔记数量
            target_files: 指定要处理的文件列表（文件名），None表示处理全部
            
        Returns:
            Dict[str, int]: 处理统计信息
        """
        print(f"\n🚀 开始批量处理小红书数据")
        
        # 显示当前token使用情况
        self.show_token_usage()
        
        # 获取所有结果文件
        json_files = self.get_all_result_files()
        
        # 如果指定了目标文件，进行过滤
        if target_files:
            json_files = [f for f in json_files if f.name in target_files]
            print(f"🎯 指定处理文件: {[f.name for f in json_files]}")
        
        if not json_files:
            print(f"❌ 未找到要处理的文件")
            return {}
        
        print(f"📋 找到 {len(json_files)} 个文件待处理")
        
        # 处理统计
        stats = {
            'total_files': len(json_files),
            'crawl_success': 0,
            'crawl_failed': 0,
            'image_success': 0,
            'image_failed': 0,
            'keyword_success': 0,
            'keyword_failed': 0,
            'embedding_success': 0,
            'embedding_failed': 0
        }
        
        # 逐个处理
        for i, json_file in enumerate(json_files, 1):
            print(f"\n📊 进度: {i}/{len(json_files)}")
            
            try:
                results = self.process_single_file(
                    json_file_path=str(json_file),
                    enable_crawl=enable_crawl,
                    enable_images=enable_images,
                    enable_keywords=enable_keywords,
                    enable_embeddings=enable_embeddings,
                    max_notes=max_notes
                )
                
                # 更新统计
                if results['crawl']:
                    stats['crawl_success'] += 1
                else:
                    stats['crawl_failed'] += 1
                
                if results['images']:
                    stats['image_success'] += 1
                else:
                    stats['image_failed'] += 1
                
                if results['keywords']:
                    stats['keyword_success'] += 1
                else:
                    stats['keyword_failed'] += 1
                
                if results['embeddings']:
                    stats['embedding_success'] += 1
                else:
                    stats['embedding_failed'] += 1
                
                print(f"📋 处理结果: {results}")
                
            except Exception as e:
                print(f"❌ 处理异常: {e}")
                stats['crawl_failed'] += 1
                stats['image_failed'] += 1
                stats['keyword_failed'] += 1
                stats['embedding_failed'] += 1
            
            # 每处理完一个文件显示进度
            self.show_progress_stats(stats, i, len(json_files))
            
            # 适当休息，避免请求过于频繁
            if i < len(json_files):
                print(f"⏳ 休息 3 秒...")
                time.sleep(3)
        
        # 显示最终统计
        self.show_final_stats(stats)
        
        return stats
    
    def show_token_usage(self):
        """
        显示当前token使用情况
        """
        print(f"\n📊 当前Token使用情况:")
        
        # 清理旧数据
        self.token_manager.cleanup_old_data()
        
        # 显示各模型使用情况
        chat_models = ["doubao-seed-1-6-flash-250715", "doubao-1-5-pro-32k-250115", "doubao-1-5-thinking-pro-250415"]
        stats = self.token_manager.get_usage_stats(chat_models)
        
        for model, info in stats['models'].items():
            print(f"  {info['status']} {model}: {info['usage']:,}/{stats['daily_limit']:,} tokens ({info['percentage']:.1f}%)")
    
    def show_progress_stats(self, stats: Dict[str, int], current: int, total: int):
        """
        显示进度统计
        
        Args:
            stats: 统计信息
            current: 当前处理数量
            total: 总数量
        """
        print(f"\n📈 进度统计 ({current}/{total}):")
        print(f"  爬取: 成功 {stats['crawl_success']}, 失败 {stats['crawl_failed']}")
        print(f"  图片: 成功 {stats['image_success']}, 失败 {stats['image_failed']}")
        print(f"  关键词: 成功 {stats['keyword_success']}, 失败 {stats['keyword_failed']}")
        print(f"  向量: 成功 {stats['embedding_success']}, 失败 {stats['embedding_failed']}")
    
    def show_final_stats(self, stats: Dict[str, int]):
        """
        显示最终统计信息
        
        Args:
            stats: 统计信息
        """
        print(f"\n🎉 批量处理完成!")
        print(f"{'='*50}")
        print(f"📊 最终统计:")
        print(f"  总文件数: {stats['total_files']}")
        print(f"  爬取: 成功 {stats['crawl_success']}, 失败 {stats['crawl_failed']}")
        print(f"  图片处理: 成功 {stats['image_success']}, 失败 {stats['image_failed']}")
        print(f"  关键词生成: 成功 {stats['keyword_success']}, 失败 {stats['keyword_failed']}")
        print(f"  向量生成: 成功 {stats['embedding_success']}, 失败 {stats['embedding_failed']}")
        print(f"{'='*50}")
        
        # 显示最终token使用情况
        self.show_token_usage()
    
    def search_similar_content(self, query: str, top_k: int = 10) -> Dict:
        """
        搜索相似内容
        
        Args:
            query: 搜索查询
            top_k: 返回结果数量
            
        Returns:
            Dict: 搜索结果
        """
        json_files = [str(f) for f in self.get_all_result_files()]
        return self.embedding_service.search_similar_notes(query, json_files, top_k)
    
    def search_and_rerank(self, query: str, top_k_search: int = 10, top_k_rerank: int = 3) -> Dict:
        """
        搜索并重排序
        
        Args:
            query: 搜索查询
            top_k_search: 搜索阶段返回结果数量
            top_k_rerank: 重排序阶段返回结果数量
            
        Returns:
            Dict: 重排序后的搜索结果
        """
        json_files = [str(f) for f in self.get_all_result_files()]
        return self.embedding_service.search_and_rerank(query, json_files, top_k_search, top_k_rerank)


# 便捷函数
def create_processor(results_dir: Optional[str] = None) -> XHSProcessor:
    """
    创建处理器实例
    
    Args:
        results_dir: 结果目录路径
        
    Returns:
        XHSProcessor: 处理器实例
    """
    return XHSProcessor(results_dir)


def quick_process_all(enable_crawl: bool = True,
                     enable_images: bool = True,
                     enable_keywords: bool = True,
                     enable_embeddings: bool = True,
                     max_notes: Optional[int] = None,
                     results_dir: Optional[str] = None) -> Dict[str, int]:
    """
    快速处理所有文件
    
    Args:
        enable_crawl: 是否启用爬取
        enable_images: 是否启用图片处理
        enable_keywords: 是否启用关键词生成
        enable_embeddings: 是否启用向量生成
        max_notes: 最大处理笔记数量
        results_dir: 结果目录路径
        
    Returns:
        Dict[str, int]: 处理统计信息
    """
    processor = create_processor(results_dir)
    return processor.process_all_files(
        enable_crawl=enable_crawl,
        enable_images=enable_images,
        enable_keywords=enable_keywords,
        enable_embeddings=enable_embeddings,
        max_notes=max_notes
    )


def quick_search(query: str, top_k: int = 10, results_dir: Optional[str] = None) -> Dict:
    """
    快速搜索相似内容
    
    Args:
        query: 搜索查询
        top_k: 返回结果数量
        results_dir: 结果目录路径
        
    Returns:
        Dict: 搜索结果
    """
    processor = create_processor(results_dir)
    return processor.search_similar_content(query, top_k)