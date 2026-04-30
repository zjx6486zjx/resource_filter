"""
智能爬虫模块 - 使用多种策略定位元素，不依赖硬编码class
使用持久化上下文保持登录状态
"""
import asyncio
import re
import time
from dataclasses import dataclass
from typing import List, Optional, Callable, Any
from datetime import datetime
from pathlib import Path

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import Page as SyncPage, TimeoutError as SyncTimeoutError


@dataclass
class ElementStrategy:
    """元素定位策略"""
    name: str
    selector: str
    strategy_type: str = "css"  # css, xpath, text, js
    priority: int = 1


class SmartElementFinder:
    """智能元素查找器 - 支持多种定位策略"""
    
    def __init__(self, page):
        self.page = page
        self.is_async = hasattr(page, 'query_selector')
    
    async def find_element_async(self, strategies: List[ElementStrategy], timeout: int = 5000) -> Optional[Any]:
        """异步查找元素，尝试多种策略"""
        for strategy in sorted(strategies, key=lambda x: x.priority):
            try:
                if strategy.strategy_type == "css":
                    element = await self.page.query_selector(strategy.selector)
                elif strategy.strategy_type == "xpath":
                    element = await self.page.query_selector(f"xpath={strategy.selector}")
                elif strategy.strategy_type == "text":
                    element = await self.page.get_by_text(strategy.selector).first
                else:
                    continue
                    
                if element:
                    # 验证元素是否可见和可操作
                    is_visible = await element.is_visible()
                    if is_visible:
                        print(f"✓ 找到元素 [{strategy.name}]: {strategy.selector}")
                        return element
            except Exception as e:
                print(f"  策略 [{strategy.name}] 失败: {e}")
                continue
        return None
    
    def find_element_sync(self, strategies: List[ElementStrategy], timeout: int = 5000) -> Optional[Any]:
        """同步查找元素，尝试多种策略"""
        for strategy in sorted(strategies, key=lambda x: x.priority):
            try:
                if strategy.strategy_type == "css":
                    element = self.page.query_selector(strategy.selector)
                elif strategy.strategy_type == "xpath":
                    element = self.page.query_selector(f"xpath={strategy.selector}")
                else:
                    continue
                    
                if element:
                    is_visible = element.is_visible()
                    if is_visible:
                        print(f"✓ 找到元素 [{strategy.name}]: {strategy.selector}")
                        return element
            except Exception as e:
                print(f"  策略 [{strategy.name}] 失败: {e}")
                continue
        return None
    
    async def find_elements_async(self, strategy: ElementStrategy) -> List[Any]:
        """异步查找多个元素"""
        try:
            if strategy.strategy_type == "css":
                return await self.page.query_selector_all(strategy.selector)
            return []
        except:
            return []
    
    def find_elements_sync(self, strategy: ElementStrategy) -> List[Any]:
        """同步查找多个元素"""
        try:
            if strategy.strategy_type == "css":
                return self.page.query_selector_all(strategy.selector)
            return []
        except:
            return []


