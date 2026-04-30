#!/usr/bin/env python3
"""
爬虫异常处理模块
定义专用异常类和重试机制
"""

import time
import functools
from typing import Callable, Any, Optional, Tuple, Type
from enum import Enum

class CrawlerErrorType(Enum):
    """爬虫错误类型枚举"""
    NETWORK_ERROR = "network_error"
    DOM_ERROR = "dom_error"
    TIMEOUT_ERROR = "timeout_error"
    ELEMENT_NOT_FOUND = "element_not_found"
    SCROLL_ERROR = "scroll_error"
    CLICK_ERROR = "click_error"
    PAGE_LOAD_ERROR = "page_load_error"
    UNKNOWN_ERROR = "unknown_error"

class CrawlerException(Exception):
    """爬虫基础异常类"""
    
    def __init__(self, message: str, error_type: CrawlerErrorType = CrawlerErrorType.UNKNOWN_ERROR, 
                 original_error: Optional[Exception] = None):
        super().__init__(message)
        self.error_type = error_type
        self.original_error = original_error
        self.timestamp = time.time()
    
    def __str__(self):
        return f"[{self.error_type.value}] {super().__str__()}"

class ElementNotFoundError(CrawlerException):
    """元素未找到异常"""
    
    def __init__(self, selector: str, message: str = None):
        self.selector = selector
        msg = message or f"未找到元素: {selector}"
        super().__init__(msg, CrawlerErrorType.ELEMENT_NOT_FOUND)

class DOMError(CrawlerException):
    """DOM相关异常"""
    
    def __init__(self, message: str, original_error: Optional[Exception] = None):
        super().__init__(message, CrawlerErrorType.DOM_ERROR, original_error)

class ScrollError(CrawlerException):
    """滚动相关异常"""
    
    def __init__(self, message: str, original_error: Optional[Exception] = None):
        super().__init__(message, CrawlerErrorType.SCROLL_ERROR, original_error)

class ClickError(CrawlerException):
    """点击相关异常"""
    
    def __init__(self, message: str, card_index: Optional[int] = None, 
                 original_error: Optional[Exception] = None):
        self.card_index = card_index
        super().__init__(message, CrawlerErrorType.CLICK_ERROR, original_error)

class PageLoadError(CrawlerException):
    """页面加载异常"""
    
    def __init__(self, url: str, message: str = None, original_error: Optional[Exception] = None):
        self.url = url
        msg = message or f"页面加载失败: {url}"
        super().__init__(msg, CrawlerErrorType.PAGE_LOAD_ERROR, original_error)

def retry_on_exception(max_retries: int = 3, 
                      delay: float = 1.0, 
                      backoff: float = 2.0,
                      exceptions: Tuple[Type[Exception], ...] = (Exception,),
                      logger: Optional[Any] = None):
    """
    重试装饰器
    
    Args:
        max_retries: 最大重试次数
        delay: 初始延迟时间（秒）
        backoff: 延迟倍数
        exceptions: 需要重试的异常类型
        logger: 日志记录器
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            last_exception = None
            current_delay = delay
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    
                    if attempt == max_retries:
                        if logger:
                            logger.error(f"函数 {func.__name__} 重试 {max_retries} 次后仍然失败", error=e)
                        raise
                    
                    if logger:
                        logger.warning(f"函数 {func.__name__} 第 {attempt + 1} 次尝试失败，{current_delay:.1f}秒后重试", 
                                     error=str(e))
                    
                    time.sleep(current_delay)
                    current_delay *= backoff
            
            raise last_exception
        
        return wrapper
    return decorator

def safe_execute(func: Callable, 
                default_return: Any = None, 
                logger: Optional[Any] = None,
                error_message: str = None) -> Any:
    """
    安全执行函数，捕获异常并返回默认值
    
    Args:
        func: 要执行的函数
        default_return: 异常时的默认返回值
        logger: 日志记录器
        error_message: 自定义错误消息
    
    Returns:
        函数执行结果或默认值
    """
    try:
        return func()
    except Exception as e:
        if logger:
            msg = error_message or f"执行函数 {func.__name__} 时发生异常"
            logger.error(msg, error=e)
        return default_return

class ErrorHandler:
    """错误处理器"""
    
    def __init__(self, logger: Optional[Any] = None):
        self.logger = logger
        self.error_counts = {}
    
    def handle_error(self, error: Exception, context: str = "") -> CrawlerException:
        """
        处理错误，转换为爬虫专用异常
        
        Args:
            error: 原始异常
            context: 错误上下文
        
        Returns:
            转换后的爬虫异常
        """
        error_str = str(error).lower()
        
        # 根据错误信息判断错误类型
        if "timeout" in error_str:
            crawler_error = CrawlerException(
                f"操作超时: {context}", 
                CrawlerErrorType.TIMEOUT_ERROR, 
                error
            )
        elif "element is not attached to the dom" in error_str:
            crawler_error = DOMError(f"DOM元素已分离: {context}", error)
        elif "element is not visible" in error_str:
            crawler_error = DOMError(f"元素不可见: {context}", error)
        elif "scroll" in error_str:
            crawler_error = ScrollError(f"滚动失败: {context}", error)
        elif "click" in error_str:
            crawler_error = ClickError(f"点击失败: {context}", original_error=error)
        elif "network" in error_str or "connection" in error_str:
            crawler_error = CrawlerException(
                f"网络错误: {context}", 
                CrawlerErrorType.NETWORK_ERROR, 
                error
            )
        else:
            crawler_error = CrawlerException(f"未知错误: {context}", original_error=error)
        
        # 记录错误统计
        error_type = crawler_error.error_type.value
        self.error_counts[error_type] = self.error_counts.get(error_type, 0) + 1
        
        if self.logger:
            self.logger.error(f"错误处理: {crawler_error}", error=error)
        
        return crawler_error
    
    def get_error_stats(self) -> dict:
        """获取错误统计"""
        return self.error_counts.copy()
    
    def should_continue(self, error: CrawlerException, max_errors: int = 10) -> bool:
        """
        判断是否应该继续执行
        
        Args:
            error: 爬虫异常
            max_errors: 最大错误数量
        
        Returns:
            是否应该继续
        """
        total_errors = sum(self.error_counts.values())
        
        # 如果总错误数超过限制，停止执行
        if total_errors >= max_errors:
            if self.logger:
                self.logger.error(f"错误数量过多 ({total_errors})，停止执行")
            return False
        
        # 某些严重错误应该立即停止
        critical_errors = [
            CrawlerErrorType.PAGE_LOAD_ERROR,
            CrawlerErrorType.NETWORK_ERROR
        ]
        
        if error.error_type in critical_errors:
            if self.logger:
                self.logger.error(f"遇到严重错误 ({error.error_type.value})，停止执行")
            return False
        
        return True