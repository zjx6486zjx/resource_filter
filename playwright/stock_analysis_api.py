#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票分析API接口
提供与stock_analysis.html前端页面对应的后端逻辑
"""

import sys
import os
import json
from pathlib import Path
from flask import Blueprint, request, jsonify

# 添加项目根目录到Python路径
project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

# 导入web_searchs模块
web_searchs_path = project_root / "func" / "playwright" / "web_server"
sys.path.append(str(web_searchs_path))

from web_searchs import web_search

# 创建蓝图
stock_analysis_bp = Blueprint('stock_analysis', __name__)

# 功能类型映射字典
FUNCTION_TYPE_MAP = {
    "comprehensive": "综合分析",
    "fundamental": "基本面分析",
    "companies": "涉及公司查询",
    "trend": "趋势预测",
    "comparison": "对比分析"
}

# 功能关键词前缀映射
FUNCTION_PREFIX_MAP = {
    "comprehensive": "公司介绍，主营业务，营收占比，主要产品以及客户",
    "fundamental": "分析以下股票的基本面情况：",
    "companies": "直接相关的上市公司有哪些，需要直接相关的，并说明相关性",
    "trend": "预测以下股票或市场的发展趋势：",
    "comparison": "对比分析以下股票或市场："
}

@stock_analysis_bp.route('/api/stock-analysis/search', methods=['POST'])
def stock_analysis_search():
    """
    股票分析搜索接口
    接收前端传来的搜索关键词和功能类型，拼接成完整的搜索词，
    使用playwright进行搜索，返回解析后的结果
    """
    try:
        # 获取请求数据
        data = request.get_json()
        query = data.get('query', '').strip()
        function_type = data.get('functionType', 'comprehensive')
        
        # 验证输入
        if not query:
            return jsonify({
                'success': False,
                'error': '查询内容不能为空'
            }), 400
            
        # 获取功能类型对应的中文描述
        function_name = FUNCTION_TYPE_MAP.get(function_type, '综合分析')
        
        # 拼接搜索关键词
        search_query = query + FUNCTION_PREFIX_MAP.get(function_type, '') 
        
        # 使用playwright进行搜索
        search_result = web_search(search_query)
        
        # 处理搜索结果
        if not search_result:
            return jsonify({
                'success': True,
                'data': {
                    'query': query,
                    'functionType': function_type,
                    'functionName': function_name,
                    'result': '未找到相关分析结果',
                    'rawResult': ''
                }
            })
        
        # 返回成功结果
        return jsonify({
            'success': True,
            'data': {
                'query': query,
                'functionType': function_type,
                'functionName': function_name,
                'result': search_result,
                'rawResult': search_result
            }
        })
        
    except Exception as e:
        # 错误处理
        return jsonify({
            'success': False,
            'error': f'搜索过程中发生错误: {str(e)}'
        }), 500

@stock_analysis_bp.route('/api/stock-analysis/function-types', methods=['GET'])
def get_function_types():
    """
    获取功能类型列表接口
    """
    try:
        return jsonify({
            'success': True,
            'data': FUNCTION_TYPE_MAP
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'获取功能类型时发生错误: {str(e)}'
        }), 500