class DoubaoSmartCrawler:
    """豆包智能爬虫 - 使用多种策略定位元素"""
    
    # 输入框定位策略
    INPUT_STRATEGIES = [
        ElementStrategy("data-testid", "textarea[data-testid='chat_input_input']", "css", 1),
        ElementStrategy("placeholder", "textarea[placeholder*='搜索']", "css", 2),
        ElementStrategy("placeholder2", "textarea[placeholder*='输入']", "css", 2),
        ElementStrategy("contenteditable", "[contenteditable='true']", "css", 3),
        ElementStrategy("any_textarea", "textarea", "css", 4),
    ]
    
    # 发送按钮定位策略
    SEND_BUTTON_STRATEGIES = [
        ElementStrategy("id", "#flow-end-msg-send", "css", 1),
        ElementStrategy("data-testid", "button[data-testid*='send']", "css", 2),
        ElementStrategy("aria-label", "button[aria-label*='发送']", "css", 2),
        ElementStrategy("submit", "button[type='submit']", "css", 3),
        ElementStrategy("last_button", "button:last-of-type", "css", 5),
    ]
    
    # 响应内容定位策略
    RESPONSE_STRATEGIES = [
        ElementStrategy("data-testid", "div[data-testid='message_text_content']", "css", 1),
        ElementStrategy("markdown", "[class*='markdown']", "css", 2),
        ElementStrategy("message", "[class*='message-content']", "css", 2),
        ElementStrategy("response", "[class*='response']", "css", 3),
        ElementStrategy("assistant", "[data-role='assistant']", "css", 3),
    ]
    
    def __init__(self, page: Page):
        self.page = page
        self.finder = SmartElementFinder(page)
        self.script_dir = Path(__file__).resolve().parent
    
    async def safe_goto(self, url: str, max_retries: int = 3) -> bool:
        """安全访问页面，带重试机制"""
        for i in range(max_retries):
            try:
                print(f"  尝试访问页面 (尝试 {i+1}/{max_retries})...")
                # 使用 domcontentloaded 而不是 networkidle，更宽松
                await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
                # 额外等待页面渲染
                await asyncio.sleep(3)
                print(f"  页面加载完成")
                return True
            except Exception as e:
                print(f"  页面加载失败: {e}")
                if i < max_retries - 1:
                    await asyncio.sleep(2 ** i)  # 指数退避
                else:
                    # 最后一次尝试，使用更宽松的策略
                    try:
                        await self.page.goto(url, wait_until="commit", timeout=30000)
                        await asyncio.sleep(5)
                        return True
                    except Exception as e2:
                        print(f"  最终尝试失败: {e2}")
                        return False
        return False
    
    async def check_login_status(self) -> bool:
        """检查是否已登录"""
        try:
            # 检查是否有登录按钮或需要登录的提示
            login_indicators = [
                "button:has-text('登录')",
                "button:has-text('Login')",
                "[class*='login']",
                "a[href*='login']",
            ]
            for selector in login_indicators:
                try:
                    element = await self.page.query_selector(selector)
                    if element and await element.is_visible():
                        print(f"⚠ 检测到未登录状态 (找到: {selector})")
                        return False
                except:
                    continue
            return True
        except:
            return True
    
    async def input_text(self, text: str) -> bool:
        """智能输入文本"""
        print(f"[豆包] 尝试输入: {text[:30]}...")
        
        element = await self.finder.find_element_async(self.INPUT_STRATEGIES)
        if not element:
            print("✗ 未找到输入框")
            return False
        
        try:
            # 点击获取焦点
            await element.click()
            await asyncio.sleep(0.5)
            
            # 清空并输入
            await element.fill("")
            await element.fill(text)
            print("✓ 输入成功")
            return True
        except Exception as e:
            print(f"✗ 输入失败: {e}")
            return False
    
    async def click_send(self) -> bool:
        """智能点击发送按钮"""
        print("[豆包] 尝试点击发送按钮...")
        
        element = await self.finder.find_element_async(self.SEND_BUTTON_STRATEGIES)
        if not element:
            print("✗ 未找到发送按钮")
            return False
        
        try:
            await element.scroll_into_view_if_needed()
            await element.click()
            print("✓ 点击发送成功")
            return True
        except Exception as e:
            print(f"✗ 点击失败: {e}")
            # 尝试JS点击
            try:
                await self.page.evaluate("""
                    const buttons = document.querySelectorAll('button');
                    const sendBtn = Array.from(buttons).find(b => 
                        b.textContent.includes('发送') || 
                        b.getAttribute('aria-label')?.includes('发送')
                    );
                    if (sendBtn) sendBtn.click();
                """)
                print("✓ JS点击发送成功")
                return True
            except:
                return False
    
    async def wait_for_response(self, timeout: int = 60) -> Optional[str]:
        """智能等待响应"""
        print(f"[豆包] 等待响应 (最长{timeout}秒)...")
        
        start_time = asyncio.get_event_loop().time()
        last_content = ""
        stable_count = 0
        
        while (asyncio.get_event_loop().time() - start_time) < timeout:
            try:
                # 尝试获取响应内容
                content = await self._get_response_content()
                if content and len(content) > 10:
                    if content == last_content:
                        stable_count += 1
                        if stable_count >= 3:  # 内容稳定3次认为完成
                            print(f"✓ 响应完成，长度: {len(content)}")
                            return content
                    else:
                        stable_count = 0
                        last_content = content
                        print(f"  内容更新中... 当前长度: {len(content)}")
                
                await asyncio.sleep(2)
            except Exception as e:
                await asyncio.sleep(1)
        
        print(f"⚠ 等待超时，返回最后获取的内容")
        return last_content if last_content else None
    
    async def _get_response_content(self) -> Optional[str]:
        """获取响应内容"""
        from bs4 import BeautifulSoup
        
        try:
            content = await self.page.content()
            soup = BeautifulSoup(content, "html.parser")
            
            # 尝试多种策略找到响应内容
            for strategy in self.RESPONSE_STRATEGIES:
                try:
                    if strategy.strategy_type == "css":
                        elements = soup.select(strategy.selector)
                        if elements:
                            # 获取最后一个响应（最新的）
                            last_elem = elements[-1]
                            text = last_elem.get_text(separator="\n", strip=True)
                            if len(text) > 20:
                                return text
                except:
                    continue
            
            return None
        except:
            return None
    
    async def search(self, query: str) -> Optional[str]:
        """执行完整搜索流程"""
        print(f"\n{'='*60}")
        print(f"[豆包] 开始搜索: {query[:50]}...")
        print(f"{'='*60}")
        
        # 访问页面
        if not await self.safe_goto("https://www.doubao.com/chat/search"):
            return None
        
        # 检查登录状态
        is_logged_in = await self.check_login_status()
        if not is_logged_in:
            print("⚠ 豆包需要登录，请先在浏览器中登录")
            # 等待用户登录（最多等待60秒）
            for i in range(12):
                await asyncio.sleep(5)
                is_logged_in = await self.check_login_status()
                if is_logged_in:
                    print("✓ 检测到已登录")
                    break
                print(f"  等待登录... ({i+1}/60秒)")
            if not is_logged_in:
                print("✗ 登录超时，跳过豆包")
                return None
        
        # 输入文本
        if not await self.input_text(query):
            return None
        
        await asyncio.sleep(1)
        
        # 点击发送
        if not await self.click_send():
            return None
        
        # 等待响应
        result = await self.wait_for_response(timeout=60)
        
        if result:
            print(f"\n✓ 搜索成功，获取内容长度: {len(result)}")
        else:
            print("\n✗ 搜索失败，未获取到内容")
        
        return result


