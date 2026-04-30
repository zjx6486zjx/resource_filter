import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("MPLBACKEND", "Agg")
import matplotlib
matplotlib.use("Agg", force=True)
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd
import tushare as ts
from dotenv import load_dotenv

# 加载 .env 文件中的环境变量
load_dotenv()

# 从环境变量中获取 Tushare API 密钥
TUSHARE_API_KEY = os.getenv("TUSHARE_API_KEY")

# 初始化 pro 接口
pro = ts.pro_api(TUSHARE_API_KEY)

script_dir = Path(__file__).resolve().parent.parent
pic_dir = script_dir / "pic"
os.makedirs(pic_dir, exist_ok=True)


def get_today_date_formatted():
    # 获取今天的日期
    today = datetime.today()
    # 格式化为 YYYYMMDD 形式
    formatted_date = today.strftime("%Y%m%d")
    return formatted_date


today = get_today_date_formatted()


# 新增文件缓存路径 ↓↓↓
CACHE_DIR = script_dir / "cache"
os.makedirs(CACHE_DIR, exist_ok=True)
STOCK_CACHE_PATH = CACHE_DIR / "stock_basic_cache.pkl"

# +++ 新增全局变量初始化 +++
_STOCK_BASIC_CACHE = None
_LAST_FETCH_TIME = 0


# 修改后的缓存加载逻辑 ↓↓↓
def get_stock_code_by_name(stock_name):
    global _STOCK_BASIC_CACHE, _LAST_FETCH_TIME

    # 优先从文件加载缓存
    if (_STOCK_BASIC_CACHE is None or _STOCK_BASIC_CACHE.empty) and STOCK_CACHE_PATH.exists():
        with open(STOCK_CACHE_PATH, "rb") as f:
            _STOCK_BASIC_CACHE = pd.read_pickle(f)
            _LAST_FETCH_TIME = os.path.getmtime(STOCK_CACHE_PATH)

    # 增加缓存有效期检查（24小时）
    if "_STOCK_BASIC_CACHE" not in globals() or (time.time() - _LAST_FETCH_TIME > 86400):
        # 添加重试机制
        try:
            _STOCK_BASIC_CACHE = pro.stock_basic(exchange="", list_status="L", fields="ts_code,name")
            _LAST_FETCH_TIME = time.time()
            with open(STOCK_CACHE_PATH, "wb") as f:
                pd.to_pickle(_STOCK_BASIC_CACHE, f)
            print(f"✅ 已缓存股票基本信息（共 {len(_STOCK_BASIC_CACHE)} 条）")
        except Exception as e:
            print(f"获取股票基本信息失败: {str(e)}")
            _STOCK_BASIC_CACHE = pd.DataFrame()
    if _STOCK_BASIC_CACHE is None or _STOCK_BASIC_CACHE.empty:
        print("❌ 股票基本信息缓存未加载或为空")
        return None
    name_to_code = dict(zip(_STOCK_BASIC_CACHE["name"], _STOCK_BASIC_CACHE["ts_code"]))

    # 优化后的模糊匹配逻辑
    simplified_name = re.sub(r"[\s+A股]", "", stock_name).lower()
    for name, code in name_to_code.items():
        clean_name = re.sub(r"[\s+A股]", "", name).lower()
        if simplified_name in clean_name:
            return code
    return None


def get_stock_klines(ts_code, start_date="20240101"):
    try:
        # 尝试获取最近5年的数据
        df = pro.daily(ts_code=ts_code, start_date="20240101", end_date=today)
        print(df)
        if df.empty:
            print(f"⚠️ 股票{ts_code}无历史数据，可能原因：1.代码错误 2.新上市股票 3.长期停牌")
            return pd.DataFrame()  # 返回空DataFrame而不是抛出异常
        return df[["trade_date", "open", "high", "low", "close", "vol"]]
    except Exception as e:
        print(f"获取股票数据异常 {ts_code}: {str(e)}")
        return pd.DataFrame()


