import json
import os
import random
import re
import sys
import time
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import bs4
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from duckduckgo_search import DDGS
from html_deal import doubao_parse_html_to_string, zhipu_parse_html
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import TimeoutError as SyncPlaywrightTimeoutError
from tavily import TavilyClient

# 导入新的智能爬虫
from smart_crawler import (
    DoubaoSmartCrawler, ZhipuSmartCrawler,
    SyncDoubaoCrawler, SyncZhipuCrawler
)

# 导入配置类
sys.path.append(str(Path(__file__).resolve().parent.parent))
from playwright_config import PlaywrightConfig

load_dotenv()
SCRIPT_DIR = Path(__file__).resolve().parent


# ==================== 原有的工具函数 ====================

async def safe_get(page, url, max_retries=3):
    """带重试机制的页面加载 - 使用更宽松的策略"""
    for i in range(max_retries):
        try:
            # 使用 domcontentloaded 而不是 networkidle，更稳定
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)  # 等待页面渲染
            return True
        except PlaywrightTimeoutError as e:
            print(f"页面加载失败: {e}, 尝试刷新...")
            try:
                await page.reload()
                await asyncio.sleep(2**i)
            except:
                pass
    # 最后一次尝试使用最宽松的策略
    try:
        await page.goto(url, wait_until="commit", timeout=30000)
        await asyncio.sleep(5)
        return True
    except:
        return False


def get_original_content(query):
    t_client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
    result = t_client.search(query, search_depth="basic", topic="general", include_images=True)
    return result


def remove_citation_marks(text):
    text = re.sub(r"\[\s*\d{1,2}\s*\]", "", text)
    text = re.sub(r"Search Result Count: \d+", "", text)
    return text


async def wait_for_element(page, selector, timeout=30000):
    """显式等待元素出现"""
    try:
        await page.wait_for_selector(selector, timeout=timeout)
        return await page.query_selector(selector)
    except PlaywrightTimeoutError:
        return None


async def click_element(page, selector, timeout=30000):
    """增强版点击操作，优化无头模式兼容性"""
    try:
        element = await page.wait_for_selector(selector, timeout=timeout)
        if element:
            await element.scroll_into_view_if_needed()
            await element.click()
            return True
    except Exception as e:
        print(f"常规点击失败: {e}，尝试JS点击...")
        try:
            escaped_selector = selector.replace("'", "\\'")
            await page.evaluate(f"""
                const element = document.querySelector('{escaped_selector}');
                if (element) {{
                    element.scrollIntoView({{behavior: 'auto', block: 'center'}});
                    element.click();
                }}
            """)
            return True
        except Exception as js_e:
            print(f"JS点击失败: {js_e}")
            return False
    return False


@lru_cache(maxsize=128)
def search_with_ddgs(query, search_type="text", region="cn-zh", max_results=3):
    """带缓存的DuckDuckGo搜索"""
    try:
        ddgs = DDGS()
        search_func = getattr(ddgs, search_type)
        results = list(search_func(query, region=region, max_results=max_results))

        return [{"title": r["title"], "body": r["body"], "image": r.get("image", "")} for r in results]
    except Exception as e:
        print(f"搜索失败: {e}")
        return []


async def wait_for_page_ready(page, timeout=30000):
    """等待页面完全加载"""
    try:
        await page.wait_for_load_state("networkidle", timeout=timeout)
        await page.wait_for_selector(".message-content-container", timeout=timeout)
    except PlaywrightTimeoutError:
        print("页面加载超时")


# ==================== 新版智能爬虫流程 ====================

async def process_doubao_search_smart(page, search_text):
    """使用智能爬虫的豆包搜索流程"""
    crawler = DoubaoSmartCrawler(page)
    return await crawler.search(search_text)


async def process_zhipu_search_smart(page, search_text):
    """使用智能爬虫的智谱搜索流程"""
    crawler = ZhipuSmartCrawler(page)
    return await crawler.search(search_text)


# ==================== 保留旧版流程作为fallback ====================

