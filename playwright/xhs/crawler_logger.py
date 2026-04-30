#!/usr/bin/env python3
"""
爬虫日志管理模块
提供统一的日志记录和管理功能
"""

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
import json

class CrawlerLogger:
    """
    爬虫专用日志管理器
    支持多级别日志、文件输出、结构化日志等功能
    """
    
    def __init__(self, 
                 name: str = "xiaohongshu_crawler",
                 log_file: Optional[Path] = None,
                 level: int = logging.INFO,
                 enable_console: bool = True):
        """
        初始化日志管理器
        
        Args:
            name: 日志器名称
            log_file: 日志文件路径
            level: 日志级别
            enable_console: 是否启用控制台输出
        """
        self.logger = logging.getLogger(name)
        self.logger.setLevel(level)
        
        # 清除已有的处理器
        self.logger.handlers.clear()
        
        # 创建格式化器
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # 控制台处理器
        if enable_console:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(formatter)
            self.logger.addHandler(console_handler)
        
        # 文件处理器
        if log_file:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)
        
        # 统计信息
        self.stats = {
            'start_time': datetime.now(),
            'cards_processed': 0,
            'cards_success': 0,
            'cards_failed': 0,
            'scroll_rounds': 0,
            'errors': []
        }
    
    def info(self, message: str, **kwargs):
        """记录信息日志"""
        self.logger.info(self._format_message(message, **kwargs))
    
    def warning(self, message: str, **kwargs):
        """记录警告日志"""
        self.logger.warning(self._format_message(message, **kwargs))
    
    def error(self, message: str, error: Optional[Exception] = None, **kwargs):
        """记录错误日志"""
        if error:
            self.stats['errors'].append({
                'time': datetime.now().isoformat(),
                'message': message,
                'error': str(error),
                'type': type(error).__name__
            })
        self.logger.error(self._format_message(message, **kwargs))
    
    def debug(self, message: str, **kwargs):
        """记录调试日志"""
        self.logger.debug(self._format_message(message, **kwargs))
    
    def _format_message(self, message: str, **kwargs) -> str:
        """格式化日志消息"""
        if kwargs:
            extra_info = " | ".join([f"{k}={v}" for k, v in kwargs.items()])
            return f"{message} | {extra_info}"
        return message
    
    def log_card_processing(self, card_index: int, action: str, success: bool = True, **kwargs):
        """记录卡片处理日志"""
        self.stats['cards_processed'] += 1
        if success:
            self.stats['cards_success'] += 1
            self.info(f"卡片处理成功", 
                     card_index=card_index, 
                     action=action, 
                     **kwargs)
        else:
            self.stats['cards_failed'] += 1
            self.warning(f"卡片处理失败", 
                        card_index=card_index, 
                        action=action, 
                        **kwargs)
    
    def log_scroll_round(self, round_num: int, cards_found: int, **kwargs):
        """记录滚动轮次日志"""
        self.stats['scroll_rounds'] = round_num
        self.info(f"滚动轮次完成", 
                 round=round_num, 
                 cards_found=cards_found, 
                 **kwargs)
    
    def log_page_status(self, status_info: dict):
        """记录页面状态日志"""
        self.debug("页面状态检查", **status_info)
    
    def log_performance_metrics(self, metrics: dict):
        """记录性能指标"""
        self.info("性能指标", **metrics)
    
    def get_stats(self) -> dict:
        """获取统计信息"""
        current_time = datetime.now()
        duration = current_time - self.stats['start_time']
        
        return {
            **self.stats,
            'end_time': current_time,
            'duration_seconds': duration.total_seconds(),
            'success_rate': (self.stats['cards_success'] / max(self.stats['cards_processed'], 1)) * 100
        }
    
    def print_summary(self):
        """打印执行摘要"""
        stats = self.get_stats()
        
        print("\n" + "="*50)
        print("📊 爬虫执行摘要")
        print("="*50)
        print(f"⏱️  执行时间: {stats['duration_seconds']:.2f} 秒")
        print(f"📄 处理卡片: {stats['cards_processed']} 个")
        print(f"✅ 成功: {stats['cards_success']} 个")
        print(f"❌ 失败: {stats['cards_failed']} 个")
        print(f"📈 成功率: {stats['success_rate']:.1f}%")
        print(f"🔄 滚动轮次: {stats['scroll_rounds']} 轮")
        
        if stats['errors']:
            print(f"⚠️  错误数量: {len(stats['errors'])}")
            print("\n最近的错误:")
            for error in stats['errors'][-3:]:  # 显示最近3个错误
                print(f"  - {error['time']}: {error['message']} ({error['type']})")
        
        print("="*50)
    
    def save_stats(self, file_path: Path):
        """保存统计信息到文件"""
        stats = self.get_stats()
        # 转换datetime对象为字符串
        stats['start_time'] = stats['start_time'].isoformat()
        stats['end_time'] = stats['end_time'].isoformat()
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
        
        self.info(f"统计信息已保存到: {file_path}")

# 创建全局日志实例
def create_logger(log_file: Optional[Path] = None, 
                 level: int = logging.INFO) -> CrawlerLogger:
    """创建日志实例"""
    return CrawlerLogger(log_file=log_file, level=level)