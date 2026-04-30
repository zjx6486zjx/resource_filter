#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小红书笔记处理服务
提供原子化的笔记处理方法，供页面调用
"""

import json
import os
import sys
from pathlib import Path

# 添加路径以导入服务模块
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.append(project_root)
sys.path.append(os.path.join(project_root, "func"))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "web_server")))

from .web_server.src.pic_understand_service import PicIdentifyService
from ..api.llm_client import LLMApiClient


class XHSNoteService:
    """小红书笔记处理服务类"""
    
    def __init__(self):
        self.results_dir = Path("xhs") / "xhs"/"results"
        # 初始化LLM客户端
        self.llm_client = LLMApiClient()
        self.token_manager = self.llm_client.token_manager
    
    def process_single_note_images(self, json_file_path, note_index):
        """
        处理单个笔记的图片内容
        
        Args:
            json_file_path (str): JSON文件路径
            note_index (int): 笔记在JSON中的索引
            
        Returns:
            dict: 处理结果，包含success状态和相关信息
        """
        try:
            # 检查是否是template.json文件
            if os.path.basename(json_file_path) == 'template.json':
                return {
                    'success': False,
                    'error': 'template.json文件不是有效的笔记数据文件'
                }
            
            # 读取JSON文件
            with open(json_file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            notes = data.get('notes', [])
            if note_index >= len(notes):
                return {
                    'success': False,
                    'error': f'笔记索引 {note_index} 超出范围，总共有 {len(notes)} 个笔记'
                }
            
            note = notes[note_index]
            
            # 检查是否已经有pic_content
            if note.get('pic_content'):
                print("该笔记已有图片内容分析结果，跳过图片处理")
            else:
                # 处理图片
                pic_result = self._process_note_images(note)
                if not pic_result['success']:
                    return pic_result
            
            # 生成新笔记内容
            generate_result = self._generate_new_note_content(note)
            if not generate_result['success']:
                return generate_result
            
            # 保存更新后的JSON文件
            with open(json_file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            return {
                'success': True,
                'message': '笔记处理完成',
                'new_note': note.get('new_note', '')
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': f'处理笔记时出错: {str(e)}'
            }
    
    def _process_note_images(self, note):
        """
        处理笔记中的图片
        
        Args:
            note (dict): 笔记数据
            
        Returns:
            dict: 处理结果
        """
        try:
            local_images = note.get('local_images', [])
            if not local_images:
                return {
                    'success': False,
                    'error': '该笔记没有本地图片'
                }
            
            # 初始化图片识别结果缓存
            if 'pic_results' not in note:
                note['pic_results'] = {}
            
            # 收集所有图片的识别结果
            pic_contents = []
            
            for image_path in local_images:
                # 构建完整的图片路径
                full_image_path = image_path
                
                # 处理Linux风格的绝对路径
                if full_image_path.startswith('/mnt/d/'):
                    # 将 /mnt/d/ 转换为 d:\
                    full_image_path = full_image_path.replace('/mnt/d/', 'd:\\')
                    full_image_path = full_image_path.replace('/', '\\')
                elif not os.path.isabs(full_image_path):
                    # 相对路径处理：相对于当前文件所在目录构建绝对路径
                    base_dir = os.path.dirname(__file__)
                    full_image_path = os.path.abspath(os.path.join(base_dir, image_path))
                
                # 标准化路径
                full_image_path = os.path.normpath(full_image_path)
                
                # 检查图片文件是否存在
                if not os.path.exists(full_image_path):
                    print(f"图片文件不存在: {full_image_path}")
                    continue
                
                # 检查是否已经解析过该图片
                if image_path in note['pic_results']:
                    cached_content = note['pic_results'][image_path]
                    if cached_content:
                        pic_contents.append(cached_content)
                    continue
                
                try:
                    # 调用图片识别服务
                    pic_content = PicIdentifyService.identify_xhs_pic_content(full_image_path)
                    
                    # 将结果存储到缓存中
                    note['pic_results'][image_path] = pic_content
                    
                    if pic_content:
                        pic_contents.append(pic_content)
                        
                except Exception as e:
                    print(f"图片识别失败: {e}")
                    note['pic_results'][image_path] = None
                    continue
            
            # 如果有识别结果，进行合并处理
            if pic_contents:
                # 将所有图片内容用换行符连接
                combined_pic_content = "\n".join(pic_contents)
                
                # 调用合并服务
                merged_content = PicIdentifyService.merge_note_pic_txt_content(combined_pic_content)
                
                # 将合并结果添加到笔记中
                note['pic_content'] = merged_content
                
                return {
                    'success': True,
                    'message': f'成功处理 {len(pic_contents)} 张图片',
                    'pic_content': merged_content
                }
            else:
                return {
                    'success': False,
                    'error': '没有有效的图片识别结果'
                }
                
        except Exception as e:
            return {
                'success': False,
                'error': f'处理图片时出错: {str(e)}'
            }
    
    def _generate_new_note_content(self, note):
        """
        生成新的笔记内容
        
        Args:
            note (dict): 笔记数据
            
        Returns:
            dict: 生成结果
        """
        try:
            note_title = note.get('title', '')
            note_desc = note.get('desc', '')
            note_content = note.get('pic_content', '')
            
            # 调用regen_note方法生成新的笔记内容
            new_note_content = PicIdentifyService.regen_note(note_title, note_desc, note_content)
            
            if new_note_content:
                note['new_note'] = new_note_content
                return {
                    'success': True,
                    'message': '新笔记生成完成',
                    'new_note': new_note_content
                }
            else:
                return {
                    'success': False,
                    'error': '新笔记生成失败或返回空内容'
                }
                
        except Exception as e:
            return {
                'success': False,
                'error': f'生成新笔记时出错: {str(e)}'
            }
    
    def get_token_usage(self):
        """
        获取当前token使用情况
        
        Returns:
            dict: token使用情况
        """
        usage_info = {}
        for model in self.llm_client.vision_models:
            usage = self.token_manager.get_model_usage_today(model)
            limit = self.token_manager.daily_limit
            percentage = (usage / limit) * 100
            
            usage_info[model] = {
                'usage': usage,
                'limit': limit,
                'percentage': percentage,
                'status': '🟢' if usage < limit * 0.8 else '🟡' if usage < limit else '🔴'
            }
        
        return usage_info


# 创建全局服务实例
xhs_note_service = XHSNoteService()