def validate_stock_code(ts_code):
    try:
        original_code = ts_code
        # 处理市场后缀格式
        if "." in ts_code:
            code_part, suffix = ts_code.split(".")
            suffix = suffix.upper().replace("SHG", "SH").replace("SHE", "SZ")
            if suffix not in ("SH", "SZ"):
                print(f"❌ 异常市场后缀: {original_code}")
                return False
            ts_code = f"{code_part}.{suffix}"
        else:
            # 自动补全市场后缀
            if ts_code.startswith(("6", "5", "9", "7")):
                ts_code += ".SH"
            else:
                ts_code += ".SZ"

        # 格式校验（6位数字+后缀）
        if not re.match(r"^\d{6}\.(SH|SZ)$", ts_code):
            print(f"❌ 非法股票代码格式: {original_code} -> {ts_code}")
            return False

        # 交易所前缀规则校验
        code_part = ts_code.split(".")[0]
        if ts_code.endswith(".SH"):
            # 上交所代码必须以6/5/9/7开头
            if not code_part[0] in {"6", "5", "9", "7"}:
                print(f"❌ 上交所代码需以6/5/9/7开头: {original_code}")
                return False
        elif ts_code.endswith(".SZ"):
            # 深交所代码需以0/2/3开头
            if not (code_part.startswith("0") or code_part.startswith("2") or code_part.startswith("3")):
                print(f"❌ 深交所代码需以0/2/3开头: {original_code}")
                return False
        return True
    except Exception as e:
        print(f"验证股票代码异常 {original_code}: {str(e)}")
        return False


