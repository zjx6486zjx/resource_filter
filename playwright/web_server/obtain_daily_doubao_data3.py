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
# 导入日志配置模块
from logger_config import LoggerConfig
from web_searchs import web_search

script_dir = Path(__file__).resolve().parent

# 初始化日志对象
logger = LoggerConfig().setup_logger()


def process_analysis_result(analysis_result):
    try:
        newest_title = analysis_result["related_news_title"]
        logger.info(f"处理标题: {newest_title}")

        search_background_prompt = (
            f"搜索`{newest_title}`-资讯相关信息，根据最近一年的相关消息，判断直接相关的A股上市公司都有哪些，"
            "要明确直接相关的，不要推测相关性。并且列出这些公司的名称，代码，主营业务，营收占比，市盈率以及近期减持情况。"
        )
        text1 = web_search(search_background_prompt)
        if not text1:
            logger.warning(f"未找到与标题 '{newest_title}' 相关的信息")
            return None

        detailed_result = NewsAnalysisService.analysis_news_detailed_result(newest_title, text1)
        return detailed_result
    except Exception as e:
        logger.error(f"处理分析结果时发生错误: {e}", exc_info=True)
        return None


if __name__ == "__main__":
    try:
        # 读取两个分析结果文件
        with open(script_dir / "logs" / "doubao_analysis_result1.json", "r", encoding="utf-8") as file:
            doubao_analysis_result1 = json.load(file)
        with open(script_dir / "logs" / "doubao_analysis_result2.json", "r", encoding="utf-8") as file:
            doubao_analysis_result2 = json.load(file)

        # 合并并去重
        analysis_results = doubao_analysis_result1 + doubao_analysis_result2
        seen_titles = set()
        unique_analysis_results = []

        for result in analysis_results:
            title = result.get("related_news_title")
            if title and title not in seen_titles:
                seen_titles.add(title)
                unique_analysis_results.append(result)

        logger.info(f"去重后共 {len(unique_analysis_results)} 条唯一新闻")

        new_analysis_results = []

        output_path = script_dir / "logs" / "doubao_analysis_result0.json"
        for analysis_result in unique_analysis_results:
            result = process_analysis_result(analysis_result)
            if result is not None:
                new_analysis_results.append(result)
                # 保留原有随机延时
                time.sleep(random.uniform(5, 10))

                # 检查result是否为字典类型，避免'list' object has no attribute 'get'错误
                if isinstance(result, dict):
                    companys = result.get("related_company", [])
                    for company in companys:
                        try:
                            draw_stock_k_chart(company["stock_code"], company["stock_name"])
                        except Exception as e:
                            logger.error(f"生成K线图失败: {e} - {company['stock_code']}")
                elif isinstance(result, list):
                    # 如果result是列表，遍历列表中的每个元素
                    for item in result:
                        if isinstance(item, dict):
                            companys = item.get("related_company", [])
                            for company in companys:
                                try:
                                    draw_stock_k_chart(company["stock_code"], company["stock_name"])
                                except Exception as e:
                                    logger.error(f"生成K线图失败: {e} - {company['stock_code']}")
                else:
                    logger.warning(f"result不是字典类型，跳过股票图表生成: {type(result)}")
        
        # 写入最终结果
            with open(output_path, "w", encoding="utf-8") as file:
                json.dump(new_analysis_results, file, ensure_ascii=False, indent=4)
        logger.info(f"结果已写入 {output_path}")
    except Exception as e:
        logger.error(f"主程序运行时发生错误: {e}", exc_info=True)