class ZhipuSmartCrawler:
    """智谱智能爬虫 - 使用多种策略定位元素"""
    
    # 输入框定位策略
    INPUT_STRATEGIES = [
        ElementStrategy("id", "textarea#chat-input", "css", 1),
        ElementStrategy("data-testid", "textarea[data-testid*='input']", "css", 2),
        ElementStrategy("placeholder", "textarea[placeholder*='输入']", "css", 2),
        ElementStrategy("contenteditable", "[contenteditable='true']", "css", 3),
        ElementStrategy("any_textarea", "textarea", "css", 4),
    ]
    
    # Web搜索按钮定位策略
    WEB_SEARCH_STRATEGIES = [
        ElementStrategy("aria-label", "[aria-label='Web Search']", "css", 1),
        ElementStrategy("aria-label-zh", "[aria-label*='网络']", "css", 1),
        ElementStrategy("data-testid", "[data-testid*='web']", "css", 2),
        ElementStrategy("button-text", "button:has-text('Search')", "css", 3),
        ElementStrategy("icon", "[class*='search']", "css", 4),
    ]
    
    # 发送按钮定位策略
    SEND_BUTTON_STRATEGIES = [
        ElementStrategy("id", "button#send-message-button", "css", 1),
        ElementStrategy("data-testid", "button[data-testid*='send']", "css", 2),
        ElementStrategy("aria-label", "button[aria-label*='Send']", "css", 2),
        ElementStrategy("submit", "button[type='submit']", "css", 3),
        ElementStrategy("last_button", "button:last-of-type", "css", 5),
    ]
    
    # 响应内容定位策略
    RESPONSE_STRATEGIES = [
        ElementStrategy("id", "div#response-content-container", "css", 1),
        ElementStrategy("data-testid", "[data-testid*='response']", "css", 2),
        ElementStrategy("message", "[class*='message-content']", "css", 2),
        ElementStrategy("markdown", "[class*='markdown']", "css", 3),
        ElementStrategy("assistant", "[data-role='assistant']", "css", 3),
    ]
    
    def __init__(self, page: Page):
        self.page = page
        self.finder = SmartElementFinder(page)
        self.script_dir = Path(__file__).resolve().parent
    
    async def safe_goto(self, url: str, max_retries: int = 3) -> bool:
        """安全访问页面，带重试机制"""
        for i in range(max_retries):
            try:
                print(f"  尝试访问页面 (尝试 {i+1}/{max_retries})...")
                await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(3)
                print(f"  页面加载完成")
                return True
            except Exception as e:
                print(f"  页面加载失败: {e}")
                if i < max_retries - 1:
                    await asyncio.sleep(2 ** i)
                else:
                    try:
                        await self.page.goto(url, wait_until="commit", timeout=30000)
                        await asyncio.sleep(5)
                        return True
                    except Exception as e2:
                        print(f"  最终尝试失败: {e2}")
                        return False
        return False
    
    async def input_text(self, text: str) -> bool:
        """智能输入文本"""
        print(f"[智谱] 尝试输入: {text[:30]}...")
        
        element = await self.finder.find_element_async(self.INPUT_STRATEGIES)
        if not element:
            print("✗ 未找到输入框")
            return False
        
        try:
            await element.click()
            await asyncio.sleep(0.5)
            await element.fill("")
            await element.fill(text)
            print("✓ 输入成功")
            return True
        except Exception as e:
            print(f"✗ 输入失败: {e}")
            return False
    
    async def enable_web_search(self) -> bool:
        """启用Web搜索"""
        print("[智谱] 尝试启用Web搜索...")
        
        element = await self.finder.find_element_async(self.WEB_SEARCH_STRATEGIES)
        if not element:
            print("⚠ 未找到Web搜索按钮，可能已默认启用")
            return True  # 不强制要求
        
        try:
            # 检查是否已经启用
            is_checked = await element.evaluate("""
                el => {
                    const input = el.querySelector('input');
                    return input ? input.checked : el.getAttribute('aria-pressed') === 'true';
                }
            """)
            
            if is_checked:
                print("✓ Web搜索已启用")
                return True
            
            await element.click()
            print("✓ Web搜索启用成功")
            return True
        except Exception as e:
            print(f"⚠ Web搜索启用失败: {e}")
            return True  # 不强制要求
    
    async def click_send(self) -> bool:
        """智能点击发送按钮"""
        print("[智谱] 尝试点击发送按钮...")
        
        element = await self.finder.find_element_async(self.SEND_BUTTON_STRATEGIES)
        if not element:
            print("✗ 未找到发送按钮，尝试键盘发送")
            try:
                await self.page.keyboard.press("Enter")
                print("✓ 键盘发送成功")
                return True
            except:
                return False
        
        try:
            await element.scroll_into_view_if_needed()
            await element.click()
            print("✓ 点击发送成功")
            return True
        except Exception as e:
            print(f"✗ 点击失败: {e}")
            return False
    
    async def wait_for_response(self, timeout: int = 60) -> Optional[str]:
        """智能等待响应"""
        print(f"[智谱] 等待响应 (最长{timeout}秒)...")
        
        start_time = asyncio.get_event_loop().time()
        last_content = ""
        stable_count = 0
        
        while (asyncio.get_event_loop().time() - start_time) < timeout:
            try:
                content = await self._get_response_content()
                if content and len(content) > 10:
                    if content == last_content:
                        stable_count += 1
                        if stable_count >= 3:
                            print(f"✓ 响应完成，长度: {len(content)}")
                            return content
                    else:
                        stable_count = 0
                        last_content = content
                        print(f"  内容更新中... 当前长度: {len(content)}")
                
                await asyncio.sleep(2)
            except Exception as e:
                await asyncio.sleep(1)
        
        return last_content if last_content else None
    
    async def _get_response_content(self) -> Optional[str]:
        """获取响应内容"""
        from bs4 import BeautifulSoup
        
        try:
            content = await self.page.content()
            soup = BeautifulSoup(content, "html.parser")
            
            for strategy in self.RESPONSE_STRATEGIES:
                try:
                    if strategy.strategy_type == "css":
                        elements = soup.select(strategy.selector)
                        if elements:
                            last_elem = elements[-1]
                            text = last_elem.get_text(separator="\n", strip=True)
                            if len(text) > 20:
                                return text
                except:
                    continue
            
            return None
        except:
            return None
    
    async def search(self, query: str) -> Optional[str]:
        """执行完整搜索流程"""
        print(f"\n{'='*60}")
        print(f"[智谱] 开始搜索: {query[:50]}...")
        print(f"{'='*60}")
        
        # 访问页面
        if not await self.safe_goto("https://chat.z.ai/"):
            return None
        
        # 输入文本
        if not await self.input_text(query):
            return None
        
        await asyncio.sleep(1)
        
        # 启用Web搜索
        await self.enable_web_search()
        
        await asyncio.sleep(1)
        
        # 点击发送
        if not await self.click_send():
            return None
        
        # 等待响应
        result = await self.wait_for_response(timeout=60)
        
        if result:
            print(f"\n✓ 搜索成功，获取内容长度: {len(result)}")
        else:
            print("\n✗ 搜索失败，未获取到内容")
        
        return result


