#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
向量搜索脚本
对results目录下所有JSON文件的title、keywords分别调用siliconflow_embedding方法
生成向量并存储，实现相似度计算和rerank功能
"""

import json
import os
import sys
import glob
import numpy as np
from typing import List, Dict, Tuple, Any

# 添加路径以导入服务模块
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.append(project_root)
sys.path.append(os.path.join(project_root, "func"))
sys.path.append(os.path.join(project_root, "func", "src"))

from api.llm_client import LLMApiClient

# 初始化LLM客户端
llm_client = LLMApiClient()


class EmbeddingSearchService:
    """
    向量搜索服务类
    """
    
    def __init__(self):
        self.llm_client = LLMApiClient()
    
    def generate_embeddings_for_json(self, json_file_path: str) -> bool:
        """
        为指定JSON文件中的笔记生成title和keywords的向量
        
        Args:
            json_file_path (str): JSON文件路径
            
        Returns:
            bool: 是否成功处理
        """
        print(f"\n🔍 处理文件: {json_file_path}")
        
        # 读取JSON文件
        try:
            with open(json_file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            print(f"❌ 读取JSON文件失败: {e}")
            return False
        
        notes = data.get('notes', [])
        total_notes = len(notes)
        processed_count = 0
        skipped_count = 0
        
        print(f"📋 找到 {total_notes} 个笔记")
        
        # 处理每个笔记
        for i, note in enumerate(notes):
            note_title = note.get('title', '无标题')
            print(f"\n--- 处理第 {i+1}/{total_notes} 个笔记: {note_title} ---")
            
            # 检查是否已经有向量，如果有则跳过
            if note.get('title_embedding') and note.get('keywords_embedding'):
                print("该笔记已有向量，跳过处理")
                skipped_count += 1
                continue
            
            # 处理title向量
            title = note.get('title', '')
            if title and not note.get('title_embedding'):
                try:
                    print(f"生成title向量: {title}")
                    title_embedding = self.llm_client.siliconflow_embedding(title)
                    if title_embedding:
                        note['title_embedding'] = title_embedding
                        print(f"✅ title向量生成成功，维度: {len(title_embedding)}")
                    else:
                        print("❌ title向量生成失败")
                        note['title_embedding'] = []
                except Exception as e:
                    print(f"❌ title向量生成异常: {e}")
                    note['title_embedding'] = []
            
            # 处理keywords向量
            keywords = note.get('keywords', '')
            if keywords and not note.get('keywords_embedding'):
                try:
                    # 获取关键词字符串
                    keywords_text = str(keywords).strip()
                    
                    print(f"生成keywords向量: {keywords_text[:100]}{'...' if len(keywords_text) > 100 else ''}")
                    keywords_embedding = self.llm_client.siliconflow_embedding(keywords_text)
                    if keywords_embedding:
                        note['keywords_embedding'] = keywords_embedding
                        print(f"✅ keywords向量生成成功，维度: {len(keywords_embedding)}")
                        processed_count += 1
                    else:
                        print("❌ keywords向量生成失败")
                        note['keywords_embedding'] = []
                except Exception as e:
                    print(f"❌ keywords向量生成异常: {e}")
                    note['keywords_embedding'] = []
            
            # 如果没有keywords，跳过
            if not keywords:
                print("该笔记没有keywords，跳过keywords向量生成")
                note['keywords_embedding'] = []
                if title and note.get('title_embedding'):
                    processed_count += 1
        
        # 保存更新后的JSON文件
        try:
            with open(json_file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"\n✅ JSON文件已更新: {json_file_path}")
            print(f"📊 处理统计: 成功处理 {processed_count} 个，跳过 {skipped_count} 个")
            return True
        except Exception as e:
            print(f"\n❌ 保存JSON文件失败: {e}")
            return False
    
    def cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """
        计算两个向量的余弦相似度
        
        Args:
            vec1: 向量1
            vec2: 向量2
            
        Returns:
            float: 余弦相似度值 (-1 到 1)
        """
        try:
            vec1 = np.array(vec1)
            vec2 = np.array(vec2)
            
            # 计算余弦相似度
            dot_product = np.dot(vec1, vec2)
            norm1 = np.linalg.norm(vec1)
            norm2 = np.linalg.norm(vec2)
            
            if norm1 == 0 or norm2 == 0:
                return 0.0
            
            similarity = dot_product / (norm1 * norm2)
            return float(similarity)
        except Exception as e:
            print(f"计算余弦相似度失败: {e}")
            return 0.0
    
    def search_similar_notes(self, query: str, json_files: List[str], top_k: int = 10) -> Dict[str, List[Dict]]:
        """
        搜索相似的笔记
        
        Args:
            query: 查询文本
            json_files: JSON文件路径列表
            top_k: 返回前k个最相似的结果
            
        Returns:
            Dict: 包含title和keywords搜索结果的字典
        """
        print(f"\n🔍 搜索查询: {query}")
        
        # 生成查询向量
        try:
            query_embedding = self.llm_client.siliconflow_embedding(query)
            if not query_embedding:
                print("❌ 查询向量生成失败")
                return {'title_results': [], 'keywords_results': []}
        except Exception as e:
            print(f"❌ 查询向量生成异常: {e}")
            return {'title_results': [], 'keywords_results': []}
        
        print(f"✅ 查询向量生成成功，维度: {len(query_embedding)}")
        
        title_similarities = []
        keywords_similarities = []
        
        # 遍历所有JSON文件
        for json_file in json_files:
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                notes = data.get('notes', [])
                
                for note in notes:
                    note_id = f"{os.path.basename(json_file)}_{notes.index(note)}"
                    
                    # 计算title相似度
                    title_embedding = note.get('title_embedding', [])
                    if title_embedding:
                        title_sim = self.cosine_similarity(query_embedding, title_embedding)
                        title_similarities.append({
                            'note_id': note_id,
                            'title': note.get('title', ''),
                            'similarity': title_sim,
                            'content': note.get('new_note', note.get('desc', '')),
                            'file_path': json_file
                        })
                    
                    # 计算keywords相似度
                    keywords_embedding = note.get('keywords_embedding', [])
                    if keywords_embedding:
                        keywords_sim = self.cosine_similarity(query_embedding, keywords_embedding)
                        keywords_similarities.append({
                            'note_id': note_id,
                            'title': note.get('title', ''),
                            'keywords': note.get('keywords', []),
                            'similarity': keywords_sim,
                            'content': note.get('new_note', note.get('desc', '')),
                            'file_path': json_file
                        })
            
            except Exception as e:
                print(f"❌ 处理文件 {json_file} 时出错: {e}")
                continue
        
        # 按相似度排序
        title_similarities.sort(key=lambda x: x['similarity'], reverse=True)
        keywords_similarities.sort(key=lambda x: x['similarity'], reverse=True)
        
        # 取前top_k个结果
        title_results = title_similarities[:top_k]
        keywords_results = keywords_similarities[:top_k]
        
        print(f"\n📊 搜索结果统计:")
        print(f"Title相似度搜索: 找到 {len(title_similarities)} 个结果，返回前 {len(title_results)} 个")
        print(f"Keywords相似度搜索: 找到 {len(keywords_similarities)} 个结果，返回前 {len(keywords_results)} 个")
        
        return {
            'title_results': title_results,
            'keywords_results': keywords_results
        }
    
    def rerank_results(self, query: str, search_results: Dict[str, List[Dict]], top_k: int = 3) -> Dict[str, List[Dict]]:
        """
        使用siliconflow_rerank对搜索结果进行重排序
        
        Args:
            query: 查询文本
            search_results: 搜索结果
            top_k: 返回前k个重排序结果
            
        Returns:
            Dict: 重排序后的结果
        """
        print(f"\n🔄 开始重排序，目标返回前 {top_k} 个结果")
        
        reranked_results = {
            'title_reranked': [],
            'keywords_reranked': []
        }
        
        # 重排序title结果
        title_results = search_results.get('title_results', [])
        if title_results:
            try:
                # 准备重排序的文档
                title_docs = []
                for result in title_results:
                    doc_text = f"标题: {result['title']}\n内容: {result['content'][:200]}..."
                    title_docs.append(doc_text)
                
                print(f"对 {len(title_docs)} 个title结果进行重排序")
                rerank_response = self.llm_client.siliconflow_rerank(query, title_docs)
                
                if rerank_response and 'results' in rerank_response:
                    # 获取重排序结果
                    rerank_results = rerank_response['results']
                    # 按相关性分数排序并取前top_k个
                    sorted_results = sorted(rerank_results, key=lambda x: x.get('relevance_score', 0), reverse=True)[:top_k]
                    
                    for rerank_item in sorted_results:
                        doc_index = rerank_item.get('index', 0)
                        if doc_index < len(title_results):
                            result = title_results[doc_index].copy()
                            result['rerank_score'] = rerank_item.get('relevance_score', 0)
                            reranked_results['title_reranked'].append(result)
                    
                    print(f"✅ Title重排序完成，返回 {len(reranked_results['title_reranked'])} 个结果")
                else:
                    print("❌ Title重排序失败，使用原始排序")
                    reranked_results['title_reranked'] = title_results[:top_k]
                    
            except Exception as e:
                print(f"❌ Title重排序异常: {e}，使用原始排序")
                reranked_results['title_reranked'] = title_results[:top_k]
        
        # 重排序keywords结果
        keywords_results = search_results.get('keywords_results', [])
        if keywords_results:
            try:
                # 准备重排序的文档
                keywords_docs = []
                for result in keywords_results:
                    # 获取关键词字符串
                    keywords = result['keywords']
                    keywords_text = str(keywords).strip()
                    
                    doc_text = f"标题: {result['title']}\n关键词: {keywords_text}\n内容: {result['content'][:200]}..."
                    keywords_docs.append(doc_text)
                
                print(f"对 {len(keywords_docs)} 个keywords结果进行重排序")
                rerank_response = self.llm_client.siliconflow_rerank(query, keywords_docs)
                
                if rerank_response and 'results' in rerank_response:
                    # 获取重排序结果
                    rerank_results = rerank_response['results']
                    # 按相关性分数排序并取前top_k个
                    sorted_results = sorted(rerank_results, key=lambda x: x.get('relevance_score', 0), reverse=True)[:top_k]
                    
                    for rerank_item in sorted_results:
                        doc_index = rerank_item.get('index', 0)
                        if doc_index < len(keywords_results):
                            result = keywords_results[doc_index].copy()
                            result['rerank_score'] = rerank_item.get('relevance_score', 0)
                            reranked_results['keywords_reranked'].append(result)
                    
                    print(f"✅ Keywords重排序完成，返回 {len(reranked_results['keywords_reranked'])} 个结果")
                else:
                    print("❌ Keywords重排序失败，使用原始排序")
                    reranked_results['keywords_reranked'] = keywords_results[:top_k]
                    
            except Exception as e:
                print(f"❌ Keywords重排序异常: {e}，使用原始排序")
                reranked_results['keywords_reranked'] = keywords_results[:top_k]
        
        return reranked_results
    
    def search_and_rerank(self, query: str, json_files: List[str] = None, top_k_search: int = 10, top_k_rerank: int = 3) -> Dict[str, List[Dict]]:
        """
        完整的搜索和重排序流程
        
        Args:
            query: 查询文本
            json_files: JSON文件路径列表，如果为None则自动查找results目录下的所有JSON文件
            top_k_search: 初始搜索返回的结果数量
            top_k_rerank: 重排序后返回的结果数量
            
        Returns:
            Dict: 最终的搜索和重排序结果
        """
        # 如果没有指定文件，自动查找results目录下的所有JSON文件
        if json_files is None:
            results_dir = os.path.join(os.path.dirname(__file__), "xhs", "results")
            if os.path.exists(results_dir):
                json_pattern = os.path.join(results_dir, "*.json")
                json_files = glob.glob(json_pattern)
            else:
                print(f"❌ results目录不存在: {results_dir}")
                return {'title_reranked': [], 'keywords_reranked': []}
        
        if not json_files:
            print("❌ 未找到JSON文件")
            return {'title_reranked': [], 'keywords_reranked': []}
        
        print(f"🔍 将在 {len(json_files)} 个文件中搜索")
        
        # 执行相似度搜索
        search_results = self.search_similar_notes(query, json_files, top_k_search)
        
        # 执行重排序
        final_results = self.rerank_results(query, search_results, top_k_rerank)
        
        return final_results


# 移除全局函数和main执行代码，只保留EmbeddingSearchService类