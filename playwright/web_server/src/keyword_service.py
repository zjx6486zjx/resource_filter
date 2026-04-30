#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
关键词生成服务
"""

import json
import os
import sys
from typing import List, Optional

# 添加路径以导入API客户端
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.append(project_root)
sys.path.append(os.path.join(project_root, "func"))

from api.llm_client import LLMApiClient
from api.response_parser import ResponseParser
from src.prompt import xhs_prompts


class KeywordGenerationService:
    """
    关键词生成服务类
    """
    
    def __init__(self):
        self.llm_client = LLMApiClient()
    
    @staticmethod
    def generate_keywords(content: str, max_keywords: int = 10) -> Optional[str]:
        """
        为给定内容生成关键词
        
        Args:
            content (str): 要生成关键词的内容
            max_keywords (int): 最大关键词数量
            
        Returns:
            Optional[str]: 生成的关键词字符串，以空格分隔
        """
        if not content or not content.strip():
            return None
            
        try:
            # 创建服务实例
            service = KeywordGenerationService()
            
            # 构建提示词
            prompt = f"""
请为以下内容生成{max_keywords}个关键词，要求：
1. 关键词要准确反映内容主题
2. 关键词之间用空格分隔
3. 优先选择核心概念和重要术语
4. 避免过于通用的词汇
5. 只返回关键词，不要其他解释

内容：
{content}

关键词："""
            
            # 调用LLM生成关键词
            response = ResponseParser.safe_call(service.llm_client.doubao_text_chat, prompt)
            
            if response and response.strip():
                # 清理和格式化关键词
                keywords = response.strip()
                # 移除可能的标点符号和多余空格
                keywords = ' '.join(keywords.replace(',', ' ').replace('，', ' ').split())
                return keywords
            else:
                print("LLM返回空响应")
                return None
                
        except Exception as e:
            print(f"关键词生成失败: {e}")
            return None
    
    def generate_keywords_batch(self, contents: List[str], max_keywords: int = 10) -> List[Optional[str]]:
        """
        批量生成关键词
        
        Args:
            contents (List[str]): 内容列表
            max_keywords (int): 每个内容的最大关键词数量
            
        Returns:
            List[Optional[str]]: 关键词列表
        """
        results = []
        for content in contents:
            keywords = self.generate_keywords(content, max_keywords)
            results.append(keywords)
        return results