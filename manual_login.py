from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright


DEFAULT_XHS_URL = "https://www.xiaohongshu.com/explore"
DEFAULT_XHS_PROFILE = "/mnt/d/project/resource_filter/user_data/xhs_profile"
DEFAULT_MJ_URL = "https://www.midjourney.com/explore?tab=top"
DEFAULT_MJ_PROFILE = "/mnt/d/project/resource_filter/user_data/mj_profile"
NAVIGATION_TIMEOUT_MS = 90000
POST_NAVIGATION_TIMEOUT_MS = 15000


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="打开持久化浏览器，手动完成站点登录")
    parser.add_argument("--site", default="xhs", help="站点名称，当前支持 xhs、mj 等需要手动登录/验证的站点")
    parser.add_argument("--url", default="", help="打开后默认访问的页面 URL")
    parser.add_argument(
        "--user-data-dir",
        default=os.getenv("RESOURCE_FILTER_USER_DATA_DIR", DEFAULT_XHS_PROFILE),
        help="要写入登录态的浏览器用户目录",
    )
    parser.add_argument(
        "--browser-channel",
        default=os.getenv("RESOURCE_FILTER_BROWSER_CHANNEL", "chrome"),
        help="浏览器通道，例如 chrome、msedge、chromium",
    )
    parser.add_argument(
        "--browser-mode",
        choices=("auto", "chrome", "playwright"),
        default=os.getenv("RESOURCE_FILTER_MANUAL_BROWSER_MODE", "auto"),
        help="手动登录浏览器模式；mj 默认用系统 Chrome，xhs 默认用 Playwright",
    )
    parser.add_argument(
        "--proxy-server",
        default=os.getenv("RESOURCE_FILTER_PROXY_SERVER", ""),
        help="Playwright 浏览器代理，例如 http://127.0.0.1:7890 或 socks5://127.0.0.1:7890",
    )
    parser.add_argument(
        "--remote-debugging-port",
        type=int,
        default=int(os.getenv("RESOURCE_FILTER_REMOTE_DEBUGGING_PORT", "9222") or "9222"),
        help="系统 Chrome 调试端口；用于让抓取器通过 CDP 连接同一个浏览器会话",
    )
    parser.add_argument("--slow-mo", type=int, default=100, help="Playwright slow_mo，毫秒")
    return parser


def normalize_target_url(site_name: str, url: str) -> str:
    normalized_site = str(site_name or "").strip().lower()
    normalized_url = str(url or "").strip()
    if normalized_url:
        return normalized_url
    if normalized_site == "xhs":
        return DEFAULT_XHS_URL
    if normalized_site == "mj":
        return DEFAULT_MJ_URL
    return normalized_url or "https://www.google.com"


def normalize_user_data_dir(site_name: str, user_data_dir: str) -> str:
    normalized_site = str(site_name or "").strip().lower()
    normalized_dir = str(user_data_dir or "").strip()
    if normalized_dir and normalized_dir != DEFAULT_XHS_PROFILE:
        return normalized_dir
    if normalized_site == "mj":
        return DEFAULT_MJ_PROFILE
    return normalized_dir or DEFAULT_XHS_PROFILE


def normalize_proxy_server(proxy_server: str) -> str:
    normalized = str(proxy_server or "").strip()
    if not normalized:
        return ""
    if "://" in normalized:
        return normalized
    return f"http://{normalized}"


def cleanup_profile_locks(user_data_dir: Path) -> None:
    for pattern in ("Singleton*", "*.lock", "LOCK"):
        for lock_path in user_data_dir.glob(pattern):
            if lock_path.is_file() or lock_path.is_symlink():
                lock_path.unlink(missing_ok=True)

    default_dir = user_data_dir / "Default"
    if default_dir.exists():
        for pattern in ("LOCK", "*.lock"):
            for lock_path in default_dir.glob(pattern):
                if lock_path.is_file() or lock_path.is_symlink():
                    lock_path.unlink(missing_ok=True)


def resolve_browser_executable_path(browser_channel: str) -> Optional[str]:
    normalized_channel = str(browser_channel or "").strip().lower()
    channel_candidates = {
        "chrome": (
            "google-chrome",
            "google-chrome-stable",
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
        ),
        "msedge": (
            "microsoft-edge",
            "microsoft-edge-stable",
            "/usr/bin/microsoft-edge",
            "/usr/bin/microsoft-edge-stable",
        ),
        "chromium": (
            "chromium",
            "chromium-browser",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
        ),
    }
    candidates = channel_candidates.get(normalized_channel, ())
    if not candidates and normalized_channel:
        candidates = (normalized_channel,)

    for candidate in candidates:
        resolved = candidate if candidate.startswith("/") else shutil.which(candidate)
        if resolved and os.path.exists(resolved):
            return resolved
    return None


