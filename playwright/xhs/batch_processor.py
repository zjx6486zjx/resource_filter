#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小红书批量处理脚本
整合爬取、图片处理、关键词生成和向量化功能
对xhs/results目录下的所有链接重新执行完整的处理流程
"""

import json
import os
import sys
import glob
import time
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional

# 添加路径以导入服务模块
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.append(project_root)
sys.path.append(os.path.join(project_root, "func"))

# 导入服务模块
from .processor import XHSProcessor, quick_process_all


class XHSBatchProcessor:
    """
    小红书批量处理器
    基于XHSProcessor的用户交互界面
    """
    
    def __init__(self):
        self.processor = XHSProcessor()
        print(f"🚀 小红书批量处理器初始化完成")
        print(f"📁 结果目录: {self.processor.results_dir}")
    
    def get_all_result_files(self) -> List[Path]:
        """
        获取results目录下的所有JSON文件
        
        Returns:
            List[Path]: JSON文件路径列表
        """
        json_files = self.processor.get_all_result_files()
        print(f"📋 找到 {len(json_files)} 个结果文件")
        return json_files
    

    
    def process_all_urls(self, 
                        skip_crawl: bool = False,
                        skip_images: bool = False,
                        skip_keywords: bool = False,
                        skip_embeddings: bool = False,
                        max_notes: Optional[int] = None,
                        target_files: Optional[List[str]] = None) -> None:
        """
        处理所有URL的完整流程
        
        Args:
            skip_crawl: 是否跳过爬取
            skip_images: 是否跳过图片处理
            skip_keywords: 是否跳过关键词生成
            skip_embeddings: 是否跳过向量生成
            max_notes: 最大处理笔记数量
            target_files: 指定要处理的文件列表（文件名），None表示处理全部
        """
        # 直接调用processor的方法
        stats = self.processor.process_all_files(
            enable_crawl=not skip_crawl,
            enable_images=not skip_images,
            enable_keywords=not skip_keywords,
            enable_embeddings=not skip_embeddings,
            max_notes=max_notes,
            target_files=target_files
        )
        
        print(f"\n🎉 处理完成! 统计结果: {stats}")
    



def main():
    """
    主函数
    """
    processor = XHSBatchProcessor()
    
    print("\n🎯 小红书批量处理器")
    print("请选择处理模式:")
    print("1. 完整流程 (图片处理 + 关键词 + 向量)")
    print("2. 仅关键词 + 向量 (跳过图片处理)")
    print("3. 仅向量生成 (跳过前面所有步骤)")
    print("4. 自定义选择步骤")
    print("5. 指定文件处理")
    print("\n⚠️ 注意: 如需爬取功能，请单独使用XHSProcessor")
    
    while True:
        try:
            choice = input("\n请输入选择 (1-5): ").strip()
            
            if choice == "1":
                # 完整流程
                max_notes = None
                user_input = input("请输入每个文件最大处理笔记数量 (直接回车处理全部): ").strip()
                if user_input:
                    max_notes = int(user_input)
                
                processor.process_all_urls(
                    skip_crawl=True,
                    max_notes=max_notes
                )
                break
                
            elif choice == "2":
                # 跳过图片处理
                processor.process_all_urls(
                    skip_crawl=True,
                    skip_images=True
                )
                break
                
            elif choice == "3":
                # 仅向量生成
                processor.process_all_urls(
                    skip_crawl=True,
                    skip_images=True,
                    skip_keywords=True
                )
                break
                
            elif choice == "4":
                # 自定义选择
                skip_images = input("是否跳过图片处理? (y/N): ").strip().lower() == 'y'
                skip_keywords = input("是否跳过关键词生成? (y/N): ").strip().lower() == 'y'
                skip_embeddings = input("是否跳过向量生成? (y/N): ").strip().lower() == 'y'
                
                max_notes = None
                if not skip_images:
                    user_input = input("请输入每个文件最大处理笔记数量 (直接回车处理全部): ").strip()
                    if user_input:
                        max_notes = int(user_input)
                
                processor.process_all_urls(
                    skip_crawl=True,
                    skip_images=skip_images,
                    skip_keywords=skip_keywords,
                    skip_embeddings=skip_embeddings,
                    max_notes=max_notes
                )
                break
                
            elif choice == "5":
                # 指定文件处理
                json_files = processor.get_all_result_files()
                if not json_files:
                    print("❌ 未找到结果文件")
                    continue
                
                print("\n可用的文件:")
                for i, f in enumerate(json_files, 1):
                    print(f"  {i}. {f.name}")
                
                file_input = input("\n请输入要处理的文件编号 (用逗号分隔多个编号): ").strip()
                try:
                    indices = [int(x.strip()) - 1 for x in file_input.split(',')]
                    target_files = [json_files[i].name for i in indices if 0 <= i < len(json_files)]
                    
                    if not target_files:
                        print("❌ 无效的文件编号")
                        continue
                    
                    print(f"将处理文件: {target_files}")
                    
                    # 选择处理步骤
                    skip_images = input("是否跳过图片处理? (y/N): ").strip().lower() == 'y'
                    skip_keywords = input("是否跳过关键词生成? (y/N): ").strip().lower() == 'y'
                    skip_embeddings = input("是否跳过向量生成? (y/N): ").strip().lower() == 'y'
                    
                    max_notes = None
                    if not skip_images:
                        user_input = input("请输入每个文件最大处理笔记数量 (直接回车处理全部): ").strip()
                        if user_input:
                            max_notes = int(user_input)
                    
                    processor.process_all_urls(
                        skip_crawl=True,
                        skip_images=skip_images,
                        skip_keywords=skip_keywords,
                        skip_embeddings=skip_embeddings,
                        max_notes=max_notes,
                        target_files=target_files
                    )
                    break
                    
                except ValueError:
                    print("❌ 请输入有效的数字")
                    continue
                
            else:
                print("❌ 请输入有效的选择 (1-5)")
                continue
                
        except KeyboardInterrupt:
            print("\n\n👋 用户取消操作")
            return
        except ValueError as e:
            print(f"❌ 输入错误: {e}")
            continue


if __name__ == "__main__":
    main()