import json
import os
import sys
from pathlib import Path
import json
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.append(project_root)

from src.news_analysis_service import NewsAnalysisService
# 导入日志模块
from logger_config import LoggerConfig
from web_searchs import web_search

from src.utils import Utils
from src.get_stock_k import draw_stock_k_chart

script_dir = Path(__file__).resolve().parent

# 初始化日志配置
logger = LoggerConfig().setup_logger()


def process_news_classification(news_list, max_batch_size=80):
    try:
        if len(news_list) > max_batch_size:
            half = len(news_list) // 2
            first = NewsAnalysisService.classify_news_title(news_list[:half])
            second = NewsAnalysisService.classify_news_title(news_list[half:])
            
            # 检查返回值是否为字典
            if not isinstance(first, dict):
                logger.error(f"第一部分分类结果不是字典: {type(first)} - {first}")
                first = {}
            if not isinstance(second, dict):
                logger.error(f"第二部分分类结果不是字典: {type(second)} - {second}")
                second = {}
            
            merged = {}
            for cat in first:
                merged[cat] = first[cat] + second.get(cat, [])
            return merged
        else:
            result = NewsAnalysisService.classify_news_title(news_list)
            # 检查返回值是否为字典
            if not isinstance(result, dict):
                logger.error(f"分类结果不是字典: {type(result)} - {result}")
                return {}
            return result
    except Exception as e:
        logger.error(f"处理新闻分类时发生错误: {e}")
        return {}


def analyze_news(news_titles, news_contents, exclude_tag=None):
    input_text = ""
    for title in news_titles:
        for content in news_contents:
            if exclude_tag and "tag" in content and content["tag"] == exclude_tag:
                continue
            if isinstance(content, dict) and content.get("title") == title:
                input_text += content.get("desc", "") + "\n"
            elif isinstance(content, list):
                for item in content:
                    if item.get("title") == title:
                        input_text += item.get("desc", "") + "\n"
    raw_result = NewsAnalysisService.get_analysis_result(news_titles, input_text)
    if isinstance(raw_result, dict) and "related_news" in raw_result:
        return raw_result["related_news"]
    else:
        logger.warning(f"Unexpected result format: {raw_result}")
        return []


def process_data_source(today_path, yesterday_path, output_log, analysis_output, exclude_tag=None, need_old_compare=False):
    try:
        with open(today_path, "r", encoding="utf-8") as f:
            today_news = json.load(f)
        with open(yesterday_path, "r", encoding="utf-8") as f:
            yesterday_news = json.load(f)
    except Exception as e:
        logger.error(f"文件读取失败: {e}")
        return
    # 处理数据格式差异
    if isinstance(today_news[0], dict) and "content" in today_news[0]:
        today_list = []
        for content in today_news:
            if exclude_tag and content.get("tag") in exclude_tag:
                continue
            today_list.extend([item["title"] for item in content["content"]])
    else:
        today_list = [item["title"] for item in today_news]
    today_list = list(set(today_list))

    yesterday_list = []
    for item in yesterday_news:
        try:
            title = item.get("title")
            if title:
                yesterday_list.append(title)
        except AttributeError:
            logger.warning(f"无效数据项: {item}")
    updated_list = list(set(today_list) - set(yesterday_list))

    logger.info(f"updated_list: {len(updated_list)}")

    # 分类处理
    news_classify = process_news_classification(updated_list)
    all_classify = {
        "经济": news_classify.get("经济", []),
        "科技": news_classify.get("科技", []),
        "影视": news_classify.get("影视", []),
        "趣事": news_classify.get("趣事", []),
        "唯美": news_classify.get("唯美", []),
    }

    # 与旧数据对比（第二个数据源需要）
    if need_old_compare:
        try:
            with open(script_dir / "logs" / output_log, "r", encoding="utf-8") as f:
                old_classify = json.load(f)
            economy_new = list(set(all_classify["经济"]) - set(old_classify.get("经济", [])))
            tech_new = list(set(all_classify["科技"]) - set(old_classify.get("科技", [])))
            related_news = economy_new + tech_new
        except Exception as e:
            logger.error(f"加载历史分类数据失败: {e}")
            related_news = all_classify["经济"] + all_classify["科技"]
    else:
        related_news = all_classify["经济"] + all_classify["科技"]

    # 分析处理
    analysis_result = []
    logger.info(f"related_news: {len(related_news)}")
    if len(related_news) > 10:
        half = len(related_news) // 2
        first_part = analyze_news(related_news[:half], today_news, exclude_tag)
        second_part = analyze_news(related_news[half:], today_news, exclude_tag)
        analysis_result = first_part + second_part
    else:
        analysis_result = analyze_news(related_news, today_news, exclude_tag)
    for item in analysis_result:
        related_companies = item.get("related_company", [])
        for company in related_companies:
            stock_name = company.get("stock_name", "").strip() or None
            stock_code = company.get("stock_code", "").strip() or None
            if not stock_code and not stock_name:
                continue
            try:
                draw_stock_k_chart(stock_code, stock_name)
            except Exception as e:
                logger.error(f"生成K线图失败: {e} - {stock_code}")

    # 保存结果
    with open(script_dir / "logs" / output_log, "w", encoding="utf-8") as f:
        json.dump(all_classify, f, ensure_ascii=False, indent=4)
    with open(script_dir / "logs" / analysis_output, "w", encoding="utf-8") as f:
        json.dump(analysis_result, f, ensure_ascii=False, indent=4)


if __name__ == "__main__":
    # 处理第一个数据源（原第一个main）
    logger.info("开始处理第一个数据源...")
    process_data_source(
        today_path=script_dir / "data" / "doubao_news_search.json",
        yesterday_path=script_dir / "data" / "last_doubao_news_search.json",
        output_log="doubao_news_classification1.json",
        analysis_output="doubao_analysis_result1.json",
        exclude_tag=None,
        need_old_compare=False,
    )

    # 处理第二个数据源（原第二个main）
    logger.info("开始处理第二个数据源...")
    file_name1, file_name2 = Utils.get_latest_json_files(script_dir / "data" / "doubao")
    if file_name1:
        process_data_source(
            today_path=script_dir / "data" / "doubao" / file_name1,
            yesterday_path=script_dir / "data" / "doubao" / (file_name2 or ""),
            output_log="doubao_news_classification2.json",
            analysis_output="doubao_analysis_result2.json",
            exclude_tag=["体育", "数码"],
            need_old_compare=True,
        )
