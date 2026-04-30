import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from api.llm_client import AliAPI
from api.response_parser import ResponseParser
from src.prompt import base_prompts

llm_client = AliAPI()

response_parser = ResponseParser()


class AliSearchService:
    @staticmethod
    def stock_info_web_search(stock_name):
        prompt = base_prompts.stock_info_web_search.format_map({"stock_name": stock_name})
        enable_search = True
        response = ResponseParser.safe_call(llm_client.ali_text_chat, prompt, enable_search)
        return response_parser.parse_response(response)