def resolve_browser_executable(playwright, browser_channel: str) -> tuple[object, dict]:
    normalized_channel = str(browser_channel or "").strip().lower()
    browser_type = playwright.chromium
    launch_kwargs: dict = {}

    executable_path = resolve_browser_executable_path(browser_channel)
    if executable_path:
        launch_kwargs["executable_path"] = executable_path
        return browser_type, launch_kwargs

    if normalized_channel:
        launch_kwargs["channel"] = normalized_channel
    return browser_type, launch_kwargs


def resolve_browser_mode(site_name: str, browser_mode: str) -> str:
    normalized_mode = str(browser_mode or "").strip().lower()
    if normalized_mode in ("chrome", "playwright"):
        return normalized_mode
    if str(site_name or "").strip().lower() == "mj":
        return "chrome"
    return "playwright"


def run_external_chrome_login(
    user_data_dir: str,
    target_url: str,
    browser_channel: str,
    proxy_server: str,
    remote_debugging_port: int,
) -> int:
    profile_dir = Path(user_data_dir).expanduser().resolve()
    profile_dir.mkdir(parents=True, exist_ok=True)
    cleanup_profile_locks(profile_dir)

    executable_path = resolve_browser_executable_path(browser_channel)
    if not executable_path:
        raise FileNotFoundError(f"未找到系统浏览器：{browser_channel}")

    command = [
        executable_path,
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-gpu",
        "--disable-software-rasterizer",
        "--disable-quic",
        f"--remote-debugging-port={max(remote_debugging_port, 0)}",
        "--remote-debugging-address=127.0.0.1",
    ]
    normalized_proxy = normalize_proxy_server(proxy_server)
    if normalized_proxy:
        command.append(f"--proxy-server={normalized_proxy}")
    command.append(target_url)

    process = subprocess.Popen(command)
    try:
        print(f"已打开系统 Chrome，用户目录: {profile_dir}")
        print(f"当前页面: {target_url}")
        print(f"CDP 地址: http://127.0.0.1:{max(remote_debugging_port, 0)}")
        print("请在浏览器里完成 Midjourney 登录/验证；抓取完成后再回到终端按回车关闭浏览器。")
        input()
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    return 0


def run_playwright_manual_login(
    user_data_dir: str,
    target_url: str,
    browser_channel: str,
    proxy_server: str,
    slow_mo: int,
) -> int:
    profile_dir = Path(user_data_dir).expanduser().resolve()
    profile_dir.mkdir(parents=True, exist_ok=True)
    cleanup_profile_locks(profile_dir)

    with sync_playwright() as playwright:
        browser_type, launch_kwargs = resolve_browser_executable(playwright, browser_channel)
        normalized_proxy = normalize_proxy_server(proxy_server)
        if normalized_proxy:
            launch_kwargs["proxy"] = {"server": normalized_proxy}

        context = browser_type.launch_persistent_context(
            str(profile_dir),
            headless=False,
            slow_mo=max(slow_mo, 0),
            viewport={"width": 1440, "height": 1200},
            ignore_https_errors=True,
            args=["--disable-gpu", "--disable-software-rasterizer"],
            **launch_kwargs,
        )
        page = context.new_page()
        try:
            try:
                page.goto(target_url, wait_until="commit", timeout=NAVIGATION_TIMEOUT_MS)
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=POST_NAVIGATION_TIMEOUT_MS)
                except PlaywrightTimeoutError:
                    try:
                        page.evaluate("window.stop()")
                    except Exception:
                        pass
            except PlaywrightTimeoutError as exc:
                print(f"页面打开超时，浏览器已保留给你手动处理：{exc}")
            try:
                page.bring_to_front()
            except Exception:
                pass
            print(f"已打开浏览器，用户目录: {profile_dir}")
            print(f"当前页面: {target_url}")
            print("请在浏览器里完成登录；登录完成后回到终端按回车保存并关闭。")
            input()
        finally:
            context.close()
    return 0


def run_manual_login(
    site_name: str,
    user_data_dir: str,
    target_url: str,
    browser_channel: str,
    browser_mode: str,
    proxy_server: str,
    remote_debugging_port: int,
    slow_mo: int,
) -> int:
    resolved_mode = resolve_browser_mode(site_name, browser_mode)
    if resolved_mode == "chrome":
        return run_external_chrome_login(
            user_data_dir,
            target_url,
            browser_channel,
            proxy_server,
            remote_debugging_port,
        )
    return run_playwright_manual_login(user_data_dir, target_url, browser_channel, proxy_server, slow_mo)


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    target_url = normalize_target_url(args.site, args.url)
    user_data_dir = normalize_user_data_dir(args.site, args.user_data_dir)
    return run_manual_login(
        args.site,
        user_data_dir,
        target_url,
        args.browser_channel,
        args.browser_mode,
        args.proxy_server,
        args.remote_debugging_port,
        args.slow_mo,
    )


if __name__ == "__main__":
    raise SystemExit(main())