# ==================== 同步版本 ====================

class SyncSmartElementFinder:
    """同步智能元素查找器"""
    
    def __init__(self, page: SyncPage):
        self.page = page
    
    def find_element(self, strategies: List[ElementStrategy], timeout: int = 5000) -> Optional[Any]:
        """同步查找元素"""
        for strategy in sorted(strategies, key=lambda x: x.priority):
            try:
                if strategy.strategy_type == "css":
                    element = self.page.query_selector(strategy.selector)
                elif strategy.strategy_type == "xpath":
                    element = self.page.query_selector(f"xpath={strategy.selector}")
                else:
                    continue
                    
                if element and element.is_visible():
                    print(f"✓ 找到元素 [{strategy.name}]: {strategy.selector}")
                    return element
            except Exception as e:
                continue
        return None


class SyncDoubaoCrawler:
    """豆包同步智能爬虫"""
    
    INPUT_STRATEGIES = [
        ElementStrategy("data-testid", "textarea[data-testid='chat_input_input']", "css", 1),
        ElementStrategy("placeholder", "textarea[placeholder*='搜索']", "css", 2),
        ElementStrategy("placeholder2", "textarea[placeholder*='输入']", "css", 2),
        ElementStrategy("contenteditable", "[contenteditable='true']", "css", 3),
        ElementStrategy("any_textarea", "textarea", "css", 4),
    ]
    
    SEND_BUTTON_STRATEGIES = [
        ElementStrategy("id", "#flow-end-msg-send", "css", 1),
        ElementStrategy("data-testid", "button[data-testid*='send']", "css", 2),
        ElementStrategy("aria-label", "button[aria-label*='发送']", "css", 2),
        ElementStrategy("submit", "button[type='submit']", "css", 3),
        ElementStrategy("last_button", "button:last-of-type", "css", 5),
    ]
    
    def __init__(self, page: SyncPage):
        self.page = page
        self.finder = SyncSmartElementFinder(page)
    
    def safe_goto(self, url: str, max_retries: int = 3) -> bool:
        """安全访问页面"""
        for i in range(max_retries):
            try:
                print(f"  尝试访问页面 (尝试 {i+1}/{max_retries})...")
                self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
                time.sleep(3)
                print(f"  页面加载完成")
                return True
            except Exception as e:
                print(f"  页面加载失败: {e}")
                if i < max_retries - 1:
                    time.sleep(2 ** i)
                else:
                    try:
                        self.page.goto(url, wait_until="commit", timeout=30000)
                        time.sleep(5)
                        return True
                    except Exception as e2:
                        print(f"  最终尝试失败: {e2}")
                        return False
        return False
    
    def check_login_status(self) -> bool:
        """检查是否已登录"""
        try:
            login_indicators = [
                "button:has-text('登录')",
                "button:has-text('Login')",
                "[class*='login']",
                "a[href*='login']",
            ]
            for selector in login_indicators:
                try:
                    element = self.page.query_selector(selector)
                    if element and element.is_visible():
                        print(f"⚠ 检测到未登录状态 (找到: {selector})")
                        return False
                except:
                    continue
            return True
        except:
            return True
    
    def input_text(self, text: str) -> bool:
        """同步输入文本"""
        print(f"[豆包] 尝试输入: {text[:30]}...")
        
        element = self.finder.find_element(self.INPUT_STRATEGIES)
        if not element:
            print("✗ 未找到输入框")
            return False
        
        try:
            element.click()
            time.sleep(0.5)
            element.fill("")
            element.fill(text)
            print("✓ 输入成功")
            return True
        except Exception as e:
            print(f"✗ 输入失败: {e}")
            return False
    
    def click_send(self) -> bool:
        """同步点击发送"""
        print("[豆包] 尝试点击发送按钮...")
        
        element = self.finder.find_element(self.SEND_BUTTON_STRATEGIES)
        if not element:
            print("✗ 未找到发送按钮")
            return False
        
        try:
            element.scroll_into_view_if_needed()
            element.click()
            print("✓ 点击发送成功")
            return True
        except Exception as e:
            print(f"✗ 点击失败: {e}")
            return False
    
    def search(self, query: str) -> Optional[str]:
        """同步执行搜索"""
        print(f"\n{'='*60}")
        print(f"[豆包] 开始搜索: {query[:50]}...")
        print(f"{'='*60}")
        
        if not self.safe_goto("https://www.doubao.com/chat/search"):
            return None
        
        # 检查登录状态
        is_logged_in = self.check_login_status()
        if not is_logged_in:
            print("⚠ 豆包需要登录，请先在浏览器中登录")
            # 等待用户登录（最多等待60秒）
            for i in range(12):
                time.sleep(5)
                is_logged_in = self.check_login_status()
                if is_logged_in:
                    print("✓ 检测到已登录")
                    break
                print(f"  等待登录... ({(i+1)*5}/60秒)")
            if not is_logged_in:
                print("✗ 登录超时，跳过豆包")
                return None
        
        if not self.input_text(query):
            return None
        
        time.sleep(1)
        
        if not self.click_send():
            return None
        
        print("[豆包] 等待响应...")
        time.sleep(30)
        
        try:
            from bs4 import BeautifulSoup
            content = self.page.content()
            soup = BeautifulSoup(content, "html.parser")
            
            selectors = [
                "div[data-testid='message_text_content']",
                "[class*='markdown']",
                "[class*='message-content']",
            ]
            
            for selector in selectors:
                elements = soup.select(selector)
                if elements:
                    text = elements[-1].get_text(separator="\n", strip=True)
                    if len(text) > 20:
                        print(f"✓ 获取内容成功，长度: {len(text)}")
                        return text
            
            return None
        except Exception as e:
            print(f"✗ 获取内容失败: {e}")
            return None


