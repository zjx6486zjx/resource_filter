#!/usr/bin/env python3
"""
爬虫性能监控模块
收集和分析爬虫性能指标
"""

import time
import psutil
import threading
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import json

@dataclass
class PerformanceMetrics:
    """性能指标数据类"""
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    
    # 页面指标
    page_load_time: float = 0.0
    total_scroll_time: float = 0.0
    total_click_time: float = 0.0
    
    # 卡片指标
    cards_found: int = 0
    cards_clicked: int = 0
    cards_failed: int = 0
    
    # 滚动指标
    scroll_rounds: int = 0
    successful_scrolls: int = 0
    failed_scrolls: int = 0
    
    # 系统资源指标
    peak_memory_mb: float = 0.0
    avg_cpu_percent: float = 0.0
    
    # 错误指标
    error_counts: Dict[str, int] = field(default_factory=dict)
    
    # 时间线记录
    timeline: List[Dict[str, Any]] = field(default_factory=list)

class PerformanceMonitor:
    """性能监控器"""
    
    def __init__(self, logger: Optional[Any] = None):
        self.logger = logger
        self.metrics = PerformanceMetrics()
        self.is_monitoring = False
        self.monitor_thread = None
        self._lock = threading.Lock()
        
        # 系统监控数据
        self._cpu_samples = []
        self._memory_samples = []
    
    def start_monitoring(self):
        """开始监控"""
        with self._lock:
            if self.is_monitoring:
                return
            
            self.is_monitoring = True
            self.metrics.start_time = time.time()
            
            # 启动系统资源监控线程
            self.monitor_thread = threading.Thread(target=self._monitor_system_resources)
            self.monitor_thread.daemon = True
            self.monitor_thread.start()
            
            self._add_timeline_event("monitoring_started", {"timestamp": self.metrics.start_time})
            
            if self.logger:
                self.logger.info("性能监控已启动")
    
    def stop_monitoring(self):
        """停止监控"""
        with self._lock:
            if not self.is_monitoring:
                return
            
            self.is_monitoring = False
            self.metrics.end_time = time.time()
            
            # 计算平均CPU使用率
            if self._cpu_samples:
                self.metrics.avg_cpu_percent = sum(self._cpu_samples) / len(self._cpu_samples)
            
            # 计算峰值内存使用
            if self._memory_samples:
                self.metrics.peak_memory_mb = max(self._memory_samples)
            
            self._add_timeline_event("monitoring_stopped", {
                "timestamp": self.metrics.end_time,
                "duration": self.get_total_duration()
            })
            
            if self.logger:
                self.logger.info(f"性能监控已停止，总耗时: {self.get_total_duration():.2f}秒")
    
    def _monitor_system_resources(self):
        """监控系统资源使用情况"""
        process = psutil.Process()
        
        while self.is_monitoring:
            try:
                # CPU使用率
                cpu_percent = process.cpu_percent()
                self._cpu_samples.append(cpu_percent)
                
                # 内存使用量（MB）
                memory_mb = process.memory_info().rss / 1024 / 1024
                self._memory_samples.append(memory_mb)
                
                time.sleep(1)  # 每秒采样一次
                
            except Exception as e:
                if self.logger:
                    self.logger.warning(f"系统资源监控异常: {e}")
                break
    
    def record_page_load(self, duration: float):
        """记录页面加载时间"""
        self.metrics.page_load_time = duration
        self._add_timeline_event("page_loaded", {"duration": duration})
        
        if self.logger:
            self.logger.info(f"页面加载完成，耗时: {duration:.2f}秒")
    
    def record_scroll_start(self):
        """记录滚动开始"""
        self._scroll_start_time = time.time()
        self.metrics.scroll_rounds += 1
        self._add_timeline_event("scroll_started", {"round": self.metrics.scroll_rounds})
    
    def record_scroll_end(self, success: bool = True):
        """记录滚动结束"""
        if hasattr(self, '_scroll_start_time'):
            duration = time.time() - self._scroll_start_time
            self.metrics.total_scroll_time += duration
            
            if success:
                self.metrics.successful_scrolls += 1
            else:
                self.metrics.failed_scrolls += 1
            
            self._add_timeline_event("scroll_ended", {
                "duration": duration,
                "success": success,
                "total_scroll_time": self.metrics.total_scroll_time
            })
    
    def record_click_start(self, card_index: int):
        """记录点击开始"""
        self._click_start_time = time.time()
        self._current_card_index = card_index
        self._add_timeline_event("click_started", {"card_index": card_index})
    
    def record_click_end(self, success: bool = True):
        """记录点击结束"""
        if hasattr(self, '_click_start_time'):
            duration = time.time() - self._click_start_time
            self.metrics.total_click_time += duration
            
            if success:
                self.metrics.cards_clicked += 1
            else:
                self.metrics.cards_failed += 1
            
            self._add_timeline_event("click_ended", {
                "card_index": getattr(self, '_current_card_index', -1),
                "duration": duration,
                "success": success,
                "total_click_time": self.metrics.total_click_time
            })
    
    def record_cards_found(self, count: int):
        """记录找到的卡片数量"""
        self.metrics.cards_found = count
        self._add_timeline_event("cards_found", {"count": count})
    
    def record_error(self, error_type: str, details: str = ""):
        """记录错误"""
        self.metrics.error_counts[error_type] = self.metrics.error_counts.get(error_type, 0) + 1
        self._add_timeline_event("error_occurred", {
            "error_type": error_type,
            "details": details,
            "total_count": self.metrics.error_counts[error_type]
        })
    
    def _add_timeline_event(self, event_type: str, data: Dict[str, Any]):
        """添加时间线事件"""
        event = {
            "timestamp": time.time(),
            "event_type": event_type,
            "data": data
        }
        self.metrics.timeline.append(event)
    
    def get_total_duration(self) -> float:
        """获取总耗时"""
        if self.metrics.end_time:
            return self.metrics.end_time - self.metrics.start_time
        return time.time() - self.metrics.start_time
    
    def get_success_rate(self) -> float:
        """获取成功率"""
        total_attempts = self.metrics.cards_clicked + self.metrics.cards_failed
        if total_attempts == 0:
            return 0.0
        return (self.metrics.cards_clicked / total_attempts) * 100
    
    def get_scroll_efficiency(self) -> float:
        """获取滚动效率"""
        if self.metrics.scroll_rounds == 0:
            return 0.0
        return (self.metrics.successful_scrolls / self.metrics.scroll_rounds) * 100
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """获取性能摘要"""
        total_duration = self.get_total_duration()
        
        return {
            "总体指标": {
                "总耗时": f"{total_duration:.2f}秒",
                "页面加载时间": f"{self.metrics.page_load_time:.2f}秒",
                "成功率": f"{self.get_success_rate():.1f}%",
                "滚动效率": f"{self.get_scroll_efficiency():.1f}%"
            },
            "卡片处理": {
                "发现卡片": self.metrics.cards_found,
                "成功点击": self.metrics.cards_clicked,
                "点击失败": self.metrics.cards_failed,
                "平均点击时间": f"{self.metrics.total_click_time / max(1, self.metrics.cards_clicked + self.metrics.cards_failed):.2f}秒"
            },
            "滚动统计": {
                "滚动轮次": self.metrics.scroll_rounds,
                "成功滚动": self.metrics.successful_scrolls,
                "失败滚动": self.metrics.failed_scrolls,
                "总滚动时间": f"{self.metrics.total_scroll_time:.2f}秒"
            },
            "系统资源": {
                "峰值内存": f"{self.metrics.peak_memory_mb:.1f}MB",
                "平均CPU": f"{self.metrics.avg_cpu_percent:.1f}%"
            },
            "错误统计": self.metrics.error_counts
        }
    
    def export_metrics(self, file_path: str):
        """导出指标到文件"""
        try:
            export_data = {
                "summary": self.get_performance_summary(),
                "raw_metrics": {
                    "start_time": self.metrics.start_time,
                    "end_time": self.metrics.end_time,
                    "page_load_time": self.metrics.page_load_time,
                    "total_scroll_time": self.metrics.total_scroll_time,
                    "total_click_time": self.metrics.total_click_time,
                    "cards_found": self.metrics.cards_found,
                    "cards_clicked": self.metrics.cards_clicked,
                    "cards_failed": self.metrics.cards_failed,
                    "scroll_rounds": self.metrics.scroll_rounds,
                    "successful_scrolls": self.metrics.successful_scrolls,
                    "failed_scrolls": self.metrics.failed_scrolls,
                    "peak_memory_mb": self.metrics.peak_memory_mb,
                    "avg_cpu_percent": self.metrics.avg_cpu_percent,
                    "error_counts": self.metrics.error_counts
                },
                "timeline": self.metrics.timeline,
                "export_time": datetime.now().isoformat()
            }
            
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, ensure_ascii=False, indent=2)
            
            if self.logger:
                self.logger.info(f"性能指标已导出到: {file_path}")
                
        except Exception as e:
            if self.logger:
                self.logger.error(f"导出性能指标失败: {e}")
    
    def print_summary(self):
        """打印性能摘要"""
        summary = self.get_performance_summary()
        
        print("\n" + "="*60)
        print("🚀 爬虫性能报告")
        print("="*60)
        
        for category, metrics in summary.items():
            print(f"\n📊 {category}:")
            for key, value in metrics.items():
                print(f"  • {key}: {value}")
        
        print("\n" + "="*60)

