import asyncio
import json
from playwright.async_api import async_playwright
from pathlib import Path


class NovelScraper:
    def __init__(self, search_keyword="斗破苍穹小说 内容大纲文字概述", max_results=5):
        self.script_dir = Path(__file__).resolve().parent
        self.search_keyword = search_keyword  # 暴露搜索关键词为实例变量
        self.max_results = max_results
        self.browser = None
        self.results = []

    async def _extract_page_info(self, page):
        """提取页面关键信息（保持原有实现）"""
        # 增强清理脚本
        await page.evaluate(
            r"""() => {
            // 移除顶部导航和侧边栏
            const headerElements = document.querySelectorAll('header, nav, .navbar, .top-bar, .site-header');
            headerElements.forEach(el => el.remove());
            
            // 移除更多广告元素
            document.querySelectorAll('iframe, script, style, noscript, [class*="banner"], [id*="popup"]').forEach(el => el.remove());
            
            // 移除互动元素
            document.querySelectorAll('button, .comments-section, .social-share, .login-box').forEach(el => el.remove());
        
            // 新增页脚清理规则
            document.querySelectorAll('.footer, .site-footer, .icp, .beian, [class*="pagination"], [class*="page"]').forEach(el => el.remove());
            
            // 新增短标签过滤（5字以下）
            document.querySelectorAll('a, button, span').forEach(el => {
                const text = el.innerText.replace(/\\s+/g, '');
                if (text.length <= 5 && !['上一篇','下一篇'].includes(text)) {
                    el.remove();
                }
            });
        
            // 增强备案号清理（修改部分）
            const icpPattern = /(京(ICP|公网安备)|备案号)[\s:：]*\d+/;  // 修正正则表达式注释
            document.querySelectorAll('[id*="icp"], [class*="icp"], [id*="beian"], [class*="beian"], [href*="beian"], [href*="icp"], div, p, span').forEach(el => {
                // 移除包含备案号的元素
                if (icpPattern.test(el.textContent) || icpPattern.test(el.href)) {
                    el.remove();
                }
            });
        
            // 新增文本节点清理（新增部分）
            const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
            while (walker.nextNode()) {
                const node = walker.currentNode;
                if (icpPattern.test(node.nodeValue)) {
                    node.parentNode.remove();
                }
            }
        }"""
        )

        title = await page.title()
        # 改进内容定位策略（新增备用选择器）
        content_selectors = [
            "article",
            ".main-content",
            ".content-wrapper",
            ".post-content",
            "[itemprop='articleBody']",
            "div.content",
            ".content-main",  # 新增常见内容容器
            ".article-text",  # 新增文章正文类
            "div[role='main']",  # 新增 ARIA 角色定位
            ".chapter-content",  # 新增小说内容专用类
        ]

        # 顺序尝试所有选择器（新增循环尝试逻辑）
        content_element = None
        for selector in content_selectors:
            content_element = await page.query_selector(selector)
            if content_element:
                break

        # 获取完整正文内容（新增备用方案）
        if content_element:
            full_content = await content_element.inner_text()
        else:
            # 降级方案：通过文本密度分析定位
            full_content = await page.evaluate(
                """() => {
                const elements = [...document.querySelectorAll('div,p')];
                let maxLength = 0;
                let content = '';
                elements.forEach(el => {
                    const text = el.innerText.trim().replace(/\\s+/g, '');
                    if (text.length > maxLength) {
                        maxLength = text.length;
                        content = el.innerText;
                    }
                });
                return content;
            }"""
            )

        # 增强文本过滤
        banned_keywords = ["广告", "推荐", "声明", "相关阅读", "评论", "获赞", "粉丝", "分享"]
        cleaned_content = "\n".join(
            [
                line.strip()
                for line in full_content.split("\n")
                if line.strip() and not any(kw in line for kw in banned_keywords)
            ]
        )

        # 新增空内容检测（新增重试机制）
        if not cleaned_content.strip():
            # 尝试备用解析方案
            cleaned_content = await page.evaluate(
                """() => {
                // 尝试读取 JSON-LD 结构化数据
                const jsonLd = document.querySelector('script[type="application/ld+json"]');
                if (jsonLd) {
                    try {
                        const data = JSON.parse(jsonLd.innerText);
                        return data.articleBody || data.description || '';
                    } catch(e) { return ''; }
                }
                return document.body.innerText;
            }"""
            )

        return {"url": page.url, "title": title.strip(), "content": cleaned_content.strip()}

    async def _process_link(self, link):
        """处理单个搜索结果链接"""
        async with await self.browser.new_page() as new_page:
            try:
                href = await link.get_attribute("href")
                await new_page.goto(href, timeout=60000)
                await new_page.wait_for_load_state("networkidle", timeout=15000)
                page_data = await self._extract_page_info(new_page)
                self.results.append(page_data)
            except Exception as e:
                print(f"Error processing {href}: {str(e)}")

    async def _save_results(self):
        """保存结果到文件"""
        with open(self.script_dir / "search_results.json", "w", encoding="utf-8") as f:
            json.dump(self.results, f, ensure_ascii=False, indent=2)

    async def run(self):
        """主执行流程"""
        async with async_playwright() as p:
            self.browser = await p.chromium.connect_over_cdp("http://localhost:9222")
            page = await self.browser.new_page()

            # 执行搜索
            await page.goto("https://www.baidu.com")
            await page.fill("#kw", self.search_keyword)  # 使用实例变量
            await page.press("#kw", "Enter")
            await page.wait_for_selector(".result.c-container", timeout=60000)

            # 处理结果链接
            links = await page.query_selector_all(".result.c-container h3 a")
            await asyncio.gather(*[self._process_link(link) for link in links[: self.max_results]])

            # 保存结果
            await self._save_results()
            await self.browser.close()


if __name__ == "__main__":
    # 使用示例（可通过修改参数自定义）
    scraper = NovelScraper(search_keyword="斗破苍穹小说 内容大纲文字概述", max_results=5)  # 暴露的搜索关键词参数
    asyncio.run(scraper.run())
