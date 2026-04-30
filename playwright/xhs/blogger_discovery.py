#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小红书博主发掘模块
功能：
1. 搜索关键词
2. 筛选笔记（未看过、图文）
3. 过滤高赞笔记（>20赞）
4. 分析评论区用户
5. 识别用户性别，保存女性博主信息
"""

import json
import time
import random
import os
from pathlib import Path
from typing import Dict, List, Set, Optional
from playwright.sync_api import Page
from datetime import datetime
import logging
import sys

# 导入配置和工具
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from playwright_config import PlaywrightConfig
from .crawler_logger import CrawlerLogger

class XiaohongshuBloggerDiscovery:
    """
    小红书博主发掘器
    """
    
    def __init__(self, user_data_dir: str = None):
        """
        初始化发掘器
        
        Args:
            user_data_dir: 用户数据目录，如果为None则使用PlaywrightConfig的默认目录
        """
        self.playwright_config = PlaywrightConfig(user_data_dir=user_data_dir)
        self.page = None
        self.context = None
        self.browser = None
        
        # 结果保存目录
        # 当前文件在 d:\project\web_server\func\playwright\xhs\blogger_discovery.py
        # 结果保存在 d:\project\web_server\func\playwright\xhs\results\bloggers
        self.results_dir = Path(__file__).parent / "results" / "bloggers"
        self.results_dir.mkdir(parents=True, exist_ok=True)
        
        # 调试目录
        self.debug_dir = self.results_dir / "debug"
        self.debug_dir.mkdir(parents=True, exist_ok=True)
        
        # 记录文件
        # 统一使用 social_bot 的数据存储路径
        self.data_store_xhs_dir = Path(__file__).resolve().parent.parent.parent.parent / "social_bot" / "data_store" / "xhs"
        self.data_store_xhs_dir.mkdir(parents=True, exist_ok=True)
        
        self.bloggers_file = self.data_store_xhs_dir / "discovered_bloggers.json"
        self.excluded_file = self.results_dir / "excluded_users.json"
        self.processed_notes_file = self.results_dir / "processed_notes.json"

        # 加载已记录的用户
        self.discovered_users = self._load_json(self.bloggers_file)
        self.excluded_users = self._load_json(self.excluded_file)
        self.processed_notes = self._load_json(self.processed_notes_file)
        
        # 加载所有已打过招呼的用户 (从 user_status.json 检查)
        self.greeted_users_cache = self._load_greeted_users()
        
        # 日志
        self.logger = CrawlerLogger(name="xhs_blogger_discovery")
        
    def _load_greeted_users(self) -> Set[str]:
        """加载所有已打过招呼或正在进行中的用户ID"""
        greeted = set()
        # 遍历 data_store/xhs 目录下的所有用户文件夹
        if self.data_store_xhs_dir.exists():
            for user_dir in self.data_store_xhs_dir.iterdir():
                if user_dir.is_dir():
                    status_file = user_dir / "user_status.json"
                    if status_file.exists():
                        try:
                            with open(status_file, 'r', encoding='utf-8') as f:
                                status_data = json.load(f)
                                # 如果状态不是 pending_greet，说明已经有交互或者已完成
                                # status 可能为: greeted, replied, completed, rejected, processing 等
                                # 我们这里保守一点，只要状态不是 pending_greet (初始状态)，就视为已处理
                                # 或者更严格：只要 status == greeted 或 replied 或 completed
                                current_status = status_data.get("status")
                                if current_status in ["greeted", "replied", "completed", "rejected"]:
                                    # 尝试获取xhs_id
                                    profile_file = user_dir / "profile_structured.json"
                                    if profile_file.exists():
                                         with open(profile_file, 'r', encoding='utf-8') as pf:
                                             profile = json.load(pf)
                                             xhs_id = profile.get("xhs_id")
                                             if xhs_id:
                                                 greeted.add(str(xhs_id))
                                    
                                    # 同时也把目录名作为可能的ID加入 (如果是 user_123 格式)
                                    user_id_from_dir = user_dir.name
                                    if user_id_from_dir.startswith("user_"):
                                         possible_id = user_id_from_dir.replace("user_", "")
                                         if possible_id.isdigit():
                                             greeted.add(possible_id)
                        except Exception as e:
                            print(f"Error loading status for {user_dir}: {e}")
        
        print(f"已加载 {len(greeted)} 个已交互用户")
        return greeted
        
    def _load_json(self, file_path: Path) -> Dict:
        """加载JSON文件"""
        if file_path.exists():
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                self.logger.logger.error(f"加载文件 {file_path} 失败: {e}")
        return {}
        
    def _save_json(self, data: Dict, file_path: Path):
        """保存JSON文件"""
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                    
        except Exception as e:
            self.logger.logger.error(f"保存文件 {file_path} 失败: {e}")

    def start(self, keyword: str, max_notes: int = 10, headless: bool = False):
        """
        开始发掘任务
        
        Args:
            keyword: 搜索关键词
            max_notes: 最大处理笔记数
            headless: 是否无头模式
        """
        try:
            self.logger.logger.info(f"🚀 开始发掘任务: 关键词='{keyword}'")
            
            # 启动浏览器
            self.playwright_config.headless = headless
            success = self.playwright_config.initialize_browser()
            if not success:
                raise Exception("浏览器初始化失败")
                
            # 获取上下文和页面
            # PlaywrightConfig 类中 context 存储在 _browser_context, page 存储在 _page
            # 并且没有公开的属性 getter，所以我们需要访问内部属性或者使用 get_default_page
            self.context = self.playwright_config._browser_context
            self.page = self.playwright_config.get_default_page()
            
            if not self.context or not self.page:
                 raise Exception("获取浏览器上下文或页面失败")
            
            # 1. 访问搜索页
            self._search_keyword(keyword)
            
            # 2. 筛选
            self._apply_filters()
            
            # 3. 处理搜索结果
            self._process_search_results(max_notes, keyword)
            
        except Exception as e:
            self.logger.logger.error(f"❌ 任务执行异常: {e}", exc_info=True)
        finally:
            self.logger.logger.info("任务结束，清理资源...")
            if self.playwright_config:
                self.playwright_config.close()

    def _search_keyword(self, keyword: str):
        """执行搜索"""
        self.logger.logger.info(f"🔍 正在搜索: {keyword}")
        self.page.goto("https://www.xiaohongshu.com/explore")
        self.page.wait_for_load_state("networkidle")
        
        # 查找输入框
        search_input = self.page.locator("input#search-input, input.search-input").first
        if not search_input.is_visible():
            # 可能是登录页或者结构变化
            self.logger.logger.warning("未找到搜索框，尝试直接访问搜索URL")
            self.page.goto(f"https://www.xiaohongshu.com/search_result?keyword={keyword}&source=web_explore_feed")
            self.page.wait_for_load_state("networkidle")
            return

        search_input.fill(keyword)
        search_input.press("Enter")
        self.page.wait_for_load_state("networkidle")
        time.sleep(2) # 等待页面跳转和加载

    def _save_debug_html(self, prefix: str):
        """保存当前页面 HTML 用于调试"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{prefix}_{timestamp}.html"
            file_path = self.debug_dir / filename
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(self.page.content())
            self.logger.logger.info(f"  🐞 已保存调试 HTML: {file_path}")
        except Exception as e:
            self.logger.logger.warning(f"  保存调试 HTML 失败: {e}")

    def _apply_filters(self):
        """应用筛选条件：未看过、图文"""
        self.logger.logger.info("⚙️ 应用筛选条件...")
        
        # 调试：保存筛选前的页面
        self._save_debug_html("before_filter")
        
        try:
            # 1. 必须先点击“筛选”按钮展开面板
            # 根据分析结果，筛选按钮结构为：
            # <div class="filter" data-v-04829c1d="" data-v-eb91fffe=""><span data-v-eb91fffe="">筛选</span>...</div>
            # 这表明 .filter 是一个 class，且包含文本“筛选”
            filter_btn = None
            try:
                # 尝试多个选择器组合
                # 1. 精确匹配 .filter 且包含文本 "筛选" 的元素
                filter_btn = self.page.locator(".filter").filter(has_text="筛选").first
                
                # 2. 如果上面找不到，尝试 .filter-box
                if not filter_btn.is_visible():
                     filter_btn = self.page.locator(".filter-box").filter(has_text="筛选").first
                     
                # 3. 实在不行，找包含文本“筛选”的 div，且具有 pointer 样式（虽然 playwright 无法直接查样式，但可以查属性）
                if not filter_btn.is_visible():
                     filter_btn = self.page.locator("div:text-is('筛选')").first
            except:
                self.logger.logger.warning("查找筛选按钮异常")
            
            # 确保面板展开的辅助函数
            def ensure_panel_open():
                if filter_btn and filter_btn.is_visible():
                    # 检查是否已经展开
                    # 面板通常有 .filter-panel 类，或者检查是否有“搜索范围”这个词
                    is_open = False
                    if self.page.locator(".filter-panel").is_visible():
                        is_open = True
                    elif self.page.locator("text='搜索范围'").is_visible():
                        is_open = True
                        
                    if not is_open:
                        self.logger.logger.info("  点击展开筛选面板")
                        # 调试：打印筛选按钮信息
                        try:
                             # 尝试获取 filter_btn 的信息
                             box = filter_btn.bounding_box()
                             self.logger.logger.info(f"    筛选按钮位置: {box}")
                             if box:
                                 # 移动鼠标到按钮上
                                 self.page.mouse.move(box["x"] + box["width"]/2, box["y"] + box["height"]/2)
                        except:
                             pass
                        
                        # 尝试点击，带重试
                        for i in range(3):
                            try:
                                # 强制点击筛选按钮
                                self.logger.logger.info(f"    点击筛选按钮 (尝试 {i+1}/3)")
                                
                                # 确保元素在视口中
                                try:
                                    filter_btn.scroll_into_view_if_needed()
                                except:
                                    pass
                                
                                # 使用 force=True 强制点击
                                filter_btn.click(force=True)
                                
                                # 等待面板出现
                                # 增加等待时间，并且如果失败尝试再次点击
                                try:
                                    # 检查 .filter-panel 是否可见
                                    self.page.wait_for_selector(".filter-panel", timeout=3000)
                                    if self.page.locator(".filter-panel").is_visible():
                                        is_open = True
                                        self.logger.logger.info("    筛选面板已展开 (.filter-panel)")
                                        break
                                except:
                                    # 如果没检测到，尝试检测包含文本的元素
                                    try:
                                        self.page.wait_for_selector("text='搜索范围'", timeout=1000)
                                        is_open = True
                                        self.logger.logger.info("    筛选面板已展开 (搜索范围)")
                                        break
                                    except:
                                        self.logger.logger.info(f"    点击后未检测到面板，等待重试...")
                                        time.sleep(1)
                            except Exception as e:
                                self.logger.logger.warning(f"    点击筛选按钮失败: {e}")
                        
                        self._save_debug_html("filter_panel_opened")
                    return is_open
                return False

            if not ensure_panel_open():
                self.logger.logger.warning("未找到筛选按钮或无法展开面板，跳过筛选")
                return
            
            # 2. 选择“图文”
            try:
                # 重新确保面板打开
                ensure_panel_open()
                
                # 策略: 在筛选面板(.filter-panel)内查找包含“图文”的 span
                # 必须精确匹配，避免点到其他地方
                img_text_tag = self.page.locator(".filter-panel span").filter(has_text="图文").first
                
                if img_text_tag.is_visible():
                    # 检查是否激活
                    # 小红书的选中状态通常是 class="active" 或父级有 class="active"
                    # 或者有个勾选图标
                    is_active = False
                    
                    # 检查是否有 active 类
                    if "active" in (img_text_tag.get_attribute("class") or ""):
                        is_active = True
                    # 检查父级
                    parent = img_text_tag.locator("..")
                    if "active" in (parent.get_attribute("class") or ""):
                        is_active = True
                        
                    if not is_active:
                        self.logger.logger.info("  点击选择: 图文")
                        img_text_tag.click()
                        time.sleep(2) # 等待加载
                    else:
                        self.logger.logger.info("  '图文'已选中")
                else:
                    self.logger.logger.warning("未找到'图文'筛选选项")
            except Exception as e:
                 self.logger.logger.warning(f"选择'图文'失败: {e}")

            # 3. 选择“未看过”
            try:
                # 重新确保面板打开
                ensure_panel_open()
                
                # 策略: 在筛选面板(.filter-panel)内查找包含“未看过”的 span
                unseen_tag = self.page.locator(".filter-panel span").filter(has_text="未看过").first
                
                if unseen_tag.is_visible():
                    # 检查是否激活
                    is_active = False
                    if "active" in (unseen_tag.get_attribute("class") or ""):
                        is_active = True
                    parent = unseen_tag.locator("..")
                    if "active" in (parent.get_attribute("class") or ""):
                        is_active = True
                        
                    if not is_active:
                        self.logger.logger.info("  点击选择: 未看过")
                        unseen_tag.click()
                        time.sleep(2)
                    else:
                         self.logger.logger.info("  '未看过'已选中")
                else:
                    self.logger.logger.warning("未找到'未看过'筛选选项")
            except Exception as e:
                self.logger.logger.warning(f"选择'未看过'失败: {e}")
                
            # 收起筛选面板（可选，点击收起按钮）
            try:
                collapse_btn = self.page.locator(".operation:has-text('收起')").first
                if collapse_btn.is_visible():
                    collapse_btn.click()
                    time.sleep(0.5)
            except:
                pass
                
        except Exception as e:
            self.logger.logger.warning(f"筛选操作异常: {e}")

    def _process_search_results(self, max_notes: int, keyword: str):
        """处理搜索结果列表"""
        self.logger.logger.info("📋 开始处理搜索结果...")
        
        processed_count = 0
        scroll_attempts = 0
        
        # 记录已处理的笔记ID，避免重复
        processed_note_ids = set()
        
        # 调试：保存初始加载后的页面
        self._save_debug_html("search_results_loaded")
        
        while processed_count < max_notes:
            # 等待卡片加载
            try:
                self.page.wait_for_selector(".note-item", timeout=5000)
            except:
                self.logger.logger.warning("等待笔记卡片超时")
            
            # 获取所有笔记卡片
            cards = self.page.locator(".note-item").all()
            self.logger.logger.info(f"当前页面共有 {len(cards)} 个笔记卡片")
            
            new_cards_found = False
            
            for i, card in enumerate(cards):
                if processed_count >= max_notes:
                    break
                    
                try:
                    # 确保卡片可见并滚动到视图中
                    # 注意：Playwright 的 scroll_into_view_if_needed 会尝试滚动
                    # 但如果是懒加载，可能需要手动滚动页面底部
                    try:
                        if not card.is_visible():
                            card.scroll_into_view_if_needed()
                    except:
                        pass
                        
                    # 获取笔记链接，用于提取ID
                    # 放宽选择器：查找任意 href 包含 /explore/ 或 /user/profile/ 的链接
                    # 或者直接找 .cover 元素
                    note_id = None
                    href = None
                    
                    # 尝试从 .cover 获取链接 (通常是 /search_result/...)
                    cover = card.locator(".cover").first
                    if cover.is_visible():
                        href = cover.get_attribute("href")
                    
                    # 如果没有，尝试找任意链接
                    if not href:
                        link_el = card.locator("a").first
                        if link_el.is_visible():
                            href = link_el.get_attribute("href")
                            
                    if not href:
                        # self.logger.logger.warning(f"  卡片 {i} 未找到链接")
                        continue
                        
                    # 提取笔记ID
                    # href可能包含参数，如 /search_result/68bb7aeb...?xsec...
                    # 提取最后一段路径作为ID
                    # 注意：如果href是 /user/profile/xxx，说明不是笔记卡片，而是用户卡片，跳过
                    if "/user/profile/" in href:
                        continue

                    parts = href.split('/')
                    # 过滤掉空字符串
                    parts = [p for p in parts if p]
                    
                    if parts:
                        # 通常ID是最后一部分，但在 /search_result/ID?token... 中，ID在?之前
                        last_part = parts[-1]
                        note_id = last_part.split('?')[0]
                    
                    if not note_id:
                        continue
                    
                    # 检查是否在本次运行中处理过
                    if note_id in processed_note_ids:
                        continue

                    # 检查是否历史已处理
                    if note_id in self.processed_notes:
                        self.logger.logger.info(f"  跳过历史已处理笔记: {note_id}")
                        processed_note_ids.add(note_id) # 标记为本次已见，避免重复检查
                        continue
                        
                    processed_note_ids.add(note_id)
                    new_cards_found = True
                    
                    # 检查点赞数
                    # 结构: <span class="count">16</span>
                    # 如果没有 .count 元素，说明可能是 0 赞或者隐藏，默认跳过
                    like_count_el = card.locator(".count").first
                    if not like_count_el.is_visible():
                         # 尝试找 .like-wrapper 里的文本
                         like_count_el = card.locator(".like-wrapper span").first
                    
                    if like_count_el.is_visible():
                        like_count_text = like_count_el.inner_text().strip()
                        # 解析点赞数 (处理 "1.2万", "100+" 等情况)
                        like_count = self._parse_count(like_count_text)
                        
                        if like_count <= 20:
                            self.logger.logger.info(f"  跳过低赞笔记 {note_id}: {like_count} (文本: {like_count_text})")
                            processed_note_ids.add(note_id) # 标记为已处理，虽然是跳过
                            continue
                            
                        self.logger.logger.info(f"👉 发现热门笔记 {note_id} (点赞: {like_count_text})")
                    else:
                        self.logger.logger.info(f"  跳过无点赞数笔记 {note_id}")
                        processed_note_ids.add(note_id)
                        continue
                    
                    # 点击进入笔记详情
                    # 改为直接访问URL，避免点击事件监听超时
                    if href:
                        self.logger.logger.info(f"  正在打开笔记详情: {note_id}")
                        
                        if not self.context:
                            self.logger.logger.error("  浏览器上下文失效")
                            continue
                            
                        detail_page = None
                        try:
                            # 构建完整URL
                            detail_url = f"https://www.xiaohongshu.com{href}" if href.startswith('/') else href
                            
                            # 创建新页面并访问
                            detail_page = self.context.new_page()
                            # 尝试让新页面在前台显示，解决“无头”感知问题
                            try:
                                detail_page.bring_to_front()
                            except:
                                pass
                                
                            detail_page.goto(detail_url)
                            detail_page.wait_for_load_state("domcontentloaded")
                            
                            # 额外等待页面渲染，确保用户能看到内容
                            time.sleep(1)
                            
                            # 处理详情页
                            self._process_note_detail(detail_page, keyword)
                            
                            # 记录已处理笔记
                            self.processed_notes[note_id] = {
                                "processed_at": datetime.now().isoformat(),
                                "keyword": keyword
                            }
                            self._save_json(self.processed_notes, self.processed_notes_file)
                            
                            # 关闭详情页
                            detail_page.close()
                            processed_count += 1
                            self.logger.logger.info(f"  笔记处理完成，当前进度: {processed_count}/{max_notes}")
                        except Exception as e:
                            self.logger.logger.warning(f"  处理详情页失败: {e}")
                            if detail_page:
                                try:
                                    detail_page.close()
                                except:
                                    pass
                            continue
                        
                        # 随机等待
                        time.sleep(random.uniform(1, 3))
                        
                except Exception as e:
                    self.logger.logger.error(f"处理笔记卡片异常: {e}")
                    continue
            
            if not new_cards_found:
                scroll_attempts += 1
                if scroll_attempts > 5:
                    self.logger.logger.info("多次滚动未发现新内容，结束处理")
                    break
            else:
                scroll_attempts = 0
            
            if processed_count < max_notes:
                self.logger.logger.info("滚动加载更多...")
                # 使用更大的滚动幅度，或者滚动到底部
                self.page.evaluate("window.scrollBy(0, 1500)")
                time.sleep(1)
                # 再次滚动以确保触发加载
                self.page.evaluate("window.scrollBy(0, 500)")
                time.sleep(2)
            
    def _parse_count(self, text: str) -> int:
        """解析数量字符串"""
        if not text:
            return 0
        text = text.replace('+', '')
        try:
            if '万' in text:
                return int(float(text.replace('万', '')) * 10000)
            return int(text)
        except:
            return 0

    def _process_note_detail(self, page: Page, keyword: str):
        """处理笔记详情页，提取评论区用户"""
        try:
            self.logger.logger.info("  正在加载评论区...")
            
            # 1. 尝试多次滚动以加载评论
            comments_found = False
            for i in range(5): # 增加尝试次数
                # 检查评论是否出现
                try:
                    if page.locator(".comment-item").count() > 0:
                        comments_found = True
                        break
                except:
                    pass
                
                self.logger.logger.info(f"  尝试加载评论 ({i+1}/5)...")
                # 混合滚动策略：先滚到底，再回滚一点，再滚到底
                try:
                    # 使用键盘模拟用户操作，更真实
                    page.mouse.move(100, 100)
                    page.click("body") # 聚焦页面
                    
                    # 尝试多种滚动方式
                    # 1. 模拟按 PageDown
                    for _ in range(5):
                        page.keyboard.press("PageDown")
                        time.sleep(0.5)
                        
                    # 2. 模拟按 End
                    page.keyboard.press("End")
                    time.sleep(1)
                    
                    # 3. 往回滚一点
                    page.mouse.wheel(0, -500)
                    time.sleep(0.5)
                    
                    # 4. 再滚到底
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                except:
                    # 降级到 evaluate
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    time.sleep(0.5)
                    page.evaluate("window.scrollBy(0, -500)")
                    time.sleep(0.5)
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    
                time.sleep(1.5)
                # 有时候需要往回滚一点才能触发懒加载
                page.evaluate("window.scrollBy(0, -300)")
                time.sleep(0.5)
                page.evaluate("window.scrollBy(0, 300)")
                time.sleep(1)

            if not comments_found:
                 # 最后尝试等待
                try:
                    page.wait_for_selector(".comment-item", timeout=3000)
                    comments_found = True
                except:
                    self.logger.logger.warning("  最终未找到评论或加载超时")
                    # 即使没找到评论，也可以尝试保存页面源码调试
                    # self._save_debug_html("no_comments")
                    return

            # 2. 获取评论区用户
            # 尝试获取所有评论项
            comment_items = page.locator(".comment-item").all()
            self.logger.logger.info(f"  📝 发现 {len(comment_items)} 条评论项")
            
            processed_users_in_note = 0
            
            # 遍历评论项提取用户信息
            for item in comment_items:
                if processed_users_in_note >= 10: # 增加到10个
                    break
                    
                try:
                    # 在每个评论项中查找作者链接
                    # 优先找名字链接
                    author_link = item.locator(".author-wrapper .name").first
                    if not author_link.is_visible():
                        # 备用：找头像链接
                        author_link = item.locator(".author-wrapper a").first
                    
                    if not author_link.is_visible():
                         # 再备用
                         author_link = item.locator(".author").first
                    
                    if not author_link.is_visible():
                        continue
                        
                    user_name = author_link.inner_text().strip()
                    user_href = author_link.get_attribute("href")
                    
                    if not user_href:
                        # 尝试从父元素获取 (有时候 a 标签在外面)
                        try:
                            parent_href = author_link.locator("xpath=..").get_attribute("href")
                            if parent_href and "/user/profile/" in parent_href:
                                user_href = parent_href
                        except:
                            pass
                        
                    if not user_href:
                        # self.logger.logger.warning(f"    未找到用户链接: {user_name}")
                        continue

                    # 提取用户ID
                    # href格式: /user/profile/5efc0f6d000000000101dae3?...
                    parts = user_href.split('/profile/')
                    if len(parts) > 1:
                        user_id = parts[-1].split('?')[0]
                    else:
                        continue
                    
                    # 检查是否已处理或已排除或已打招呼
                    if user_id in self.discovered_users:
                        # self.logger.logger.info(f"    跳过已发现用户: {user_name}")
                        continue
                    if user_id in self.excluded_users:
                        # self.logger.logger.info(f"    跳过已排除用户: {user_name}")
                        continue
                    if user_id in self.greeted_users_cache:
                        self.logger.logger.info(f"    跳过已打招呼/交互用户: {user_name} ({user_id})")
                        continue
                    
                    # 访问用户主页
                    self.logger.logger.info(f"    👤 检查用户: {user_name} (ID: {user_id})")
                    
                    # 构建完整URL
                    profile_url = f"https://www.xiaohongshu.com{user_href}" if user_href.startswith('/') else user_href
                    
                    new_page = None
                    try:
                        new_page = self.context.new_page()
                        # 尝试前台显示
                        try:
                            new_page.bring_to_front()
                        except:
                            pass
                            
                        new_page.goto(profile_url)
                        try:
                            new_page.wait_for_load_state("domcontentloaded", timeout=10000)
                            time.sleep(1) # 等待渲染
                        except:
                            self.logger.logger.warning("    用户主页加载超时")
                        
                        # 检查性别
                        is_male = self._check_is_male(new_page)
                        is_female = self._check_is_female(new_page)
                        
                        # 获取小红书号和IP属地
                        xhs_id = self._get_xhs_id(new_page)
                        ip_location = self._get_ip_location(new_page)
                        avatar_url = self._get_avatar_url(new_page)
                        
                        if xhs_id == "unknown":
                            # 尝试重试获取
                            time.sleep(1)
                            xhs_id = self._get_xhs_id(new_page)
                            ip_location = self._get_ip_location(new_page)
                            if not avatar_url:
                                avatar_url = self._get_avatar_url(new_page)

                        # 严格筛选：只留女性
                        if is_male:
                            # 排除 (男性)
                            # 重新加载排除列表以防止覆盖
                            self.excluded_users = self._load_json(self.excluded_file)
                            self.excluded_users[user_id] = {
                                "nickname": user_name,
                                "reason": "gender_male",
                                "discovered_at": datetime.now().isoformat(),
                                "keyword": keyword
                            }
                            self._save_json(self.excluded_users, self.excluded_file)
                            self.logger.logger.info(f"    🚫 排除用户: {user_name} (男性)")
                        
                        elif not is_female:
                            # 排除 (未知/非女性)
                            # 重新加载排除列表以防止覆盖
                            self.excluded_users = self._load_json(self.excluded_file)
                            self.excluded_users[user_id] = {
                                "nickname": user_name,
                                "reason": "gender_not_female",
                                "discovered_at": datetime.now().isoformat(),
                                "keyword": keyword
                            }
                            self._save_json(self.excluded_users, self.excluded_file)
                            self.logger.logger.info(f"    🚫 排除用户: {user_name} (非女性/未知性别)")

                        elif "重庆" not in ip_location:
                            # 排除 (IP非重庆)
                            # 重新加载排除列表以防止覆盖
                            self.excluded_users = self._load_json(self.excluded_file)
                            self.excluded_users[user_id] = {
                                "nickname": user_name,
                                "reason": f"ip_location_mismatch ({ip_location})",
                                "discovered_at": datetime.now().isoformat(),
                                "keyword": keyword
                            }
                            self._save_json(self.excluded_users, self.excluded_file)
                            self.logger.logger.info(f"    🚫 排除用户: {user_name} (IP属地: {ip_location})")
                            
                        else:
                            # 截图保存
                            try:
                                screenshots_dir = self.results_dir / "screenshots"
                                screenshots_dir.mkdir(parents=True, exist_ok=True)
                                screenshot_filename = f"{user_id}.jpg"
                                screenshot_path = screenshots_dir / screenshot_filename
                                
                                # 等待图片加载完毕
                                time.sleep(2)
                                
                                # 隐藏可能的干扰元素（如弹窗）
                                try:
                                    new_page.evaluate("document.querySelectorAll('.mask, .dialog').forEach(e => e.style.display = 'none')")
                                except:
                                    pass
                                    
                                new_page.screenshot(path=str(screenshot_path), type="jpeg", quality=60)
                                self.logger.logger.info(f"    📸 已保存截图: {screenshot_filename}")
                            except Exception as e:
                                self.logger.logger.warning(f"    保存截图失败: {e}")
                                screenshot_filename = None

                            # 记录信息 (女性 且 IP为重庆)
                            # 重新加载博主列表以防止覆盖其他进程（如UI）的修改
                            self.discovered_users = self._load_json(self.bloggers_file)
                            
                            # 再次检查是否已存在（可能在重载后发现状态已变）
                            if user_id in self.discovered_users and self.discovered_users[user_id].get("status") == "rejected":
                                self.logger.logger.info(f"    跳过已拒绝用户 (实时检查): {user_name}")
                            else:
                                self.discovered_users[user_id] = {
                                    "nickname": user_name,
                                    "xhs_id": xhs_id,
                                    "ip_location": ip_location,
                                    "avatar_url": avatar_url,
                                    "screenshot": screenshot_filename,  # 保存截图文件名
                                    "url": profile_url,
                                    "gender": "female",
                                    "discovered_at": datetime.now().isoformat(),
                                    "source_note": page.url,
                                    "keyword": keyword,
                                    "status": "pending"  # 默认状态
                                }
                                self._save_json(self.discovered_users, self.bloggers_file)
                                self.logger.logger.info(f"    ✅ 发现目标博主: {user_name} (小红书号: {xhs_id}, IP: {ip_location})")
                            
                        new_page.close()
                    except Exception as e:
                        self.logger.logger.error(f"    访问用户主页失败: {e}")
                        if new_page:
                            try:
                                new_page.close()
                            except:
                                pass
                        continue
                    
                    processed_users_in_note += 1
                    # 稍微等待，避免请求过快
                    time.sleep(random.uniform(0.5, 1.5))
                    
                except Exception as e:
                    self.logger.logger.error(f"    处理评论用户异常: {e}")
                    continue
                    
        except Exception as e:
            self.logger.logger.error(f"  处理详情页异常: {e}")

    def _check_is_female(self, page: Page) -> bool:
        """检查用户是否为女性"""
        try:
            # 检查女性图标
            # HTML: <svg class="reds-icon"><use xlink:href="#female"></use></svg>
            female_icon = page.locator("use[href='#female']").first
            if female_icon.is_visible():
                return True
            female_icon_xlink = page.locator("use[xlink\\:href='#female']").first
            if female_icon_xlink.is_visible():
                return True
            
            # 检查 innerHTML 包含 #female
            gender_div = page.locator(".gender").first
            if gender_div.is_visible():
                html = gender_div.inner_html()
                if "#female" in html:
                    return True
                    
            return False
        except:
            return False

    def _check_is_male(self, page: Page) -> bool:
        """检查用户是否为男性"""
        try:
            # 检查男性图标
            # HTML: <svg class="reds-icon"><use xlink:href="#male"></use></svg>
            # 我们查找包含 #male 的 use 元素
            male_icon = page.locator("use[href='#male']").first
            if male_icon.is_visible():
                return True
            male_icon_xlink = page.locator("use[xlink\\:href='#male']").first
            if male_icon_xlink.is_visible():
                return True
            
            # 检查 innerHTML 包含 #male
            gender_div = page.locator(".gender").first
            if gender_div.is_visible():
                html = gender_div.inner_html()
                if "#male" in html:
                    return True
                    
            return False
        except:
            return False # 默认不排除

    def _get_xhs_id(self, page: Page) -> str:
        """获取小红书号"""
        try:
            # <span class="user-redId">小红书号：5477720795</span>
            id_el = page.locator(".user-redId").first
            if id_el.is_visible():
                text = id_el.inner_text()
                return text.replace("小红书号：", "").strip()
        except:
            pass
        return "unknown"

    def _get_ip_location(self, page: Page) -> str:
        """获取IP属地"""
        try:
            # <span class="user-IP">IP属地：云南</span>
            ip_el = page.locator(".user-IP").first
            if ip_el.is_visible():
                text = ip_el.inner_text()
                return text.replace("IP属地：", "").strip()
        except:
            pass
        return "unknown"

    def _get_avatar_url(self, page: Page) -> str:
        """获取用户头像URL"""
        try:
            # 尝试查找头像 img
            # 通常在 .user-info .avatar-wrapper img 或者 .user-image img
            # 策略1: 查找 .user-image img (常见)
            avatar_img = page.locator(".user-image img").first
            if avatar_img.is_visible():
                return avatar_img.get_attribute("src")
                
            # 策略2: 查找 .avatar img
            avatar_img = page.locator(".avatar img").first
            if avatar_img.is_visible():
                return avatar_img.get_attribute("src")
                
            # 策略3: 查找任意包含 'avatar' class 的 div 下的 img
            avatar_img = page.locator("[class*='avatar'] img").first
            if avatar_img.is_visible():
                return avatar_img.get_attribute("src")
                
        except:
            pass
        return ""


if __name__ == "__main__":
    # 测试代码
    discovery = XiaohongshuBloggerDiscovery()
    keyword = input("请输入搜索关键词: ")
    if keyword:
        discovery.start(keyword, max_notes=5)