async def process_doubao_search_legacy(page, search_text):
    """原有的豆包搜索流程（作为fallback）"""
    if not await safe_get(page, "https://www.doubao.com/chat/search"):
        return None
    
    input_selector = "textarea[data-testid='chat_input_input']"
    if not await click_element(page, input_selector):
        return None

    input_element = await wait_for_element(page, input_selector)
    if input_element:
        await input_element.fill(search_text)
    await asyncio.sleep(5)
    
    close_buttons = await page.query_selector_all("span.semi-icon-default[role='img'].cursor-pointer")
    if close_buttons:
        try:
            close_button = close_buttons[0]
            await close_button.scroll_into_view_if_needed()
            await close_button.click()
            
            try:
                await page.wait_for_selector(".modal-container", state="hidden", timeout=5000)
                print("弹窗关闭成功")
            except PlaywrightTimeoutError:
                print("弹窗关闭验证超时")
            
        except Exception as e:
            print(f"关闭失败: {e}")
            await page.screenshot(path="close_error.png")
    
    buttons = await page.query_selector_all("#flow-end-msg-send")
    print(f"找到 {len(buttons)} 个匹配的按钮")
    if len(buttons) > 1:
        for idx, btn in enumerate(buttons):
            box = await btn.bounding_box()
            if box:
                print(f"按钮 #{idx+1} 位置: {box}")
    
    button = await page.wait_for_selector("#flow-end-msg-send", timeout=10000)
    if not button:
        return None

    original_url = page.url
    print(f"当前 URL: {original_url}")

    await page.evaluate("""
        const button = document.querySelector('#flow-end-msg-send');
        if (button) {
            button.style.border = '3px solid red';
            button.style.backgroundColor = 'yellow';
        }
    """)
    await asyncio.sleep(1)
    await button.click()

    await asyncio.sleep(60)
    print(f"页面跳转到: {page.url}")
    try:
        await page.wait_for_selector(
            "div[data-testid='message_text_content'] > div.auto-hide-last-sibling-br",
            timeout=30000
        )
    except PlaywrightTimeoutError:
        print("动态内容加载超时")
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = SCRIPT_DIR / "error_pages" / f"error_page_{timestamp}.html"
        try:
            content = await page.content()
            with open(filename, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception as e:
            print(f"保存页面失败: {e}")
    
    content = await page.content()
    soup = BeautifulSoup(content, "html.parser")
    response_div = soup.find(
        "div", {"data-testid": "message_text_content", "class": "container-P2rR72 flow-markdown-body mdbox-theme-next theme-samantha-uDexJL"}
    )

    if response_div:
        html_content = str(response_div)
        parsed = doubao_parse_html_to_string(html_content)
        return parsed
    return None


async def process_zhipu_search_legacy(page, search_text):
    """原有的智谱搜索流程（作为fallback）"""
    if not await safe_get(page, "https://chat.z.ai/"):
        return None

    input_selector = "textarea#chat-input"
    web_search_btn_selector = "div[aria-label='Web Search'] > button"
    send_btn_selector = "button#send-message-button"

    await asyncio.sleep(2)
    
    if not await click_element(page, input_selector):
        print("输入框点击失败")
        return None
    
    input_element = await wait_for_element(page, input_selector)
    if input_element:
        await input_element.fill(search_text)
        print(f"已输入搜索内容: {search_text}")
    else:
        print("未找到输入框元素")
        return None
    
    await asyncio.sleep(1)
    
    web_search_selectors = [
        "div[aria-label='Web Search'] > button",
        "div[aria-label='Web Search'] button",
        "button[aria-label*='Web Search']",
        "[aria-label='Web Search']",
        "button[data-testid='web-search-button']",
        ".web-search-btn",
        "[title*='Web Search']",
        "[title*='网络搜索']"
    ]
    
    web_search_clicked = False
    for selector in web_search_selectors:
        print(f"尝试Web搜索按钮选择器: {selector}")
        element = await page.query_selector(selector)
        if element:
            print(f"找到Web搜索按钮: {selector}")
            if await click_element(page, selector, timeout=10000):
                print("Web搜索按钮点击成功")
                web_search_clicked = True
                break
        await asyncio.sleep(0.5)
    
    if not web_search_clicked:
        print("所有Web搜索按钮选择器都失败，尝试直接发送")

    screenshot_path = SCRIPT_DIR / "error_pages" / f"zhipu_search_{datetime.now().strftime('%Y%m%d-%H%M%S')}.png"
    await page.screenshot(path=str(screenshot_path))
    print(f"调试截图已保存: {screenshot_path}")
    
    send_selectors = [
        "button#send-message-button",
        "#send-message-button",
        "button[type='submit']",
        "button.sendMessageButton",
        "[aria-label*='Send']",
        "[aria-label*='发送']",
        "button[data-testid='send-button']",
        ".send-btn",
        "[title*='Send']",
        "[title*='发送']",
        "button:has-text('Send')",
        "button:has-text('发送')"
    ]
    
    send_clicked = False
    for selector in send_selectors:
        print(f"尝试发送按钮选择器: {selector}")
        element = await page.query_selector(selector)
        if element:
            print(f"找到发送按钮: {selector}")
            if await click_element(page, selector, timeout=10000):
                print("发送按钮点击成功")
                send_clicked = True
                break
        await asyncio.sleep(0.5)
    
    if not send_clicked:
        print("所有发送按钮选择器都失败，尝试键盘发送")
        try:
            input_element = await page.query_selector(input_selector)
            if input_element:
                await input_element.focus()
            await page.keyboard.press("Enter")
            print("使用Enter键发送")
            send_clicked = True
        except Exception as e:
            print(f"键盘发送失败: {e}")
            try:
                await page.keyboard.press("Control+Enter")
                print("使用Ctrl+Enter发送")
                send_clicked = True
            except Exception as ctrl_e:
                print(f"Ctrl+Enter发送失败: {ctrl_e}")
                return None

    response_selectors = [
        "div#response-content-container",
        ".response-content",
        "[data-testid='response-content']",
        ".message-content",
        ".chat-response"
    ]
    
    response_element = None
    for selector in response_selectors:
        print(f"尝试等待响应容器: {selector}")
        response_element = await wait_for_element(page, selector, timeout=20000)
        if response_element:
            print(f"找到响应容器: {selector}")
            break
        await asyncio.sleep(2)
    
    if response_element:
        await asyncio.sleep(20)
        for i in range(5):
            await asyncio.sleep(4)
            new_content = await page.content()
            if "正在搜索" not in new_content and "搜索中" not in new_content:
                break
            print(f"内容仍在加载中... ({i+1}/5)")
    else:
        print("未找到响应容器，等待页面稳定")
        await asyncio.sleep(30)
    
    content = await page.content()
    soup = BeautifulSoup(content, "html.parser")
    
    response_div = None
    for selector_info in [
        ({"id": "response-content-container"}, "ID选择器"),
        ({"class": "response-content"}, "类选择器"),
        ({"data-testid": "response-content"}, "测试ID选择器")
    ]:
        response_div = soup.find("div", selector_info[0])
        if response_div:
            print(f"使用{selector_info[1]}找到响应内容")
            break
    
    if response_div:
        html_content = str(response_div)
        parsed = zhipu_parse_html(html_content)
        result = remove_citation_marks(parsed)
        return result
    else:
        print("未找到任何响应内容，保存页面用于调试")
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = SCRIPT_DIR / "error_pages" / f"error_page_{timestamp}.html"
        try:
            os.makedirs(SCRIPT_DIR / "error_pages", exist_ok=True)
            with open(filename, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"页面已保存到: {filename}")
        except Exception as e:
            print(f"保存页面失败: {e}")
    return None


# ==================== 主流程 ====================

async def process_doubao_search(page, search_text):
    """豆包搜索主入口 - 优先使用智能爬虫"""
    print("\n[豆包搜索] 尝试使用智能爬虫...")
    result = await process_doubao_search_smart(page, search_text)
    if result:
        return result
    
    print("[豆包搜索] 智能爬虫失败，尝试旧版流程...")
    return await process_doubao_search_legacy(page, search_text)


async def process_zhipu_search(page, search_text):
    """智谱搜索主入口 - 优先使用智能爬虫"""
    print("\n[智谱搜索] 尝试使用智能爬虫...")
    result = await process_zhipu_search_smart(page, search_text)
    if result:
        return result
    
    print("[智谱搜索] 智能爬虫失败，尝试旧版流程...")
    return await process_zhipu_search_legacy(page, search_text)


async def process_web_content(url, page):
    """处理单个网页内容的完整流程"""
    try:
        if not await safe_get(page, url):
            print(f"无法访问链接: {url}")
            return None

        content = await page.content()
        soup = BeautifulSoup(content, "html.parser")

        content_div = soup.find("div", {"class": "article-content"})
        if not content_div:
            print(f"未找到内容容器: {url}")
            return None

        raw_text = content_div.get_text(strip=False)
        processed_text = re.sub(r"[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f-\x9f]", "", raw_text)

        chunks = []
        current_chunk = ""
        for paragraph in processed_text.split("\n"):
            if len(current_chunk) + len(paragraph) > 2000:
                chunks.append(current_chunk)
                current_chunk = paragraph + "\n"
            else:
                current_chunk += paragraph + "\n"
        if current_chunk:
            chunks.append(current_chunk)

        if len(chunks) >= 2:
            summaries = [NewsAnalysisService.summarize_web_content(chunk) for chunk in chunks]
            combined_summary = "".join(summaries)
            final_result = NewsAnalysisService.analyze_web_content(combined_summary)
        elif chunks:
            final_result = NewsAnalysisService.analyze_web_content(chunks[0])
        else:
            final_result = "无有效内容可分析"

        return final_result

    except Exception as e:
        print(f"处理网页失败 {url}: {str(e)}")
        return None


@asynccontextmanager
async def get_browser_page():
    """获取浏览器页面的上下文管理器"""
    user_data_dir = SCRIPT_DIR.parent / "playwright_user_data"
    
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(user_data_dir),
            headless=False,
            ignore_https_errors=True,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-accelerated-2d-canvas',
                '--no-first-run',
                '--no-zygote',
                '--disable-gpu',
                '--disable-blink-features=AutomationControlled',
                '--disable-infobars'
            ]
        )
        
        if not context.pages:
            page = await context.new_page()
        else:
            page = context.pages[0]
            
        await page.set_viewport_size({"width": 1280, "height": 800})
        await page.set_extra_http_headers({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        
        try:
            yield page
        finally:
            await context.close()


# ==================== 同步版本 ====================

def safe_get_sync(page, url, max_retries=3):
    """带重试机制的页面加载（同步版本）- 使用更宽松的策略"""
    for i in range(max_retries):
        try:
            # 使用 domcontentloaded 而不是 networkidle，更稳定
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            import time
            time.sleep(3)  # 等待页面渲染
            return True
        except SyncPlaywrightTimeoutError as e:
            print(f"页面加载失败: {e}, 尝试刷新...")
            try:
                page.reload()
                page.wait_for_timeout(2000 * (2**i))
            except:
                pass
    # 最后一次尝试使用最宽松的策略
    try:
        page.goto(url, wait_until="commit", timeout=30000)
        import time
        time.sleep(5)
        return True
    except:
        return False


def wait_for_element_sync(page, selector, timeout=30000):
    """显式等待元素出现（同步版本）"""
    try:
        page.wait_for_selector(selector, timeout=timeout)
        return page.query_selector(selector)
    except SyncPlaywrightTimeoutError:
        return None


def click_element_sync(page, selector, timeout=30000):
    """增强版点击操作（同步版本）"""
    try:
        element = page.wait_for_selector(selector, timeout=timeout)
        if element:
            element.scroll_into_view_if_needed()
            element.click()
            return True
    except Exception as e:
        print(f"常规点击失败: {e}，尝试JS点击...")
        try:
            escaped_selector = selector.replace("'", "\\'")
            page.evaluate(f"""
                const element = document.querySelector('{escaped_selector}');
                if (element) {{
                    element.scrollIntoView({{behavior: 'auto', block: 'center'}});
                    element.click();
                }}
            """)
            return True
        except Exception as js_e:
            print(f"JS点击失败: {js_e}")
            return False
    return False


def wait_for_page_ready_sync(page, timeout=30000):
    """等待页面完全加载（同步版本）"""
    try:
        page.wait_for_load_state("networkidle", timeout=timeout)
        page.wait_for_selector(".message-content-container", timeout=timeout)
    except SyncPlaywrightTimeoutError:
        print("页面加载超时")


# ==================== 新版同步智能爬虫流程 ====================

def process_doubao_search_sync_smart(page, search_text):
    """使用智能爬虫的豆包同步搜索流程"""
    crawler = SyncDoubaoCrawler(page)
    return crawler.search(search_text)


def process_zhipu_search_sync_smart(page, search_text):
    """使用智能爬虫的智谱同步搜索流程"""
    crawler = SyncZhipuCrawler(page)
    return crawler.search(search_text)


# ==================== 保留旧版同步流程作为fallback ====================

def process_doubao_search_sync_legacy(page, search_text):
    """原有的豆包同步搜索流程（作为fallback）"""
    if not safe_get_sync(page, "https://www.doubao.com/chat/search"):
        return None
    
    input_selector = "textarea[data-testid='chat_input_input']"
    if not click_element_sync(page, input_selector):
        return None

    input_element = wait_for_element_sync(page, input_selector)
    if input_element:
        input_element.fill(search_text)
    page.wait_for_timeout(8000)
    
    close_buttons = page.query_selector_all("span.semi-icon-default[role='img'].cursor-pointer")
    if close_buttons:
        try:
            close_button = close_buttons[0]
            close_button.scroll_into_view_if_needed()
            close_button.click()
            
            try:
                page.wait_for_selector(".modal-container", state="hidden", timeout=5000)
                print("弹窗关闭成功")
            except SyncPlaywrightTimeoutError:
                print("弹窗关闭验证超时")
            
        except Exception as e:
            print(f"关闭失败: {e}")
            page.screenshot(path="close_error.png")
    
    button = page.wait_for_selector("#flow-end-msg-send", timeout=10000)
    if not button:
        return None

    original_url = page.url
    print(f"当前 URL: {original_url}")

    page.evaluate("""
        const button = document.querySelector('#flow-end-msg-send');
        if (button) {
            button.style.border = '3px solid red';
            button.style.backgroundColor = 'yellow';
        }
    """)
    page.wait_for_timeout(1000)
    button.click()

    page.wait_for_timeout(80000)
    print(f"页面跳转到: {page.url}")
    try:
        page.wait_for_selector(
            "div[data-testid='message_text_content'] > div.auto-hide-last-sibling-br",
            timeout=30000
        )
    except SyncPlaywrightTimeoutError:
        print("动态内容加载超时")
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = SCRIPT_DIR / "error_pages" / f"error_page_{timestamp}.html"
        try:
            content = page.content()
            with open(filename, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception as e:
            print(f"保存页面失败: {e}")
    
    content = page.content()
    soup = BeautifulSoup(content, "html.parser")
    response_div = soup.find(
        "div", {"data-testid": "message_text_content", "class": "container-ZYIsnH flow-markdown-body theme-samantha-Nbr9UN"}
    )
    if response_div:
        html_content = str(response_div)
        parsed = doubao_parse_html_to_string(html_content)
        return parsed
    return None


def process_zhipu_search_sync_legacy(page, search_text):
    """原有的智谱同步搜索流程（作为fallback）"""
    if not safe_get_sync(page, "https://chat.z.ai/"):
        return None

    input_selector = "textarea#chat-input"
    web_search_btn_selector = "div[aria-label='Web Search'] > button"
    send_btn_selector = "button#send-message-button"

    if not click_element_sync(page, input_selector):
        return None
    
    input_element = wait_for_element_sync(page, input_selector)
    if input_element:
        input_element.fill(search_text)
    
    if not click_element_sync(page, web_search_btn_selector):
        return None

    screenshot_path = SCRIPT_DIR / "error_pages" / f"zhipu_search_{datetime.now().strftime('%Y%m%d-%H%M%S')}.png"
    page.screenshot(path=str(screenshot_path))
    
    if not click_element_sync(page, send_btn_selector):
        return None

    response_selector = "div#response-content-container"
    response_element = wait_for_element_sync(page, response_selector, timeout=40000)
    page.wait_for_timeout(40000)
    
    content = page.content()
    soup = BeautifulSoup(content, "html.parser")
    response_div = soup.find("div", {"id": "response-content-container"})
    if response_div:
        html_content = str(response_div)
        parsed = zhipu_parse_html(html_content)
        result = remove_citation_marks(parsed)
        return result
    else:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = SCRIPT_DIR / "error_pages" / f"error_page_{timestamp}.html"
        try:
            with open(filename, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception as e:
            print(f"保存页面失败: {e}")
    return None


# ==================== 同步主流程 ====================

def process_doubao_search_sync(page, search_text):
    """豆包同步搜索主入口 - 优先使用智能爬虫"""
    print("\n[豆包搜索] 尝试使用智能爬虫...")
    result = process_doubao_search_sync_smart(page, search_text)
    if result:
        return result
    
    print("[豆包搜索] 智能爬虫失败，尝试旧版流程...")
    return process_doubao_search_sync_legacy(page, search_text)


def process_zhipu_search_sync(page, search_text):
    """智谱同步搜索主入口 - 优先使用智能爬虫"""
    print("\n[智谱搜索] 尝试使用智能爬虫...")
    result = process_zhipu_search_sync_smart(page, search_text)
    if result:
        return result
    
    print("[智谱搜索] 智能爬虫失败，尝试旧版流程...")
    return process_zhipu_search_sync_legacy(page, search_text)


def web_search_sync(search_text):
    """同步统一搜索入口"""
    user_data_dir = str(SCRIPT_DIR.parent / "playwright_user_data")
    config = PlaywrightConfig(user_data_dir=user_data_dir)
    page = config.get_default_page()
    
    if page is None:
        print("无法初始化浏览器")
        return web_search_fallback(search_text)
    
    try:
        platforms = [
            ("智谱", process_zhipu_search_sync),
            ("豆包", process_doubao_search_sync),
        ]
        random.shuffle(platforms)
        
        for name, func in platforms:
            print(f"尝试使用 {name} 平台...")
            result = func(page, search_text)
            if result:
                result = result.replace("#", "")
                return remove_citation_marks(result)
    
    finally:
        config.quit_browser()
    
    return web_search_fallback(search_text)


def web_search_fallback(search_text):
    """搜索降级方案"""
    print("尝试使用DuckDuckGo")
    ddgs_results = search_with_ddgs(search_text, "text") or search_with_ddgs(search_text, "news")
    if ddgs_results:
        first_result = ddgs_results[0]
        first_title = first_result["title"].replace("#", "")
        first_body = first_result["body"].replace("#", "")

        if len(ddgs_results) >= 2:
            second_result = ddgs_results[1]
            second_title = second_result["title"].replace("#", "")
            second_body = second_result["body"].replace("#", "")
        else:
            second_title = "无"
            second_body = "无足够结果"

        return f"{first_title}: {first_body}+{second_title}: {second_body}"
    
    print("尝试使用Tavily")
    Tavily_results = get_original_content(search_text)["results"]
    if Tavily_results:
        result = ""
        for item in Tavily_results:
            result += item["content"] + "\n"
        return result.strip() or None

    return ""


async def web_search_async(search_text):
    """异步统一搜索入口"""
    async with get_browser_page() as page:
        platforms = [
            ("智谱", process_zhipu_search),
            ("豆包", process_doubao_search),
        ]
        random.shuffle(platforms)
        for name, func in platforms:
            print(f"尝试使用 {name} 平台...")
            result = await func(page, search_text)
            if result:
                result = result.replace("#", "")
                return remove_citation_marks(result)

    print("尝试使用DuckDuckGo")
    ddgs_results = search_with_ddgs(search_text, "text") or search_with_ddgs(search_text, "news")
    if ddgs_results:
        first_result = ddgs_results[0]
        first_title = first_result["title"].replace("#", "")
        first_body = first_result["body"].replace("#", "")

        if len(ddgs_results) >= 2:
            second_result = ddgs_results[1]
            second_title = second_result["title"].replace("#", "")
            second_body = second_result["body"].replace("#", "")
        else:
            second_title = "无"
            second_body = "无足够结果"

        return f"{first_title}: {first_body}+{second_title}: {second_body}"
    
    print("尝试使用Tavily")
    Tavily_results = get_original_content(search_text)["results"]
    urls = []
    if Tavily_results:
        result = ""
        for item in Tavily_results:
            result += item["content"] + "\n"
            urls.append(item["url"])
        return result.strip() or None

    return ""


def web_search(search_text):
    """同步搜索入口"""
    return web_search_sync(search_text)


def pic_web_search(search_text):
    ddgs_images = search_with_ddgs(search_text, "images")
    ddgs_videos = search_with_ddgs(search_text, "videos") if not ddgs_images else []
    ddgs_results = ddgs_images or ddgs_videos

    urls = []
    if ddgs_results:
        print(ddgs_results)
        for result in ddgs_results:
            urls.append(result["image"])
    Tavily_images = get_original_content(search_text)["images"]
    if Tavily_images:
        urls.extend(Tavily_images)
    return urls


async def main_async():
    """异步主函数"""
    try:
        search_text = "万鹏最近有什么动向，近一年有什么电影电视剧相关的资讯，帮我列举一下"
        print("异步搜索结果：")
        result = await web_search_async(search_text)
        print(result)
    except Exception as e:
        print(f"异步搜索失败: {e}")


def main_sync():
    """同步主函数"""
    try:
        search_text = "万鹏最近有什么动向，近一年有什么电影电视剧相关的资讯，帮我列举一下"
        print("同步搜索结果：")
        result = web_search(search_text)
        print(result)
    except Exception as e:
        print(f"同步搜索失败: {e}")


def main():
    """主函数"""
    print("=== Playwright Web Search 演示 ===")
    print("\n1. 使用同步搜索（推荐）:")
    main_sync()
    
    print("\n2. 使用异步搜索:")
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