class SyncZhipuCrawler:
    """智谱同步智能爬虫"""
    
    INPUT_STRATEGIES = [
        ElementStrategy("id", "textarea#chat-input", "css", 1),
        ElementStrategy("data-testid", "textarea[data-testid*='input']", "css", 2),
        ElementStrategy("placeholder", "textarea[placeholder*='输入']", "css", 2),
        ElementStrategy("contenteditable", "[contenteditable='true']", "css", 3),
        ElementStrategy("any_textarea", "textarea", "css", 4),
    ]
    
    WEB_SEARCH_STRATEGIES = [
        ElementStrategy("aria-label", "[aria-label='Web Search']", "css", 1),
        ElementStrategy("aria-label-zh", "[aria-label*='网络']", "css", 1),
        ElementStrategy("data-testid", "[data-testid*='web']", "css", 2),
    ]
    
    SEND_BUTTON_STRATEGIES = [
        ElementStrategy("id", "button#send-message-button", "css", 1),
        ElementStrategy("data-testid", "button[data-testid*='send']", "css", 2),
        ElementStrategy("aria-label", "button[aria-label*='Send']", "css", 2),
        ElementStrategy("submit", "button[type='submit']", "css", 3),
        ElementStrategy("last_button", "button:last-of-type", "css", 5),
    ]
    
    def __init__(self, page: SyncPage):
        self.page = page
        self.finder = SyncSmartElementFinder(page)
    
    def safe_goto(self, url: str, max_retries: int = 3) -> bool:
        """安全访问页面"""
        for i in range(max_retries):
            try:
                print(f"  尝试访问页面 (尝试 {i+1}/{max_retries})...")
                self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
                time.sleep(3)
                print(f"  页面加载完成")
                return True
            except Exception as e:
                print(f"  页面加载失败: {e}")
                if i < max_retries - 1:
                    time.sleep(2 ** i)
                else:
                    try:
                        self.page.goto(url, wait_until="commit", timeout=30000)
                        time.sleep(5)
                        return True
                    except Exception as e2:
                        print(f"  最终尝试失败: {e2}")
                        return False
        return False
    
    def input_text(self, text: str) -> bool:
        """同步输入文本"""
        print(f"[智谱] 尝试输入: {text[:30]}...")
        
        element = self.finder.find_element(self.INPUT_STRATEGIES)
        if not element:
            print("✗ 未找到输入框")
            return False
        
        try:
            element.click()
            time.sleep(0.5)
            element.fill("")
            element.fill(text)
            print("✓ 输入成功")
            return True
        except Exception as e:
            print(f"✗ 输入失败: {e}")
            return False
    
    def enable_web_search(self) -> bool:
        """同步启用Web搜索"""
        print("[智谱] 尝试启用Web搜索...")
        
        element = self.finder.find_element(self.WEB_SEARCH_STRATEGIES)
        if not element:
            print("⚠ 未找到Web搜索按钮")
            return True
        
        try:
            element.click()
            print("✓ Web搜索启用成功")
            return True
        except:
            return True
    
    def click_send(self) -> bool:
        """同步点击发送"""
        print("[智谱] 尝试点击发送按钮...")
        
        element = self.finder.find_element(self.SEND_BUTTON_STRATEGIES)
        if not element:
            print("✗ 未找到发送按钮，尝试键盘发送")
            try:
                self.page.keyboard.press("Enter")
                print("✓ 键盘发送成功")
                return True
            except:
                return False
        
        try:
            element.scroll_into_view_if_needed()
            element.click()
            print("✓ 点击发送成功")
            return True
        except Exception as e:
            print(f"✗ 点击失败: {e}")
            return False
    
    def search(self, query: str) -> Optional[str]:
        """同步执行搜索"""
        print(f"\n{'='*60}")
        print(f"[智谱] 开始搜索: {query[:50]}...")
        print(f"{'='*60}")
        
        if not self.safe_goto("https://chat.z.ai/"):
            return None
        
        if not self.input_text(query):
            return None
        
        time.sleep(1)
        self.enable_web_search()
        time.sleep(1)
        
        if not self.click_send():
            return None
        
        print("[智谱] 等待响应...")
        time.sleep(30)
        
        try:
            from bs4 import BeautifulSoup
            content = self.page.content()
            soup = BeautifulSoup(content, "html.parser")
            
            selectors = [
                "div#response-content-container",
                "[data-testid*='response']",
                "[class*='message-content']",
            ]
            
            for selector in selectors:
                elements = soup.select(selector)
                if elements:
                    text = elements[-1].get_text(separator="\n", strip=True)
                    if len(text) > 20:
                        print(f"✓ 获取内容成功，长度: {len(text)}")
                        return text
            
            return None
        except Exception as e:
            print(f"✗ 获取内容失败: {e}")
            return None


