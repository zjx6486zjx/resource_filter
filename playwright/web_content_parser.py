import json
import os
import re
from datetime import datetime
from typing import Dict, List, Optional

from playwright.sync_api import Page


class WebContentParser:
    """通用网页内容解析器"""

    def __init__(self, page: Page):
        self.page = page
        self.results = []

    def parse_page_content(self, url: str, timeout: int = 30000) -> Dict:
        """解析单个网页的内容"""
        try:
            # 导航到页面
            self.page.goto(url, timeout=timeout, wait_until="domcontentloaded")

            # 等待页面加载完成
            self.page.wait_for_timeout(2000)

            # 获取基本信息
            title = self.page.title()
            current_url = self.page.url

            # 解析主要文本内容
            content = self._extract_main_content()

            # 获取页面元数据
            metadata = self._extract_metadata()

            result = {
                "url": current_url,
                "original_url": url,
                "title": title,
                "content": content,
                "metadata": metadata,
                "parsed_time": datetime.now().isoformat(),
                "content_length": len(content),
                "success": True,
                "error": None,
            }

            return result

        except Exception as e:
            return {
                "url": url,
                "original_url": url,
                "title": None,
                "content": None,
                "metadata": {},
                "parsed_time": datetime.now().isoformat(),
                "content_length": 0,
                "success": False,
                "error": str(e),
            }

    def _extract_main_content(self) -> str:
        """提取页面主要文本内容"""
        content_parts = []

        # 尝试多种内容提取策略
        strategies = [
            self._extract_by_article_tags,
            self._extract_by_main_tags,
            self._extract_by_content_divs,
            self._extract_by_paragraphs,
            self._extract_fallback,
        ]

        for strategy in strategies:
            try:
                content = strategy()
                if content and len(content.strip()) > 100:  # 至少100字符才认为有效
                    return content
            except Exception as e:
                print(f"内容提取策略失败: {e}")
                continue

        return "无法提取有效内容"

    def _extract_by_article_tags(self) -> str:
        """通过article标签提取内容"""
        articles = self.page.locator("article").all()
        if articles:
            content = ""
            for article in articles:
                text = article.text_content()
                if text:
                    content += text + "\n\n"
            return content.strip()
        return ""

    def _extract_by_main_tags(self) -> str:
        """通过main标签提取内容"""
        main_elements = self.page.locator("main").all()
        if main_elements:
            content = ""
            for main in main_elements:
                text = main.text_content()
                if text:
                    content += text + "\n\n"
            return content.strip()
        return ""

    def _extract_by_content_divs(self) -> str:
        """通过常见的内容div类名提取"""
        content_selectors = [
            ".content",
            ".article-content",
            ".post-content",
            ".entry-content",
            ".main-content",
            ".article-body",
            ".post-body",
            ".content-body",
            "#content",
            "#main-content",
            "#article-content",
            ".text-content",
            ".article-text",
            ".news-content",
            ".blog-content",
        ]

        for selector in content_selectors:
            try:
                elements = self.page.locator(selector).all()
                if elements:
                    content = ""
                    for element in elements:
                        text = element.text_content()
                        if text and len(text.strip()) > 50:
                            content += text + "\n\n"
                    if content:
                        return content.strip()
            except:
                continue
        return ""

    def _extract_by_paragraphs(self) -> str:
        """通过段落标签提取内容"""
        paragraphs = self.page.locator("p").all()
        if len(paragraphs) > 3:  # 至少有3个段落才认为是有效内容
            content = ""
            for p in paragraphs:
                text = p.text_content()
                if text and len(text.strip()) > 20:  # 过滤太短的段落
                    content += text.strip() + "\n\n"
            return content.strip()
        return ""

    def _extract_fallback(self) -> str:
        """兜底策略：提取body中的所有文本"""
        try:
            # 移除脚本和样式标签
            self.page.evaluate(
                """
                const scripts = document.querySelectorAll('script, style, nav, header, footer, aside');
                scripts.forEach(el => el.remove());
            """
            )

            body_text = self.page.locator("body").text_content()
            if body_text:
                # 清理文本
                lines = body_text.split("\n")
                cleaned_lines = []
                for line in lines:
                    line = line.strip()
                    if len(line) > 10 and not self._is_navigation_text(line):
                        cleaned_lines.append(line)

                return "\n".join(cleaned_lines)
        except:
            pass
        return ""

    def _is_navigation_text(self, text: str) -> bool:
        """判断是否为导航文本"""
        nav_keywords = [
            "首页",
            "登录",
            "注册",
            "搜索",
            "菜单",
            "导航",
            "版权",
            "Copyright",
            "联系我们",
            "关于我们",
            "隐私政策",
            "用户协议",
        ]
        return any(keyword in text for keyword in nav_keywords) and len(text) < 50

    def _extract_metadata(self) -> Dict:
        """提取页面元数据"""
        metadata = {}

        try:
            # 提取meta标签信息
            meta_tags = self.page.locator("meta").all()
            for meta in meta_tags:
                name = meta.get_attribute("name") or meta.get_attribute("property")
                content = meta.get_attribute("content")
                if name and content:
                    metadata[name] = content

            # 提取其他有用信息
            metadata["page_language"] = self.page.get_attribute("html", "lang") or "unknown"

            # 统计页面元素
            metadata["paragraph_count"] = self.page.locator("p").count()
            metadata["image_count"] = self.page.locator("img").count()
            metadata["link_count"] = self.page.locator("a").count()

        except Exception as e:
            print(f"元数据提取失败: {e}")

        return metadata

    def save_results(self, results: List[Dict], filename: str, data_dir: str = "data") -> str:
        """保存解析结果到JSON文件"""
        # 确保data目录存在
        os.makedirs(data_dir, exist_ok=True)

        # 生成文件路径
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if not filename.endswith(".json"):
            filename = f"{filename}_{timestamp}.json"

        filepath = os.path.join(data_dir, filename)

        # 保存数据
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "search_info": {
                        "total_pages": len(results),
                        "successful_parses": len([r for r in results if r["success"]]),
                        "failed_parses": len([r for r in results if not r["success"]]),
                        "created_time": datetime.now().isoformat(),
                    },
                    "results": results,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )

        return filepath
