import os
import shutil
import asyncio
from pathlib import Path
from typing import Optional, Tuple
from dotenv import load_dotenv
from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright
from playwright.async_api import async_playwright, Browser as AsyncBrowser, BrowserContext as AsyncBrowserContext, Page as AsyncPage

load_dotenv()

class PlaywrightConfig:
    """Playwright基础配置类，提供同步和异步浏览器管理"""
    
    def __init__(self, user_data_dir: Optional[str] = None, headless: Optional[bool] = None):
        self.script_dir = Path(__file__).resolve().parent
        self.user_data_dir = Path(user_data_dir) if user_data_dir else self.script_dir / "playwright_user_data"
        
        # 自动检测无头模式
        if headless is None:
            ci_value = os.getenv("CI")
            self.headless = str(ci_value).lower() == "true" if ci_value is not None else False
        else:
            self.headless = headless
            
        # 同步实例
        self._playwright_instance: Optional[Playwright] = None
        self._browser_context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        
        # 页面池管理
        self._page_pool = {}
        self._page_counter = 0
        
    def cleanup_browser_locks(self):
        """清理可能存在的浏览器锁文件"""
        try:
            singleton_lock = self.user_data_dir / "SingletonLock"
            singleton_socket = self.user_data_dir / "SingletonSocket"
            singleton_cookie = self.user_data_dir / "SingletonCookie"
            
            # 删除可能存在的锁文件
            for lock_file in [singleton_lock, singleton_socket, singleton_cookie]:
                if lock_file.exists():
                    print(f"删除锁文件: {lock_file}")
                    lock_file.unlink()
                    
        except Exception as e:
            print(f"清理锁文件时出错: {e}")
    
    def get_browser_args(self):
        """获取浏览器启动参数"""
        return [
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
            "--start-maximized",
            "--disable-dev-shm-usage",
            "--disable-gpu",
        ]
    
    def initialize_browser(self) -> bool:
        """初始化同步浏览器实例"""
        # 检测是否在 asyncio 循环中（仅在主线程中检测）
        import threading
        current_thread = threading.current_thread()
        is_main_thread = isinstance(current_thread, threading._MainThread)
        
        if is_main_thread:
            try:
                loop = asyncio.get_running_loop()
                if loop.is_running():
                    print("检测到 asyncio 循环正在运行，无法使用同步 Playwright API")
                    print("请在非 asyncio 环境中使用，或使用异步版本")
                    return False
            except RuntimeError:
                # 没有运行的事件循环，可以安全使用同步 API
                pass
        else:
            # 在子线程中，不检测 asyncio 循环
            print(f"在子线程 {current_thread.name} 中初始化浏览器")
        
        # 清理之前的实例
        self.cleanup_sync_browser()
        
        try:
            print(f"初始化 Playwright 浏览器... 用户数据目录: {self.user_data_dir}")
            
            # 清理锁文件
            self.cleanup_browser_locks()
            
            print(f"环境检测: CI={os.getenv('CI')}, 无头模式={self.headless}")
            
            # 启动 Playwright 同步实例
            self._playwright_instance = sync_playwright().start()
            
            # 启动持久化上下文
            self._browser_context = self._playwright_instance.chromium.launch_persistent_context(
                user_data_dir=self.user_data_dir,
                headless=self.headless,
                ignore_https_errors=True,
                args=self.get_browser_args(),
            )
            
            # 获取或创建页面
            if not self._browser_context.pages:
                self._page = self._browser_context.new_page()
            else:
                self._page = self._browser_context.pages[0]
            
            # 设置页面大小
            self._page.set_viewport_size({"width": 1280, "height": 800})
            
            print("Playwright 浏览器初始化成功！")
            return True
            
        except Exception as e:
            print(f"Playwright 浏览器初始化失败: {e}")
            
            # 处理锁文件问题
            if "ProcessSingleton" in str(e) or "SingletonLock" in str(e):
                print("检测到进程单例锁问题，尝试强制清理用户数据目录...")
                try:
                    if self.user_data_dir.exists():
                        print(f"完全清理用户数据目录: {self.user_data_dir}")
                        shutil.rmtree(self.user_data_dir)
                        self.user_data_dir.mkdir(parents=True, exist_ok=True)
                        print("用户数据目录已重建，请重新运行程序")
                except Exception as cleanup_error:
                    print(f"清理用户数据目录失败: {cleanup_error}")
            
            self.cleanup_sync_browser()
            return False
    
    def cleanup_sync_browser(self):
        """清理同步浏览器实例"""
        if self._browser_context is not None:
            try:
                self._browser_context.close()
            except:
                pass
            self._browser_context = None
        
        if self._playwright_instance is not None:
            try:
                self._playwright_instance.stop()
            except:
                pass
            self._playwright_instance = None
        
        self._page = None
        self._page_pool.clear()
        self._page_counter = 0
    
    def create_new_page(self) -> Tuple[Optional[str], Optional[Page]]:
        """创建新页面"""
        if self._browser_context is None:
            if not self.initialize_browser():
                return None, None
        
        try:
            # 检查浏览器上下文是否有效
            if hasattr(self._browser_context, '_is_closed') and self._browser_context._is_closed:
                print("检测到浏览器上下文已关闭，重新初始化...")
                if not self.initialize_browser():
                    return None, None
            
            # 创建新页面
            new_page = self._browser_context.new_page()
            new_page.set_viewport_size({"width": 1280, "height": 800})
            
            # 分配页面ID
            self._page_counter += 1
            page_id = f"page_{self._page_counter}"
            
            # 存储到页面池
            self._page_pool[page_id] = new_page
            
            print(f"创建新页面: {page_id}")
            return page_id, new_page
            
        except Exception as e:
            print(f"创建新页面失败: {e}")
            return None, None
    
    def get_page(self, page_id: Optional[str] = None) -> Optional[Page]:
        """获取页面实例"""
        if page_id is None:
            return self._page
        
        return self._page_pool.get(page_id)
    
    def close_page(self, page_id: str) -> bool:
        """关闭指定页面"""
        if page_id in self._page_pool:
            try:
                self._page_pool[page_id].close()
                del self._page_pool[page_id]
                print(f"页面 {page_id} 已关闭")
                return True
            except Exception as e:
                print(f"关闭页面 {page_id} 失败: {e}")
                return False
        return False
    
    def get_default_page(self) -> Optional[Page]:
        """获取默认页面"""
        if self._page is None and self._browser_context is None:
            self.initialize_browser()
        return self._page
    
    def quit_browser(self):
        """关闭浏览器"""
        # 关闭所有页面池中的页面
        for page_id in list(self._page_pool.keys()):
            self.close_page(page_id)
        
        self.cleanup_sync_browser()
        self.cleanup_browser_locks()
        print("浏览器已关闭")
    
    def close(self):
        """关闭浏览器（quit_browser的别名）"""
        self.quit_browser()
    
    @staticmethod
    async def create_async_browser(headless: Optional[bool] = None, user_data_dir: Optional[str] = None) -> AsyncBrowser:
        """创建异步浏览器实例"""
        if headless is None:
            ci_value = os.getenv("CI")
            headless = str(ci_value).lower() == "true" if ci_value is not None else True
        
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(
            headless=headless,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-accelerated-2d-canvas',
                '--no-first-run',
                '--no-zygote',
                '--disable-gpu'
            ]
        )
        return browser
    
    @staticmethod
    async def create_async_context_and_page(browser: AsyncBrowser) -> Tuple[AsyncBrowserContext, AsyncPage]:
        """创建异步浏览器上下文和页面"""
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        )
        page = await context.new_page()
        return context, page


# 全局配置实例
playwright_config = PlaywrightConfig()

# 便捷函数
def get_default_page() -> Optional[Page]:
    """获取默认页面的便捷函数"""
    return playwright_config.get_default_page()

def create_new_page() -> Tuple[Optional[str], Optional[Page]]:
    """创建新页面的便捷函数"""
    return playwright_config.create_new_page()

def close_page(page_id: str) -> bool:
    """关闭页面的便捷函数"""
    return playwright_config.close_page(page_id)

def quit_browser():
    """关闭浏览器的便捷函数"""
    playwright_config.quit_browser()