import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from api.llm_client import LLMApiClient
from api.response_parser import ResponseParser
from src.prompt import base_prompts

llm_client = LLMApiClient()

response_parser = ResponseParser()


class NewsAnalysisService:
    @staticmethod
    def classify_news_title(newest_content):
        prompt = base_prompts.classify_news_title.format_map({"newest_content": newest_content})
        response = ResponseParser.safe_call(llm_client.doubao_json_chat, prompt)
        return response_parser.parse_response(response)

    @staticmethod
    def analysis_entertainment_news_title(newest_content):
        prompt = base_prompts.analysis_entertainment_news_title.format_map({"newest_content": newest_content})
        response = ResponseParser.safe_call(llm_client.doubao_json_chat, prompt)
        return response_parser.parse_response(response)

    @staticmethod
    def get_analysis_result(newest_title, related_news):
        prompt = base_prompts.gen_analysis_result.format_map({"newest_title": newest_title, "related_news": related_news})
        response = ResponseParser.safe_call(llm_client.doubao_json_chat, prompt)
        if response is None:
            return {"related_news": []}  # 防止返回None
        
        parsed_response = response_parser.parse_response(response)
        
        # 处理LLM返回列表格式的情况
        if isinstance(parsed_response, list) and len(parsed_response) > 0:
            if isinstance(parsed_response[0], dict) and "related_news" in parsed_response[0]:
                return parsed_response[0]
        
        # 处理正常字典格式
        if isinstance(parsed_response, dict) and "related_news" in parsed_response:
            return parsed_response
            
        # 兜底返回空结果
        return {"related_news": []}

    @staticmethod
    def analysis_news_detailed_result(newest_title, newest_content):
        prompt = base_prompts.analysis_news_detailed_result.format_map(
            {"newest_title": newest_title, "newest_content": newest_content}
        )
        response = ResponseParser.safe_call(llm_client.doubao_json_chat, prompt)
        return response_parser.parse_response(response)

    def summarize_web_content(web_content):
        prompt = base_prompts.summarize_web_content.format_map({"web_content": web_content})
        response = ResponseParser.safe_call(llm_client.doubao_json_chat, prompt)
        return response_parser.parse_response(response)

    def analyze_web_content(web_content):
        prompt = base_prompts.analyze_web_content.format_map({"web_content": web_content})
        response = ResponseParser.safe_call(llm_client.doubao_json_chat, prompt)
        return response_parser.parse_response(response)