# ==================== 使用持久化上下文的便捷函数 ====================

SCRIPT_DIR = Path(__file__).resolve().parent
USER_DATA_DIR = SCRIPT_DIR.parent / "playwright_user_data"


async def smart_web_search_async(query: str, headless: bool = False) -> Optional[str]:
    """异步智能搜索入口 - 使用持久化上下文保持登录状态"""
    from playwright.async_api import async_playwright
    
    async with async_playwright() as p:
        # 使用持久化上下文，保持登录状态
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(USER_DATA_DIR),
            headless=headless,
            ignore_https_errors=True,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-blink-features=AutomationControlled',
                '--disable-infobars'
            ]
        )
        
        # 获取或创建页面
        if not context.pages:
            page = await context.new_page()
        else:
            page = context.pages[0]
        
        try:
            import random
            platforms = [
                ("智谱", ZhipuSmartCrawler),
                ("豆包", DoubaoSmartCrawler),
            ]
            random.shuffle(platforms)
            
            for name, CrawlerClass in platforms:
                print(f"\n尝试使用 {name} 平台...")
                crawler = CrawlerClass(page)
                result = await crawler.search(query)
                if result:
                    await context.close()
                    return result
        except Exception as e:
            print(f"搜索失败: {e}")
        finally:
            try:
                await context.close()
            except:
                pass
        
        return None


