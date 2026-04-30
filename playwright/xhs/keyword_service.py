#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小红书关键词生成脚本
遍历爬取结果JSON文件，为每个笔记生成关键词
"""

import json
import os
import sys
from pathlib import Path

# 添加路径以导入服务模块
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.append(project_root)
sys.path.append(os.path.join(project_root, "func"))
sys.path.append(os.path.join(project_root, "func", "src"))

# 添加web_server路径
sys.path.append(os.path.join(project_root, "func", "playwright", "web_server"))

from src.pic_understand_service import PicIdentifyService
from api.llm_client import LLMApiClient


class KeywordService:
    """
    关键词生成服务类
    """
    
    def __init__(self):
        self.llm_client = LLMApiClient()
        self.token_manager = self.llm_client.token_manager
    
    def generate_keywords_for_json(self, json_file_path, max_notes=None):
        """
        为JSON文件中的笔记生成关键词
        
        Args:
            json_file_path (str): JSON文件路径
            max_notes (int, optional): 最大处理笔记数量，None表示处理全部
        
        Returns:
            bool: 处理是否成功
        """
        # 显示当前token使用情况
        print("\n📊 当前Token使用情况:")
        today = self.token_manager.get_today_key()
        print(f"📅 今日日期: {today}")
        
        for model in self.llm_client.text_models:
            usage = self.token_manager.get_model_usage_today(model)
            limit = self.token_manager.daily_limit
            percentage = (usage / limit) * 100
            status = "🟢" if usage < limit * 0.8 else "🟡" if usage < limit else "🔴"
            print(f"  {status} {model}: {usage:,}/{limit:,} tokens ({percentage:.1f}%)")
        
        # 显示历史使用情况
        print("\n📈 历史Token使用情况:")
        all_usage_data = self.token_manager.get_all_usage_data()
        for date, models in sorted(all_usage_data.items(), reverse=True):
            if date != today:  # 不重复显示今日数据
                print(f"📅 {date}:")
                for model, usage in models.items():
                    if model in self.llm_client.text_models:
                        percentage = (usage / limit) * 100
                        status = "🟢" if usage < limit * 0.8 else "🟡" if usage < limit else "🔴"
                        print(f"  {status} {model}: {usage:,}/{limit:,} tokens ({percentage:.1f}%)")
        
        # 读取JSON文件
        try:
            with open(json_file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            print(f"读取JSON文件失败: {e}")
            return False
        
        notes = data.get('notes', [])
        total_notes = len(notes)
        
        # 根据max_notes限制处理数量
        if max_notes is not None and max_notes > 0:
            notes = notes[:max_notes]
            print(f"\n🔍 找到 {total_notes} 个笔记，将处理前 {len(notes)} 个")
        else:
            print(f"\n🔍 找到 {len(notes)} 个笔记，将全部处理")
        
        # 处理每个笔记
        for i, note in enumerate(notes):
            print(f"\n--- 处理第 {i+1} 个笔记: {note.get('title', '无标题')} ---")
            
            # 检查是否已经有keywords，如果有则跳过
            if note.get('keywords'):
                print("该笔记已有关键词，跳过处理")
                continue
            
            # 获取笔记内容
            title = note.get('title', '')
            desc = note.get('desc', '')
            pic_content = note.get('pic_content', '')
            
            # 构建完整的内容
            full_content = f"标题: {title}\n描述: {desc}"
            if pic_content:
                full_content += f"\n图片内容: {pic_content}"
            
            if not full_content.strip():
                print("该笔记没有可用内容")
                continue
            
            print(f"内容长度: {len(full_content)} 字符")
            
            try:
                # 调用关键词生成服务
                keywords_result = PicIdentifyService.gen_keyword(full_content)
                keywords = keywords_result.get('keywords') if keywords_result else None
                
                if keywords:
                    note['keywords'] = keywords
                    print(f"关键词生成成功: {keywords}")
                    
                    # 立即保存当前笔记的更新到JSON文件
                    try:
                        with open(json_file_path, 'w', encoding='utf-8') as f:
                            json.dump(data, f, ensure_ascii=False, indent=2)
                        print(f"  ✅ 笔记 {i+1} 处理完成，JSON文件已更新")
                    except Exception as save_e:
                        print(f"  ❌ 保存JSON文件失败: {save_e}")
                else:
                    print("关键词生成失败或返回空内容")
                    
            except Exception as e:
                print(f"关键词生成失败: {e}")
                continue
        
        # 最终保存确认
        try:
            with open(json_file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"\n✅ 所有笔记处理完成，最终JSON文件已保存: {json_file_path}")
        except Exception as e:
            print(f"\n❌ 最终保存JSON文件失败: {e}")
            return False
        
        # 显示最终token使用情况
        print("\n📊 处理完成后Token使用情况:")
        today = self.token_manager.get_today_key()
        print(f"📅 今日日期: {today}")
        
        for model in self.llm_client.text_models:
            usage = self.token_manager.get_model_usage_today(model)
            limit = self.token_manager.daily_limit
            percentage = (usage / limit) * 100
            status = "🟢" if usage < limit * 0.8 else "🟡" if usage < limit else "🔴"
            print(f"  {status} {model}: {usage:,}/{limit:,} tokens ({percentage:.1f}%)")
        
        # 如果今日使用量为0，显示最近的使用记录
        if all(self.token_manager.get_model_usage_today(model) == 0 for model in self.llm_client.text_models):
            print("\n💡 今日暂无使用记录，显示最近的使用情况:")
            all_usage_data = self.token_manager.get_all_usage_data()
            recent_dates = sorted(all_usage_data.keys(), reverse=True)[:3]
            for date in recent_dates:
                models = all_usage_data[date]
                print(f"📅 {date}:")
                for model, usage in models.items():
                    if model in self.llm_client.text_models:
                        percentage = (usage / limit) * 100
                        status = "🟢" if usage < limit * 0.8 else "🟡" if usage < limit else "🔴"
                        print(f"  {status} {model}: {usage:,}/{limit:,} tokens ({percentage:.1f}%)")
        
        # 清理旧数据
        self.token_manager.cleanup_old_data()
        return True