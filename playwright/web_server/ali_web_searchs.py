import json
import os
import random
import sys
import time
from datetime import datetime
from pathlib import Path

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.append(project_root)

from src.get_stock_k import draw_stock_k_chart
from src.news_analysis_service import NewsAnalysisService
from src.ali_search_service import AliSearchService
# 导入日志配置模块
from logger_config import LoggerConfig
from web_searchs import web_search

script_dir = Path(__file__).resolve().parent

# 初始化日志对象
logger = LoggerConfig().setup_logger()


def get_search_result(content):
    try:
        search_result = AliSearchService.stock_info_web_search(content)
        return search_result
    except Exception as e:
        logger.error(f"处理分析结果时发生错误: {e}", exc_info=True)
        return None


if __name__ == "__main__":
    content = "康哲药业改良型新药ZUNVEYL上市申请获国家药监局受理，拟用于治疗阿尔茨海默病，与之密切相关的a股上市公司有哪些"
    search_result = get_search_result(content)
    print(search_result)
