#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os

from playwright.sync_api import sync_playwright


class BrowserSession:
    """
    浏览器会话管理类
    用于管理带有用户数据持久化的浏览器会话
    """

    def __init__(self, user_data_dir=None):
        """
        初始化浏览器会话

        Args:
            user_data_dir (str): 用户数据目录路径，默认使用项目目录下的playwright_user_data
        """
        if user_data_dir is None:
            self.user_data_dir = "playwright_user_data"
        else:
            self.user_data_dir = user_data_dir

        self.playwright = None
        self.browser = None
        self.page = None

    def start_browser(self, headless=False, url="https://www.google.com"):
        """
        启动浏览器

        Args:
            headless (bool): 是否无头模式运行
            url (str): 启动后导航到的URL
        """
        # 确保用户数据目录存在
        os.makedirs(self.user_data_dir, exist_ok=True)

        self.playwright = sync_playwright().start()

        # 启动持久化上下文浏览器
        self.browser = self.playwright.chromium.launch_persistent_context(
            user_data_dir=self.user_data_dir,
            headless=headless,
            slow_mo=100,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-web-security",
                "--disable-features=VizDisplayCompositor",
                "--disable-dev-shm-usage",
            ],
        )

        # 创建新页面
        self.page = self.browser.new_page()

        # 设置用户代理
        self.page.set_extra_http_headers(
            {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
        )

        # 导航到指定URL
        if url:
            self.page.goto(url)

        print(f"浏览器已启动，用户数据目录: {self.user_data_dir}")
        return self.page

    def get_page(self):
        """
        获取当前页面对象

        Returns:
            Page: Playwright页面对象
        """
        return self.page

    def navigate_to(self, url):
        """
        导航到指定URL

        Args:
            url (str): 目标URL
        """
        if self.page:
            self.page.goto(url)
            print(f"已导航到: {url}")
        else:
            print("浏览器未启动，请先调用start_browser()")

    def wait_for_manual_login(self, login_url=None):
        """
        等待用户手动登录

        Args:
            login_url (str): 登录页面URL，如果提供则先导航到该页面
        """
        if login_url:
            self.navigate_to(login_url)

        print("请在浏览器中完成登录操作...")
        print("登录完成后按回车键继续...")
        input()
        print("继续执行...")

    def close(self):
        """
        关闭浏览器
        """
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()
        print("浏览器已关闭")


def quick_start():
    """
    快速启动方法
    """
    session = BrowserSession()
    page = session.start_browser()

    print("浏览器已启动，可以进行登录操作")
    print("程序将保持运行状态...")

    try:
        # 保持程序运行
        import time

        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n正在关闭...")
        session.close()


if __name__ == "__main__":
    quick_start()
