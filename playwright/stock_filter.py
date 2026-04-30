import csv
import re
import time
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import Page, TimeoutError

# 导入Playwright配置
try:
    # 当作为模块导入时使用相对导入
    from .playwright_config import get_default_page, quit_browser, playwright_config
except ImportError:
    # 当直接运行脚本时使用绝对导入
    from playwright_config import get_default_page, quit_browser, playwright_config

current_dir = Path(__file__).resolve().parent
def parse_stock_data(html_content, csv_path):
    soup = BeautifulSoup(html_content, "html.parser")

    # 动态提取表头字段
    headers = []
    thead = soup.select_one(".iwc-table-header")
    if thead:
        for span in thead.select("span.thead-span"):
            # 新正则表达式：去除单位符号和日期
            text = re.sub(r"[$$元%（）\d.]", "", span.get_text(strip=True))
            if text and text not in headers:  # 添加去重
                headers.append(text.strip())
    print("优化后表头:", headers)
    # 提取表格数据
    rows = []
    rows_container = soup.select("tbody tr[data-v-41d36628]:not([class*='hidden'])")
    print(f"发现 {len(rows_container)} 行数据")
    if rows_container:
        # 修改单元格选择逻辑
        for tr in rows_container:
            # 直接选择td元素，保留空单元格
            cells = tr.select("td[data-v-41d36628]")
            # 不再过滤空单元格
            cells = cells[: len(headers)]  # 保持与表头数量一致

            if len(cells) != len(headers):
                print(f"丢弃无效行: 预期 {len(headers)} 实际 {len(cells)}")
                continue

            row = {}
            for i, header in enumerate(headers):
                # 即使内容为空也保留字段位置
                cell_content = cells[i].get_text(strip=True)
                row[header] = cell_content

            # 仅收集有效数据行
            if any(row.values()):  # 过滤完全空的行
                rows.append(row)
            else:
                print("丢弃空行:", row)

    if rows:
        print("First row:", rows[0])

    # 写入CSV
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
        
    # 提取股票代码并写入txt文件
    extract_stock_codes(rows, csv_path.parent / "stock_codes.txt")

def extract_stock_codes(rows, txt_path):
    """从股票数据中提取六位股票代码并保存到txt文件"""
    stock_codes = []
    for row in rows:
        # 查找可能包含股票代码的字段
        for key, value in row.items():
            # 检查是否为6位数字代码
            if isinstance(value, str) and re.match(r'^\d{6}$', value):
                stock_codes.append(value)
                break
    
    # 去重并排序
    stock_codes = sorted(list(set(stock_codes)))
    
    # 写入txt文件，逗号分隔
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(",".join(stock_codes))
    
    print(f"股票代码已保存到: {txt_path}")
    if stock_codes:
        print(f"提取到的股票代码: {', '.join(stock_codes)}")

def crawl_iwencai_data(query):
    # 获取或初始化Playwright页面
    page = get_default_page()
    if not page:
        if not playwright_config.initialize_browser():
            raise Exception("无法初始化浏览器")
        page = get_default_page()
    
    try:
        # 导航到目标网站
        page.goto("https://www.iwencai.com/unifiedwap/result")
        
        # 等待搜索输入框加载
        print("等待搜索输入框加载...")
        page.wait_for_selector("#searchInput", state="visible", timeout=10000)
        
        # 输入查询条件
        print(f"输入查询条件: {query[:50]}...")
        input_box = page.locator("#searchInput").first
        input_box.fill(query)
        
        # 点击搜索按钮
        print("点击搜索按钮...")
        search_btn = page.locator(".search-icon").first
        search_btn.click()
        
        # 等待页面跳转
        page.wait_for_load_state("networkidle", timeout=15000)
        print("Current URL after click:", page.url)
        
        # 等待A股选项出现并点击
        try:
            page.wait_for_selector('li[title="A股"]', state="visible", timeout=10000)
            a_stock_elements = page.locator('li[title="A股"]')
            element_count = a_stock_elements.count()
            print(f"找到 {element_count} 个A股选项")
            
            # 使用第一个元素
            a_stock_element = a_stock_elements.first
            
            # 检查是否已选中
            class_attr = a_stock_element.get_attribute("class") or ""
            if "selected" not in class_attr:
                a_stock_element.click()
                print("已点击选中 A股")
            else:
                print("A股已被选中")
        except Exception as e:
            print(f"处理A股选项时出错: {e}")
            # 继续执行，可能页面已经在正确状态
        
        # 等待数据表格加载
        timestamp = time.strftime("%Y%m%d%H%M%S")
        page.wait_for_selector("tbody tr[data-v-41d36628]:not([class*='hidden'])", timeout=60000)
        
        # 可选：保存页面截图和HTML
        # page.screenshot(path=str(current_dir / f"debug_{timestamp}.png"))
        # with open(current_dir / f"page_{timestamp}.html", "w", encoding="utf-8") as f:
        #     f.write(page.content())
        
        # 获取渲染后的HTML
        html = page.content()
        return html
        
    except Exception as e:
        print(f"爬取数据时出错: {e}")
        # 可选：保存错误截图
        # page.screenshot(path=str(current_dir / "error.png"))
        raise
    
    # 注意：不要在这里关闭浏览器，因为我们使用的是全局共享的浏览器实例


# 使用示例
if __name__ == "__main__":
    try:
        # 确保data目录存在
        data_dir = current_dir / "data"
        data_dir.mkdir(exist_ok=True, parents=True)
        
        query = "近5日换手率环比增加50%以上,非ST,非新股,主板,MACD金叉后柱状线持续放大,成交里连续放大,筹码集中度90在10-20之间,(当前价格-90%成本下限)/98%成本下限<30%,当前价格<平均成本*1.15,筹码获利比例<70%,近2日成交里与价格变动同向,市盈率>8"
        html_content = crawl_iwencai_data(query)
        # with open(current_dir / "page_20250507224053.html", "r", encoding="utf-8") as f:
        #     html_content = f.read()
        #     html_content = f.read()
        parse_stock_data(html_content, data_dir / "stock_data.csv")
        print(f"数据已保存到: {data_dir / 'stock_data.csv'}")
    finally:
        # 确保在程序结束时关闭浏览器
        quit_browser()
        print("浏览器已关闭")