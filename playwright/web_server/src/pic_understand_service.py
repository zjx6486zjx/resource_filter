import os
import sys
import base64
import io
from pathlib import Path
from PIL import Image

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from api.llm_client import LLMApiClient
from api.response_parser import ResponseParser
from src.prompt import xhs_prompts

llm_client = LLMApiClient()

response_parser = ResponseParser()


class PicIdentifyService:
    @staticmethod
    def identify_xhs_pic_content(image_path):
        # 如果是本地文件路径，转换为base64格式
        if os.path.exists(image_path):
            try:
                # 使用PIL验证和标准化图片格式
                with Image.open(image_path) as img:
                    # 转换为RGB模式（确保兼容性）
                    if img.mode != 'RGB':
                        img = img.convert('RGB')
                    
                    # 将图片保存为JPEG格式到内存
                    img_buffer = io.BytesIO()
                    img.save(img_buffer, format='JPEG', quality=85)
                    img_buffer.seek(0)
                    
                    # 编码为base64
                    base64_image = base64.b64encode(img_buffer.getvalue()).decode('utf-8')
                    image_url = f"data:image/jpeg;base64,{base64_image}"
                    
            except Exception as e:
                print(f"图片处理失败: {e}")
                # 如果PIL处理失败，尝试直接读取文件
                try:
                    with open(image_path, "rb") as image_file:
                        base64_image = base64.b64encode(image_file.read()).decode('utf-8')
                        # 获取文件扩展名来确定MIME类型
                        file_ext = Path(image_path).suffix.lower()
                        if file_ext in ['.jpg', '.jpeg']:
                            mime_type = 'image/jpeg'
                        elif file_ext == '.png':
                            mime_type = 'image/png'
                        elif file_ext == '.webp':
                            mime_type = 'image/webp'
                        else:
                            mime_type = 'image/jpeg'  # 默认
                        image_url = f"data:{mime_type};base64,{base64_image}"
                except Exception as e2:
                    print(f"文件读取也失败: {e2}")
                    return None
        else:
            # 如果是URL，直接使用
            image_url = image_path
            
        prompt = xhs_prompts.understand_pic_txt_content.format_map({})
        print(f"    调用LLM API进行图片识别...")
        print(f"    📝 提示词长度: {len(prompt)} 字符")
        
        # 直接调用API而不使用safe_call，以便获得更详细的错误信息
        try:
            response = llm_client.doubao_identify_image(prompt, image_url)
            print(f"    ✅ API响应长度: {len(response) if response else 0}")
            print(f"    📄 API响应内容: {response[:200] if response else 'None'}...")  # 显示前200个字符
            
            if not response or response.strip() == "":
                print(f"    API返回空响应")
                return None
                
            # 对于图片识别，直接返回文本内容而不进行JSON解析
            # 因为API返回的是Markdown格式的分析结果，不是JSON
            print(f"    直接返回API响应内容")
            return response.strip()
            
        except Exception as e:
            print(f"    API调用异常: {e}")
            # 使用safe_call进行重试
            print(f"    使用重试机制...")
            response = ResponseParser.safe_call(llm_client.doubao_identify_image, prompt, image_url)
            if response:
                return response.strip()
            return None


    @staticmethod
    def merge_note_pic_txt_content(pic_content):
        prompt = xhs_prompts.merge_note_pic_txt_content.format_map({"pic_content": pic_content})
        response = ResponseParser.safe_call(llm_client.doubao_text_chat, prompt)
        # 对于文本合并，直接返回响应内容而不进行JSON解析
        return response.strip() if response else None

    @staticmethod
    def regen_note(note_title,note_desc,note_content):
        prompt = xhs_prompts.regen_note_prompt.format_map({"note_title": note_title, "note_desc": note_desc, "note_content": note_content})
        response = ResponseParser.safe_call(llm_client.doubao_text_chat, prompt)
        # 对于文本合并，直接返回响应内容而不进行JSON解析
        return response.strip() if response else None

    @staticmethod
    def gen_keyword(new_note):
        prompt = xhs_prompts.gen_keyword_prompt.format_map({"new_note": new_note})
        response = ResponseParser.safe_call(llm_client.doubao_json_chat, prompt)
        return response_parser.parse_response(response)