class PerformanceProfiler:
    """性能分析器"""
    
    def __init__(self, monitor: PerformanceMonitor):
        self.monitor = monitor
    
    def analyze_bottlenecks(self) -> Dict[str, str]:
        """分析性能瓶颈"""
        bottlenecks = {}
        metrics = self.monitor.metrics
        
        # 分析页面加载
        if metrics.page_load_time > 10:
            bottlenecks["页面加载"] = f"页面加载时间过长 ({metrics.page_load_time:.1f}秒)，建议检查网络连接"
        
        # 分析滚动效率
        scroll_efficiency = self.monitor.get_scroll_efficiency()
        if scroll_efficiency < 80:
            bottlenecks["滚动效率"] = f"滚动成功率较低 ({scroll_efficiency:.1f}%)，可能存在页面加载问题"
        
        # 分析点击成功率
        success_rate = self.monitor.get_success_rate()
        if success_rate < 90:
            bottlenecks["点击成功率"] = f"点击成功率较低 ({success_rate:.1f}%)，建议检查元素选择器"
        
        # 分析内存使用
        if metrics.peak_memory_mb > 500:
            bottlenecks["内存使用"] = f"内存使用过高 ({metrics.peak_memory_mb:.1f}MB)，建议优化内存管理"
        
        # 分析CPU使用
        if metrics.avg_cpu_percent > 80:
            bottlenecks["CPU使用"] = f"CPU使用率过高 ({metrics.avg_cpu_percent:.1f}%)，建议优化算法"
        
        return bottlenecks
    
    def get_optimization_suggestions(self) -> List[str]:
        """获取优化建议"""
        suggestions = []
        bottlenecks = self.analyze_bottlenecks()
        
        if "页面加载" in bottlenecks:
            suggestions.append("考虑增加页面加载超时时间或优化网络配置")
        
        if "滚动效率" in bottlenecks:
            suggestions.append("调整滚动策略，增加滚动间隔时间")
            suggestions.append("检查页面是否存在懒加载机制")
        
        if "点击成功率" in bottlenecks:
            suggestions.append("更新元素选择器，确保准确定位")
            suggestions.append("增加元素可见性检查")
        
        if "内存使用" in bottlenecks:
            suggestions.append("定期清理不必要的页面元素")
            suggestions.append("考虑分批处理大量数据")
        
        if "CPU使用" in bottlenecks:
            suggestions.append("增加操作间隔时间")
            suggestions.append("优化循环和递归算法")
        
        if not suggestions:
            suggestions.append("当前性能表现良好，无需特别优化")
        
        return suggestions