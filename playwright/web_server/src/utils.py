import base64
import datetime
import json
import os
from pathlib import Path
from urllib.parse import urlparse

import requests


class Utils:
    @staticmethod
    def rerank(query, documents):
        api_key = os.getenv("SILICONFLOW_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("SILICONFLOW_API_KEY is required for rerank")

        url = "https://api.siliconflow.cn/v1/rerank"
        payload = {
            "model": "BAAI/bge-reranker-v2-m3",
            "query": query,
            "documents": documents,
            "top_n": 4,
            "return_documents": True,
            "max_chunks_per_doc": 123,
            "overlap_tokens": 79,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        response = requests.post(url, json=payload, headers=headers)
        return json.loads(response.text)["results"]

    @staticmethod
    def image_to_base64(source):
        """Convert image file/URL to Base64 string"""
        if not source:
            return None
        if urlparse(source).scheme in ("http", "https"):
            response = requests.get(source)
            response.raise_for_status()
            content = response.content
        else:
            with open(source, "rb") as f:
                content = f.read()

        encoded = base64.b64encode(content).decode("utf-8")
        return f"data:image/png;base64,{encoded}"

    @staticmethod
    def download_images(urls, save_dir):
        """Download images with auto-incrementing filenames"""
        save_dir = Path(save_dir)
        save_dir.mkdir(parents=True, exist_ok=True)

        existing = list(save_dir.glob("image_*.png"))
        start_idx = max([int(f.stem.split("_")[1]) for f in existing] or [-1]) + 1

        for i, url in enumerate(urls):
            try:
                response = requests.get(url)
                response.raise_for_status()
                path = save_dir / f"image_{start_idx+i}.png"
                with open(path, "wb") as f:
                    f.write(response.content)
                print(f"Saved: {path}")
            except Exception as e:
                print(f"Failed to download {url}: {str(e)}")

    @staticmethod
    def get_latest_json_files(directory):
        files = os.listdir(directory)
        date_suffix_pairs = []
        for file in files:
            if file.endswith(".json"):
                try:
                    date_str = file[:8]
                    suffix = file[8]
                    date = datetime.datetime.strptime(date_str, "%Y%m%d")
                    date_suffix_pairs.append((date, suffix, file))
                except ValueError:
                    continue
        date_suffix_pairs.sort(key=lambda x: (-x[0].timestamp(), x[1]))
        if len(date_suffix_pairs) >= 2:
            return date_suffix_pairs[0][2], date_suffix_pairs[1][2]
        elif len(date_suffix_pairs) == 1:
            return date_suffix_pairs[0][2], None
        else:
            return None, None


def save_to_file(data, filename="output.json", base_dir=None):
    """
    将数据保存到指定目录的文件中。
    :param data: 要保存的数据
    :param filename: 文件名
    :param base_dir: 基础目录路径，默认为当前脚本所在目录下的 'hot_news'
    """
    try:
        if base_dir is None:
            script_dir = Path(__file__).resolve().parent
            base_dir = script_dir / "hot_news"
        else:
            base_dir = Path(base_dir)

        output_path = base_dir / filename
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as file:
            if isinstance(data, str):
                file.write(data)  # 如果是纯文本，直接写入
            else:
                json.dump(data, file, ensure_ascii=False, indent=4)  # 如果是JSON，格式化写入
        print(f"数据已成功保存到 {output_path}")
        return True
    except IOError as e:
        print(f"保存文件时出错: {e}")
        return False
