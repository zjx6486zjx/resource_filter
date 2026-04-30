#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小红书图片内容处理脚本
遍历爬取结果JSON文件，识别图片内容并合并处理
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

from src.pic_understand_service import PicIdentifyService
from api.llm_client import LLMApiClient


class ImageService:
    """
    图片内容处理服务类
    """
    
    def __init__(self):
        self.llm_client = LLMApiClient()
        self.token_manager = self.llm_client.token_manager
    
    def process_json_file(self, json_file_path, max_notes=None):
        """
        处理小红书JSON文件，识别图片内容并合并
        
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
        
        for model in self.llm_client.vision_models:
            usage = self.token_manager.get_model_usage_today(model)
            limit = self.token_manager.daily_limit
            percentage = (usage / limit) * 100
            status = "🟢" if usage < limit * 0.8 else "🟡" if usage < limit else "🔴"
            print(f"  {status} {model}: {usage:,}/{limit:,} tokens ({percentage:.1f}%)")
        
        # 显示历史使用情况
        print("\n📈 历史Token使用情况:")
        for date, models in sorted(self.token_manager.usage_data.items(), reverse=True):
            if date != today:  # 不重复显示今日数据
                print(f"📅 {date}:")
                for model, usage in models.items():
                    if model in self.llm_client.vision_models:
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
            
            # 检查是否已经有pic_content，如果有则跳过
            if note.get('pic_content'):
                print("该笔记已有图片内容分析结果，跳过处理")
                continue
            
            local_images = note.get('local_images', [])
            if not local_images:
                print("该笔记没有本地图片")
                continue
                
            print(f"发现 {len(local_images)} 张图片")
            
            # 初始化图片识别结果缓存（如果不存在）
            if 'pic_results' not in note:
                note['pic_results'] = {}
            
            # 收集所有图片的识别结果
            pic_contents = []
            
            for j, image_path in enumerate(local_images):
                print(f"  处理图片 {j+1}/{len(local_images)}: {image_path}")
                
                # 构建完整的图片路径，支持多种可能的存储位置
                full_image_path = None
                
                # 处理Linux风格的绝对路径
                if image_path.startswith('/mnt/d/'):
                    # 将 /mnt/d/ 转换为 d:\
                    converted_path = image_path.replace('/mnt/d/', 'd:\\')
                    converted_path = converted_path.replace('/', '\\')
                    full_image_path = os.path.normpath(converted_path)
                elif os.path.isabs(image_path):
                    # 已经是绝对路径
                    full_image_path = os.path.normpath(image_path)
                else:
                    # 相对路径处理：尝试多个可能的基础目录
                    possible_base_dirs = [
                        os.path.dirname(__file__),  # 当前文件所在目录 (xhs/)
                        os.path.dirname(os.path.dirname(__file__)),  # 上级目录 (playwright/)
                        os.path.dirname(os.path.dirname(os.path.dirname(__file__)))  # 再上级目录 (func/)
                    ]
                    
                    for base_dir in possible_base_dirs:
                        candidate_path = os.path.abspath(os.path.join(base_dir, image_path))
                        candidate_path = os.path.normpath(candidate_path)
                        if os.path.exists(candidate_path):
                            full_image_path = candidate_path
                            break
                    
                    # 如果都没找到，使用第一个作为默认路径
                    if full_image_path is None:
                        full_image_path = os.path.abspath(os.path.join(possible_base_dirs[0], image_path))
                        full_image_path = os.path.normpath(full_image_path)
                
                # 检查图片文件是否存在
                if not os.path.exists(full_image_path):
                    print(f"    图片文件不存在: {full_image_path}")
                    continue
                
                # 检查是否已经解析过该图片
                if image_path in note['pic_results']:
                    cached_content = note['pic_results'][image_path]
                    if cached_content:
                        pic_contents.append(cached_content)
                        print(f"    使用缓存结果: {cached_content[:50]}...")
                    else:
                        print(f"    缓存显示该图片识别结果为空")
                    continue
                    
                try:
                    # 调用图片识别服务
                    pic_content = PicIdentifyService.identify_xhs_pic_content(full_image_path)
                    
                    # 将结果存储到缓存中（无论是否为空）
                    note['pic_results'][image_path] = pic_content
                    
                    if pic_content:
                        pic_contents.append(pic_content)
                        print(f"    识别成功: {pic_content[:50]}...")
                    else:
                        print(f"    识别结果为空")
                except Exception as e:
                    print(f"    图片识别失败: {e}")
                    # 将失败结果也存储到缓存中，避免重复尝试
                    note['pic_results'][image_path] = None
                    continue
            
            # 如果有识别结果，进行合并处理
            if pic_contents:
                print(f"  开始合并 {len(pic_contents)} 个图片识别结果")
                
                # 将所有图片内容用换行符连接
                combined_pic_content = "\n".join(pic_contents)
                
                try:
                    # 调用合并服务
                    merged_content = PicIdentifyService.merge_note_pic_txt_content(combined_pic_content)
                    
                    # 将合并结果添加到笔记中
                    note['pic_content'] = merged_content
                    
                    print(f"  合并完成: {merged_content[:100]}...")
                    
                    # 调用regen_note方法生成新的笔记内容
                    try:
                        print(f"  开始生成新笔记内容...")
                        note_title = note.get('title', '')
                        note_desc = note.get('desc', '')
                        note_content = merged_content
                        
                        new_note_content = PicIdentifyService.regen_note(note_title, note_desc, note_content)
                        
                        if new_note_content:
                            note['new_note'] = new_note_content
                            print(f"  新笔记生成完成: {new_note_content[:100]}...")
                        else:
                            print(f"  新笔记生成失败或返回空内容")
                            
                    except Exception as regen_e:
                        print(f"  新笔记生成失败: {regen_e}")
                    
                    # 立即保存当前笔记的更新到JSON文件
                    try:
                        with open(json_file_path, 'w', encoding='utf-8') as f:
                            json.dump(data, f, ensure_ascii=False, indent=2)
                        print(f"  ✅ 笔记 {i+1} 处理完成，JSON文件已更新")
                    except Exception as save_e:
                        print(f"  ❌ 保存JSON文件失败: {save_e}")
                    
                except Exception as e:
                    print(f"  合并处理失败: {e}")
            else:
                print("  没有有效的图片识别结果")
        
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
        
        for model in self.llm_client.vision_models:
            usage = self.token_manager.get_model_usage_today(model)
            limit = self.token_manager.daily_limit
            percentage = (usage / limit) * 100
            status = "🟢" if usage < limit * 0.8 else "🟡" if usage < limit else "🔴"
            print(f"  {status} {model}: {usage:,}/{limit:,} tokens ({percentage:.1f}%)")
        
        # 如果今日使用量为0，显示最近的使用记录
        if all(self.token_manager.get_model_usage_today(model) == 0 for model in self.llm_client.vision_models):
            print("\n💡 今日暂无使用记录，显示最近的使用情况:")
            recent_dates = sorted(self.token_manager.usage_data.keys(), reverse=True)[:3]
            for date in recent_dates:
                models = self.token_manager.usage_data[date]
                print(f"📅 {date}:")
                for model, usage in models.items():
                    if model in self.llm_client.vision_models:
                        percentage = (usage / limit) * 100
                        status = "🟢" if usage < limit * 0.8 else "🟡" if usage < limit else "🔴"
                        print(f"  {status} {model}: {usage:,}/{limit:,} tokens ({percentage:.1f}%)")
        
        # 清理旧数据
        self.token_manager.cleanup_old_data()
        return True
    
    def process_images_in_json(self, json_file_path, max_notes=None):
        """
        处理JSON文件中的图片（别名方法，兼容性）
        
        Args:
            json_file_path (str): JSON文件路径
            max_notes (int, optional): 最大处理笔记数量，None表示处理全部
        
        Returns:
            bool: 处理是否成功
        """
        return self.process_json_file(json_file_path, max_notes)


# 移除全局函数和main执行代码，只保留ImageService类