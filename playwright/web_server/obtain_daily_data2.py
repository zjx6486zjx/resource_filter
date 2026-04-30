import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.append(project_root)

from src.news_analysis_service import NewsAnalysisService
# 导入日志模块
from logger_config import LoggerConfig
from web_searchs import web_search

script_dir = Path(__file__).resolve().parent

# 初始化日志配置
logger = LoggerConfig().setup_logger()


def extract_contents(file_key, hot_key):
    try:
        file_path = script_dir / "data" / f"{file_key}.json"
        with open(file_path, "r", encoding="utf-8") as file:
            data = json.load(file)
        contents = []
        for item in data.get(hot_key, []):
            contents.append(item.get("title", ""))
        return contents
    except Exception as e:
        logger.error(f"读取文件 {file_key} 时发生错误: {e}", exc_info=True)
        return []


def many_platforms_hot_news_jobs(file_key, platform_key):
    try:
        if platform_key == "news":
            platforms = [
                "baidu",
                "360",
                "sougou",
                "sm",
                "bing",
                "toutiao",
                "jrcitiao",
                "chinaso",
                "cctv",
            ]
        elif platform_key == "entertainment":
            platforms = ["sm", "douyin", "citiao"]
        elif platform_key == "video":
            platforms = ["douyin", "bilibiliso", "acfun", "acfunwz"]
        elif platform_key == "meaning":
            platforms = ["lishi", "baike", "phrase", "heimao"]
        else:
            logger.warning(f"未知平台类型: {platform_key}")
            return []

        all_news = []
        for platform in platforms:
            contents = extract_contents(file_key, platform)
            news = {"platform": platform, "contents": contents}
            all_news.append(news)
        return all_news
    except Exception as e:
        logger.error(f"获取平台热点新闻时出错: {e}", exc_info=True)
        return []


if __name__ == "__main__":
    try:
        # 新闻数据处理
        yesterday_news_contents = many_platforms_hot_news_jobs("last_tianchen_hotlist", "news")
        today_news_contents = many_platforms_hot_news_jobs("tianchen_hotlist", "news")

        today_list = list(set([item for content in today_news_contents for item in content["contents"]]))
        yesterday_list = list(set([item for content in yesterday_news_contents for item in content["contents"]]))

        updated_list = [item for item in today_list if item not in yesterday_list]
        news_classification = NewsAnalysisService.classify_news_title(updated_list)

        # 娱乐数据处理
        yesterday_entertainment_contents = many_platforms_hot_news_jobs("last_tianchen_hotlist", "entertainment")
        today_entertainment_contents = many_platforms_hot_news_jobs("tianchen_hotlist", "entertainment")

        today_entertainment_list = list(set([item for content in today_entertainment_contents for item in content["contents"]]))
        yesterday_entertainment_list = list(
            set([item for content in yesterday_entertainment_contents for item in content["contents"]])
        )

        updated_entertainment_list = [item for item in today_entertainment_list if item not in yesterday_entertainment_list]
        entertainment_classification = NewsAnalysisService.classify_news_title(updated_entertainment_list)

        # 合并分类结果
        all_classification = {
            "经济": list(set(news_classification["经济"] + entertainment_classification["经济"])),
            "科技": list(set(news_classification["科技"] + entertainment_classification["科技"])),
            "影视": list(set(news_classification["影视"] + entertainment_classification["影视"])),
            "趣事": list(set(news_classification["趣事"] + entertainment_classification["趣事"])),
            "唯美": list(set(news_classification["唯美"] + entertainment_classification["唯美"])),
        }

        # 写入分类结果
        output_path = script_dir / "logs" / "news_classification.json"
        with open(output_path, "w", encoding="utf-8") as file:
            json.dump(all_classification, file, ensure_ascii=False, indent=4)
        logger.info(f"分类结果已写入 {output_path}")

        # 分析经济+科技类新闻
        economy_news = all_classification["经济"]
        technology_news = all_classification["科技"]
        technology_economy_content = f"经济类：{economy_news}\n科技类：{technology_news}"
        analysis_result_detailed = NewsAnalysisService.analysis_entertainment_news_title(technology_economy_content)
        
        # 检查返回值类型，确保是字典
        if isinstance(analysis_result_detailed, dict):
            related_news_titles = analysis_result_detailed.get("related_news_title", [])
        elif isinstance(analysis_result_detailed, list):
            # 如果返回的是列表，直接使用
            related_news_titles = analysis_result_detailed
        else:
            logger.warning(f"analysis_entertainment_news_title返回了意外的类型: {type(analysis_result_detailed)}")
            related_news_titles = []
            
        length = len(related_news_titles)
        print(related_news_titles)
        logger.info(f"需分析的新闻标题数量: {length}")

        related_news = []
        if length == 0:
            logger.info("没有需要分析的新闻标题，跳过分析步骤")
            analysis_result = []
        elif length <= 20:
            for title in related_news_titles:
                query = f"'{title}'与之直接相关的上市公司有哪些，不要推测相关的，只要一年内有消息证实直接相关的"
                result = web_search(query)
                related_news.append({title: result})
                time.sleep(1)  # 防止请求过快

            if 10 < length <= 20:
                half = length // 2
                first_half_titles = related_news_titles[:half]
                second_half_titles = related_news_titles[half:]
                input_first = "\n".join([next(iter(news.values())).split("+", 1)[0] for news in related_news[:half]])
                input_second = "\n".join([next(iter(news.values())).split("+", 1)[0] for news in related_news[half:]])

                first_result = NewsAnalysisService.get_analysis_result(first_half_titles, input_first)["related_news"]
                second_result = NewsAnalysisService.get_analysis_result(second_half_titles, input_second)["related_news"]
                analysis_result = first_result + second_result
            else:
                input_text = "\n".join([next(iter(news.values())) for news in related_news])
                analysis_result = NewsAnalysisService.get_analysis_result(related_news_titles, input_text)["related_news"]
        elif 20 < length <= 150:
            analysis_result = NewsAnalysisService.get_analysis_result(related_news_titles, "无")["related_news"]
        else:
            half = length // 2
            first_half_titles = related_news_titles[:half]
            second_half_titles = related_news_titles[half:]

            first_result = NewsAnalysisService.get_analysis_result(first_half_titles, "无")["related_news"]
            second_result = NewsAnalysisService.get_analysis_result(second_half_titles, "无")["related_news"]
            analysis_result = first_result + second_result

        # 写入分析结果
        analysis_output_path = script_dir / "logs" / "analysis_result.json"
        with open(analysis_output_path, "w", encoding="utf-8") as file:
            json.dump(analysis_result, file, ensure_ascii=False, indent=4)
        logger.info(f"分析结果已写入 {analysis_output_path}")

    except Exception as e:
        logger.error(f"主程序运行时发生错误: {e}", exc_info=True)