def draw_stock_k_chart(stock_code, stock_name):
    # +++ 新增代码：当 stock_code 为空时通过名称获取代码 +++
    if not stock_code and stock_name:
        print(f"🔄 正在通过名称获取股票代码: {stock_name}")
        stock_code = get_stock_code_by_name(stock_name)
        if not stock_code:
            print(f"❌ 无法通过名称找到股票代码: {stock_name}")
            return None

    # +++ 新增代码验证股票代码 +++
    if not validate_stock_code(stock_code):
        print(f"❌ 无效的股票代码: {stock_code} (名称: {stock_name})")
        return None

    stock_dir = pic_dir / "stock"
    try:
        # 合并重复的日期生成逻辑
        now = datetime.now()
        if now.hour < 9:
            adjusted_date = now - timedelta(days=1)
        else:
            adjusted_date = now

        today_str = adjusted_date.strftime("%Y%m%d")
        save_filename = f"{stock_name}_{today_str}.jpg"
        save_path = stock_dir / save_filename
        expected_path = save_path  # 直接使用统一路径变量

        # 统一提前创建目录（原代码中有os.makedirs但未显式创建stock_dir）
        os.makedirs(stock_dir, exist_ok=True)

        if expected_path.exists():
            print(f"✅ 今日图片已存在: {expected_path}")
            return expected_path
        # --- 检查结束 ---

        data = get_stock_klines(stock_code)  # 获取 K 线数据
        if data.empty:
            print(f"No data available for stock: {stock_code}")
            return None

        df = pd.DataFrame(data)

        # +++ 新增数据处理步骤 +++
        # 转换日期格式并设置为索引
        df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d")
        df.set_index("trade_date", inplace=True)
        df = df.sort_index(ascending=True)  # 确保按时间升序排列

        # 将 "vol" 列重命名为 "volume"
        df.rename(columns={"vol": "volume"}, inplace=True)

        # 正确实现MA48的滚动窗口计算
        df["SMA_48"] = df["close"].rolling(window=48, min_periods=48, closed="left").mean()

        df["SMA_4"] = df["close"].rolling(window=4, min_periods=4).mean()
        df["SMA_8"] = df["close"].rolling(window=8, min_periods=8).mean()

        df_plot = df.tail(60).sort_index(ascending=True)  # 保留时间升序
        df_plot = df_plot[df_plot["SMA_48"].notna()]  # 过滤无效MA值

        # 创建用于叠加的子图（SMA线放置在主图中，并调整透明度）
        apds = [
            mpf.make_addplot(df_plot["SMA_4"], color="k", alpha=0.3, panel=0),
            mpf.make_addplot(df_plot["SMA_8"], color="y", alpha=0.4, panel=0),
            mpf.make_addplot(df_plot["SMA_48"], color="purple", alpha=0.5, panel=0),
        ]

        df["color"] = ["g"] + ["r" if df["close"].iloc[i] < df["close"].iloc[i - 1] else "g" for i in range(1, len(df))]

        # 创建自定义市场颜色
        mc = mpf.make_marketcolors(
            up="white",
            down="green",
            edge={"up": "red", "down": "green"},
            wick={"up": "red", "down": "green"},
            volume={"up": "red", "down": "green"},
            inherit=False,
        )

        s = mpf.make_mpf_style(marketcolors=mc)

        df_plot = df.tail(60).sort_index(ascending=True)

        # 创建用于叠加的子图（SMA线放置在主图中，并调整透明度）
        apds = [
            mpf.make_addplot(df_plot["SMA_4"], color="k", alpha=0.3, panel=0),  # 放置在主图，降低透明度
            mpf.make_addplot(df_plot["SMA_8"], color="y", alpha=0.4, panel=0),  # 放置在主图，降低透明度
            mpf.make_addplot(df_plot["SMA_48"], color="purple", alpha=0.5, panel=0),  # 放置在主图，降低透明度
        ]

        # 绘制 K 线图和移动平均线
        fig, axlist = mpf.plot(
            df_plot,
            type="candle",
            style=s,
            title={
                "title": stock_code,
                "fontsize": 14,
                "color": "red",
            },
            ylabel="Price",
            addplot=apds,
            xrotation=0,
            datetime_format="%Y-%m-%d",
            volume=True,  # 显示默认成交量
            panel_ratios=(3, 1),  # 主图与子图的高度比例
            returnfig=True,  # 返回 figure 和 axes 对象
        )

        # 获取成交量子图的 axes
        volume_ax = axlist[2]  # 第三个 axes 是成交量子图

        # 清空默认成交量柱状图
        volume_ax.clear()
        # 修改 X 轴标签，只显示四个日期
        num_dates_to_show = 4  # 只显示四个日期
        xticks_indices = range(0, len(df_plot), len(df_plot) // num_dates_to_show)  # 均匀选择刻度位置
        xticks_labels = df_plot.index.strftime("%Y-%m-%d")[:: len(df_plot) // num_dates_to_show]  # 对应的日期标签

        volume_ax.set_xticks(xticks_indices)
        volume_ax.set_xticklabels(xticks_labels, rotation=0)

        # 手动绘制成交量柱状图，并确保宽度固定
        width = 0.8  # 固定柱子宽度
        for i, (idx, row) in enumerate(df_plot.iterrows()):
            color = "white" if row["close"] >= row["open"] else "green"
            edgecolor = "red" if row["close"] >= row["open"] else "white"
            volume_ax.bar(i, row["volume"], width=width, color=color, edgecolor=edgecolor, linewidth=1)

        # 确保 X 轴范围正确，避免柱子被压缩或拉伸
        volume_ax.set_xlim(-0.5, len(df_plot) - 0.5)

        # 封装重复的成交量绘制逻辑
        def plot_volume_bar(ax, df_plot):
            width = 0.8
            for i, (idx, row) in enumerate(df_plot.iterrows()):
                color = "white" if row["close"] >= row["open"] else "green"
                edgecolor = "red" if row["close"] >= row["open"] else "white"
                ax.bar(i, row["volume"], width=width, color=color, edgecolor=edgecolor, linewidth=1)
            ax.set_xlim(-0.5, len(df_plot) - 0.5)

        plot_volume_bar(volume_ax, df_plot)

        # 生成最终路径（与检查路径相同）
        plt.savefig(expected_path, format="jpg", dpi=300)
        plt.close(fig)

        # 删除同股票名的其他图片
        for existing_file in stock_dir.glob(f"{stock_name}_*.jpg"):
            if existing_file != save_path:
                existing_file.unlink()

        # 更新统计CSV
        csv_path = stock_dir / "stock_stats.csv"
        new_row = pd.DataFrame([{"stock_name": stock_name, "stock_code": stock_code, "count": 1}])
        if csv_path.exists():
            df_stats = pd.read_csv(csv_path)
            df_stats = pd.concat([df_stats, new_row], ignore_index=True)
            df_stats = df_stats.groupby(["stock_name", "stock_code"], as_index=False).agg({"count": "sum"})
        else:
            df_stats = new_row

        df_stats.to_csv(csv_path, index=False)

        return save_path

    except Exception as e:
        print(f"Error occurred while drawing chart for {stock_code}: {e}")
        return None


def refresh_cache_job():
    global _STOCK_BASIC_CACHE
    _STOCK_BASIC_CACHE = None
    print("🕖 定时任务：强制刷新股票缓存")


if __name__ == "__main__":
    # stock_names = ["贵州茅台", "山东黄金", "中金黄金"]
    # for stock_name in stock_names:
    stock_code = "600267.SH"
    stock_name = "海正药业"
    save_path = draw_stock_k_chart(stock_code, stock_name)
    if save_path is None:
        print(f"Failed to generate chart for stock: {stock_code}")
    print(f"K 线图已保存到 {save_path}")
