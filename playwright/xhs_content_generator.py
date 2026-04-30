import json
import os
from pathlib import Path
from datetime import datetime
import markdown
import re

class XHSContentGenerator:
    def __init__(self):
        # 使用相对路径以适配不同环境
        base_dir = Path(__file__).parent
        self.results_dir = base_dir / "xhs" /"xhs" / "results"
        self.template_path = base_dir / "templates" / "xhs_content.html"
        self.output_path = base_dir / "templates" / "xhs_content_dynamic.html"
    
    def load_all_notes(self):
        """加载所有JSON文件中的笔记数据"""
        all_notes = []
        
        # 遍历results目录下的所有JSON文件
        for json_file in self.results_dir.glob('*.json'):
            # 跳过template.json文件
            if json_file.name == 'template.json':
                continue
                
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                if 'notes' in data:
                    for i, note in enumerate(data['notes']):
                        # 添加文件来源信息
                        note['source_file'] = json_file.name
                        note['note_index'] = i
                        
                        # 只添加未发布的笔记，且有new_note字段或只有desc字段的笔记
                        if not note.get('published', False):
                            if note.get('new_note') or (note.get('desc') and not note.get('new_note')):
                                all_notes.append(note)
                            
            except Exception as e:
                print(f"读取文件 {json_file} 时出错: {e}")
                
        return all_notes
    
    def mark_as_published(self, source_file, note_index):
        """标记指定笔记为已发布"""
        file_path = self.results_dir / source_file
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if 'notes' in data and note_index < len(data['notes']):
                data['notes'][note_index]['published'] = True
                data['notes'][note_index]['published_time'] = datetime.now().isoformat()
                
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                    
                return True
        except Exception as e:
            print(f"标记发布状态时出错: {e}")
            
        return False
    
    def process_markdown_content(self, content):
        """处理Markdown内容"""
        if not content:
            return "无内容"
        
        # 使用markdown库转换内容
        md = markdown.Markdown(extensions=['nl2br', 'fenced_code'])
        html_content = md.convert(content)
        
        # 清理HTML标签中的特殊字符，防止XSS
        html_content = re.sub(r'<script.*?</script>', '', html_content, flags=re.DOTALL)
        
        return html_content
    
    def get_all_json_files(self):
        """获取所有JSON文件名称"""
        json_files = []
        for json_file in self.results_dir.glob("*.json"):
            if json_file.name != "template.json":
                json_files.append(json_file.name)
        return sorted(json_files)
    
    def load_notes_by_file(self, filename=None):
        """根据文件名加载笔记数据"""
        all_notes = []
        
        if filename:
            # 跳过template.json文件
            if filename == 'template.json':
                return all_notes
                
            # 加载指定文件的笔记
            json_file = self.results_dir / filename
            if json_file.exists():
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        
                    if 'notes' in data:
                        for i, note in enumerate(data['notes']):
                            note['source_file'] = json_file.name
                            note['note_index'] = i
                            if not note.get('published', False):
                                # 只加载有new_note字段或只有desc字段的笔记
                                if note.get('new_note') or (note.get('desc') and not note.get('new_note')):
                                    all_notes.append(note)
                                
                except Exception as e:
                    print(f"读取文件 {json_file} 时出错: {e}")
        else:
            # 加载所有文件的笔记
            all_notes = self.load_all_notes()
            
        return all_notes
    
    def get_paginated_notes(self, page=1, per_page=6, filename=None):
        """获取分页的笔记数据，支持按文件筛选"""
        all_notes = self.load_notes_by_file(filename)
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        
        paginated_notes = all_notes[start_idx:end_idx]
        has_more = end_idx < len(all_notes)
        
        return {
            'notes': paginated_notes,
            'has_more': has_more,
            'total': len(all_notes),
            'current_page': page,
            'per_page': per_page,
            'filename': filename
        }
    
    def generate_html_content(self, notes, start_index=0):
        """生成HTML内容"""
        cards_html = ""
        
        for i, note in enumerate(notes):
            title = note.get('title', '无标题')
            source_file = note.get('source_file', '')
            note_index = note.get('note_index', i)
            
            # 判断笔记类型和内容
            has_new_note = bool(note.get('new_note'))
            has_desc = bool(note.get('desc'))
            
            if has_new_note:
                # 有new_note字段，显示new_note内容和发布按钮
                desc = note.get('new_note')
                button_text = "发布到小红书"
                button_onclick = f"publishNote('{source_file}', {note_index})"
                button_class = "bg-gradient-to-r from-pink-500 to-red-500 text-white px-6 py-3 rounded-lg hover:from-pink-600 hover:to-red-600 transition-all duration-200 shadow-md hover:shadow-lg transform hover:-translate-y-0.5"
                button_icon = "fa fa-paper-plane mr-2"
            elif has_desc:
                # 只有desc字段，显示desc内容和生成笔记按钮
                desc = note.get('desc')
                button_text = "生成笔记"
                button_onclick = f"generateNote('{source_file}', {note_index})"
                button_class = "bg-gradient-to-r from-blue-500 to-purple-500 text-white px-6 py-3 rounded-lg hover:from-blue-600 hover:to-purple-600 transition-all duration-200 shadow-md hover:shadow-lg transform hover:-translate-y-0.5"
                button_icon = "fa fa-magic mr-2"
            else:
                # 既没有new_note也没有desc，跳过
                continue
            
            # 处理Markdown内容
            desc_html = self.process_markdown_content(desc)
            
            card_html = f"""
            <article class="bg-white rounded-2xl shadow-lg overflow-hidden card-hover animate-fade-in" style="animation-delay: {(start_index + i) * 0.1}s; min-height: 400px;">
                <div class="p-8 h-full flex flex-col">
                    <h2 class="text-2xl font-bold mb-4 text-gray-900 border-b border-gray-200 pb-3">{title}</h2>
                    <div class="flex-1 overflow-y-auto max-h-80 prose prose-sm max-w-none">
                        {desc_html}
                    </div>
                    <div class="mt-6 pt-4 border-t border-gray-100 flex justify-between items-center">
                        <span class="text-sm text-gray-500 bg-gray-100 px-3 py-1 rounded-full">来源: {source_file}</span>
                        <button onclick="{button_onclick}" 
                                class="{button_class}">
                            <i class="{button_icon}"></i>{button_text}
                        </button>
                    </div>
                </div>
            </article>
            """
            cards_html += card_html
        
        return cards_html
    
    def generate_page(self):
        """生成完整的HTML页面"""
        # 读取模板
        with open(self.template_path, 'r', encoding='utf-8') as f:
            template = f.read()
        
        # 替换卡片内容
        # 找到现有的卡片区域并替换
        start_marker = '<!-- 文本卡片网格 -->'
        end_marker = '</main>'
        
        start_idx = template.find(start_marker)
        end_idx = template.find(end_marker)
        
        if start_idx != -1 and end_idx != -1:
            # 添加筛选控件
            filter_html = '''
        <!-- 筛选控件 -->
        <div class="mb-6 bg-white rounded-lg shadow-sm p-4">
            <div class="flex items-center space-x-4">
                <label for="file-filter" class="text-sm font-medium text-gray-700">筛选文件:</label>
                <select id="file-filter" class="border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent">
                    <option value="">显示全部</option>
                </select>
                <div class="text-sm text-gray-500">
                    共 <span id="total-count">0</span> 条内容
                </div>
            </div>
        </div>
        '''
            
            # 保留网格容器的开始标签，但修改为2列布局
            grid_start = template.find('<div class="grid', start_idx)
            grid_end = template.find('>', grid_start) + 1
            
            # 替换网格类为2列布局
            grid_classes = '<div id="content-grid" class="grid grid-cols-1 lg:grid-cols-2 gap-8">'
            
            new_content = template[:start_idx] + filter_html + '<!-- 文本卡片网格 -->\n        ' + grid_classes + '\n        </div>'
            final_html = new_content + template[end_idx:]
        else:
            final_html = template
        
        # 添加CSS样式和JavaScript功能
        css_and_js_code = """
    <style>
        /* Prose样式 */
        .prose {
            color: #374151;
            max-width: none;
        }
        .prose p {
            margin-top: 0.75rem;
            margin-bottom: 0.75rem;
            line-height: 1.6;
        }
        .prose h1 {
            font-size: 1.5rem;
            font-weight: 700;
            margin-top: 1rem;
            margin-bottom: 0.5rem;
            color: #111827;
        }
        .prose h2 {
            font-size: 1.25rem;
            font-weight: 600;
            margin-top: 1rem;
            margin-bottom: 0.5rem;
            color: #111827;
        }
        .prose h3 {
            font-size: 1.125rem;
            font-weight: 600;
            margin-top: 0.75rem;
            margin-bottom: 0.5rem;
            color: #111827;
        }
        .prose ul, .prose ol {
            margin-top: 0.5rem;
            margin-bottom: 0.5rem;
            padding-left: 1.5rem;
        }
        .prose li {
            margin-top: 0.25rem;
            margin-bottom: 0.25rem;
        }
        .prose strong {
            color: #111827;
            font-weight: 600;
        }
        .prose em {
            font-style: italic;
            color: #6b7280;
        }
        .prose blockquote {
            border-left: 4px solid #fe2c55;
            padding-left: 1rem;
            font-style: italic;
            background-color: #fef7f7;
            padding: 0.75rem 1rem;
            border-radius: 0.375rem;
            margin: 1rem 0;
        }
        .prose code {
            background-color: #f3f4f6;
            padding: 0.125rem 0.25rem;
            border-radius: 0.25rem;
            font-size: 0.875rem;
            font-family: 'Courier New', monospace;
        }
        .prose pre {
            background-color: #1f2937;
            color: #f9fafb;
            padding: 1rem;
            border-radius: 0.5rem;
            overflow-x: auto;
            margin: 1rem 0;
        }
        .prose pre code {
            background-color: transparent;
            padding: 0;
            color: inherit;
        }
        .prose a {
            color: #fe2c55;
            text-decoration: underline;
        }
        .prose a:hover {
            color: #dc1f47;
        }
        /* 卡片悬停效果 */
        .card-hover:hover {
            transform: translateY(-2px);
            box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04);
        }
        .card-hover {
            transition: all 0.3s ease;
        }
    </style>
    <script>
        // 发布笔记功能
        async function publishNote(sourceFile, noteIndex) {
            try {
                const response = await fetch('/api/publish_note', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        source_file: sourceFile,
                        note_index: noteIndex
                    })
                });
                
                if (response.ok) {
                    alert('发布成功！');
                    // 保持筛选状态，重新加载内容而不是刷新整个页面
                    currentPage = 1;
                    hasMore = true;
                    
                    // 清空当前内容
                    const contentGrid = document.getElementById('content-grid');
                    contentGrid.innerHTML = '';
                    
                    // 隐藏"没有更多内容"提示
                    document.getElementById('no-more-content').classList.add('hidden');
                    
                    // 重新加载内容，保持当前筛选状态
                    loadMoreContent();
                } else {
                    alert('发布失败，请重试');
                }
            } catch (error) {
                console.error('发布时出错:', error);
                alert('发布时出错，请重试');
            }
        }
        
        // 生成笔记功能
        async function generateNote(sourceFile, noteIndex) {
            try {
                // 显示加载状态
                const button = event.target;
                const originalText = button.innerHTML;
                button.innerHTML = '<i class="fa fa-spinner fa-spin mr-2"></i>生成中...';
                button.disabled = true;
                
                const response = await fetch('/api/generate_note', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        source_file: sourceFile,
                        note_index: noteIndex
                    })
                });
                
                const result = await response.json();
                
                if (response.ok) {
                    alert('笔记生成成功！');
                    // 保持筛选状态，重新加载内容而不是刷新整个页面
                    currentPage = 1;
                    hasMore = true;
                    
                    // 清空当前内容
                    const contentGrid = document.getElementById('content-grid');
                    contentGrid.innerHTML = '';
                    
                    // 隐藏"没有更多内容"提示
                    document.getElementById('no-more-content').classList.add('hidden');
                    
                    // 重新加载内容，保持当前筛选状态
                    loadMoreContent();
                    
                    // 恢复按钮状态
                    button.innerHTML = originalText;
                    button.disabled = false;
                } else {
                    alert('生成失败：' + (result.error || '请重试'));
                    // 恢复按钮状态
                    button.innerHTML = originalText;
                    button.disabled = false;
                }
            } catch (error) {
                console.error('生成笔记时出错:', error);
                alert('生成笔记时出错，请重试');
                // 恢复按钮状态
                const button = event.target;
                button.innerHTML = '<i class="fa fa-magic mr-2"></i>生成笔记';
                button.disabled = false;
            }
        }
        
        // 监听滚动，改变导航栏样式
        window.addEventListener('scroll', function() {
            const header = document.querySelector('header');
            if (window.scrollY > 10) {
                header.classList.add('shadow');
                header.classList.remove('shadow-sm');
            } else {
                header.classList.remove('shadow');
                header.classList.add('shadow-sm');
            }
        });
    </script>
</body></html>"""
        
        # 替换原有的JavaScript
        final_html = final_html.replace('</body></html>', css_and_js_code)
        
        # 为网格添加ID以便JavaScript操作
        final_html = final_html.replace(
            'class="grid grid-cols-1 lg:grid-cols-2 gap-8"',
            'id="content-grid" class="grid grid-cols-1 lg:grid-cols-2 gap-8"'
        )
        
        # 添加无限滚动的HTML元素和JavaScript代码
        infinite_scroll_code = """
        
        <!-- 加载指示器 -->
        <div id="loading-indicator" class="text-center py-8 hidden">
            <div class="inline-flex items-center space-x-2">
                <div class="animate-spin rounded-full h-6 w-6 border-b-2 border-primary"></div>
                <span class="text-gray-600">加载更多内容...</span>
            </div>
        </div>
        
        <!-- 没有更多内容提示 -->
        <div id="no-more-content" class="text-center py-8 hidden">
            <p class="text-gray-500">已经到底了，没有更多内容了</p>
        </div>
    </main>
    
    <!-- JavaScript -->
    <script>
        let currentPage = 1;
        let isLoading = false;
        let hasMore = true;
        let currentFilter = '';
        
        // 加载JSON文件列表
        async function loadFileList() {
            try {
                const response = await fetch('/api/get_json_files');
                const data = await response.json();
                
                if (response.ok && data.files) {
                    const select = document.getElementById('file-filter');
                    // 清空现有选项（保留"显示全部"）
                    while (select.children.length > 1) {
                        select.removeChild(select.lastChild);
                    }
                    
                    // 添加文件选项
                    data.files.forEach(file => {
                        const option = document.createElement('option');
                        option.value = file;
                        option.textContent = file;
                        select.appendChild(option);
                    });
                }
            } catch (error) {
                console.error('加载文件列表时出错:', error);
            }
        }
        
        // 筛选变化处理
        function handleFilterChange() {
            const select = document.getElementById('file-filter');
            currentFilter = select.value;
            currentPage = 1;
            hasMore = true;
            
            // 清空当前内容
            const contentGrid = document.getElementById('content-grid');
            contentGrid.innerHTML = '';
            
            // 隐藏"没有更多内容"提示
            document.getElementById('no-more-content').classList.add('hidden');
            
            // 加载新内容
            loadMoreContent();
        }
        
        // 无限滚动功能
        function initInfiniteScroll() {
            window.addEventListener('scroll', function() {
                if (isLoading || !hasMore) return;
                
                const scrollTop = window.pageYOffset || document.documentElement.scrollTop;
                const windowHeight = window.innerHeight;
                const documentHeight = document.documentElement.scrollHeight;
                
                // 当滚动到距离底部200px时开始加载
                if (scrollTop + windowHeight >= documentHeight - 200) {
                    loadMoreContent();
                }
            });
        }
        
        // 加载更多内容
        async function loadMoreContent() {
            if (isLoading || !hasMore) return;
            
            isLoading = true;
            document.getElementById('loading-indicator').classList.remove('hidden');
            
            try {
                let url = `/api/get_notes?page=${currentPage}&per_page=6`;
                if (currentFilter) {
                    url += `&filename=${encodeURIComponent(currentFilter)}`;
                }
                
                const response = await fetch(url);
                const data = await response.json();
                
                if (response.ok && data.html) {
                    // 创建临时容器来解析HTML
                    const tempDiv = document.createElement('div');
                    tempDiv.innerHTML = data.html;
                    
                    // 将新内容添加到网格中
                    const contentGrid = document.getElementById('content-grid');
                    while (tempDiv.firstChild) {
                        contentGrid.appendChild(tempDiv.firstChild);
                    }
                    
                    currentPage++;
                    hasMore = data.has_more;
                    
                    // 更新总数显示
                    document.getElementById('total-count').textContent = data.total;
                    
                    if (!hasMore) {
                        document.getElementById('no-more-content').classList.remove('hidden');
                    }
                } else {
                    console.error('加载失败:', data.error || '未知错误');
                    hasMore = false;
                    document.getElementById('no-more-content').classList.remove('hidden');
                }
            } catch (error) {
                console.error('加载时出错:', error);
                hasMore = false;
                document.getElementById('no-more-content').classList.remove('hidden');
            } finally {
                isLoading = false;
                document.getElementById('loading-indicator').classList.add('hidden');
            }
        }
        
        // 发布笔记功能
        async function publishNote(filename, index) {
            try {
                const response = await fetch('/api/publish_note', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        filename: filename,
                        index: index
                    })
                });
                
                if (response.ok) {
                    alert('发布成功！');
                    // 保持筛选状态，重新加载内容而不是刷新整个页面
                    currentPage = 1;
                    hasMore = true;
                    
                    // 清空当前内容
                    const contentGrid = document.getElementById('content-grid');
                    contentGrid.innerHTML = '';
                    
                    // 隐藏"没有更多内容"提示
                    document.getElementById('no-more-content').classList.add('hidden');
                    
                    // 重新加载内容，保持当前筛选状态
                    loadMoreContent();
                } else {
                    alert('发布失败，请重试');
                }
            } catch (error) {
                console.error('发布时出错:', error);
                alert('发布时出错，请重试');
            }
        }
        
        // 监听滚动，改变导航栏样式
        window.addEventListener('scroll', function() {
            const header = document.querySelector('header');
            if (window.scrollY > 10) {
                header.classList.add('shadow');
                header.classList.remove('shadow-sm');
            } else {
                header.classList.remove('shadow');
                header.classList.add('shadow-sm');
            }
        });
        
        // 页面加载完成后初始化
        document.addEventListener('DOMContentLoaded', function() {
            loadFileList();
            initInfiniteScroll();
            
            // 绑定筛选器变化事件
            document.getElementById('file-filter').addEventListener('change', handleFilterChange);
            
            // 加载初始内容
            loadMoreContent();
        });
    </script>
</body></html>"""
        
        # 替换原有的结束标签
        final_html = final_html.replace('</main>', infinite_scroll_code)
        
        # 保存生成的HTML
        with open(self.output_path, 'w', encoding='utf-8') as f:
            f.write(final_html)
        
        print(f"已生成动态页面: {self.output_path}")
        
        return str(self.output_path)

if __name__ == "__main__":
    generator = XHSContentGenerator()
    generator.generate_page()