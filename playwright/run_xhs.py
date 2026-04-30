#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
XHS处理器启动脚本
快速启动XHS集成处理器
"""

import sys
import os
from pathlib import Path

# 添加路径
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.append(project_root)
sys.path.append(os.path.join(project_root, "func"))
sys.path.append(os.path.join(project_root, "func", "playwright", "web_server"))
sys.path.append(os.path.join(project_root, "func", "playwright", "web_server", "src"))

# 导入并运行集成处理器
if __name__ == "__main__":
    try:
        from xhs_integrated_processor import main
        main()
    except ImportError as e:
        print(f"❌ 导入失败: {e}")
        print("请确保所有依赖模块已正确安装")
    except Exception as e:
        print(f"❌ 运行异常: {e}")