def smart_web_search_sync(query: str, headless: bool = False) -> Optional[str]:
    """同步智能搜索入口 - 使用持久化上下文保持登录状态"""
    from playwright.sync_api import sync_playwright
    
    with sync_playwright() as p:
        # 使用持久化上下文，保持登录状态
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(USER_DATA_DIR),
            headless=headless,
            ignore_https_errors=True,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-blink-features=AutomationControlled',
                '--disable-infobars'
            ]
        )
        
        # 获取或创建页面
        if not context.pages:
            page = context.new_page()
        else:
            page = context.pages[0]
        
        try:
            import random
            platforms = [
                ("智谱", SyncZhipuCrawler),
                ("豆包", SyncDoubaoCrawler),
            ]
            random.shuffle(platforms)
            
            for name, CrawlerClass in platforms:
                print(f"\n尝试使用 {name} 平台...")
                crawler = CrawlerClass(page)
                result = crawler.search(query)
                if result:
                    context.close()
                    return result
        except Exception as e:
            print(f"搜索失败: {e}")
        finally:
            try:
                context.close()
            except:
                pass
        
        return None


if __name__ == "__main__":
    # 测试
    test_query = "万鹏最近有什么动向"
    
    print("\n" + "="*60)
    print("测试智能爬虫")
    print("="*60)
    
    # 异步测试
    result = asyncio.run(smart_web_search_async(test_query, headless=False))
    if result:
        print(f"\n搜索结果:\n{result[:500]}...")
    else:
        print("\n搜索失败")
