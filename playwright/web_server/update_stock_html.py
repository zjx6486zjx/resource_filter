import glob
import json
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, Response, url_for

# 修改静态文件夹路径
current_dir = Path(__file__).resolve().parent
target_dir = current_dir  # 直接使用当前目录，因为logs文件夹就在当前目录下

app = Flask(__name__, static_folder=str(current_dir / "pic"))


def generate_html():
    """
    生成 HTML 文件，读取 JSON 数据并写入 HTML 表格。
    """
    with app.app_context():
        # 在生成HTML时获取当前日期
        json_path = target_dir / "logs" / "doubao_analysis_result0.json"
        # json_path3 = target_dir / "logs" / "analysis_result.json"

        # 读取 JSON 数据
        with open(json_path, "r", encoding="utf-8") as file:
            data = json.load(file)
        # with open(json_path3, "r", encoding="utf-8") as file:
        #     data3 = json.load(file)

        # 合并数据
        merged_data = data

        # 排序：将 stock_code 含有 SH、SZ 的顺序往上排
        def sort_key(item):
            for company in item.get("related_company", []):
                if "SH" in company.get("stock_code", "") or "SZ" in company.get("stock_code", ""):
                    return 0
            return 1

        sorted_data = sorted(merged_data, key=sort_key)

        # 构建 HTML
        html_content = """
        <html>
        <head>
            <meta charset="UTF-8">
            <title>Stock Analysis Result</title>
            <style>
                body {
                    font-family: 'Segoe UI', Arial, sans-serif;
                    background-color: #f8f9fa;
                    padding: 20px;
                }
                table {
                    width: 100%;
                    border-collapse: collapse;
                    margin: 20px 0;
                    background: white;
                    border-radius: 8px;
                    overflow: hidden;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                }
                th {
                    background-color: #3f51b5;
                    color: white;
                    padding: 16px;
                    font-size: 1.1em;
                }
                .news-title {
                    background: #f8fbff;
                    border-bottom: 2px solid #e3f2fd;
                    padding: 15px;
                    text-align: center;
                }
                .company-container {
                    display: flex;
                    gap: 20px;
                    padding: 18px 0;
                    background: #f8fbff;
                    border-bottom: 1px solid #e3f2fd;
                    flex-wrap: nowrap;  /* 新增：强制不换行 */
                }

                .company-image {
                    flex: 0 0 50%;  /* 固定50%宽度 */
                    width: 50%;     /* 显式声明宽度 */
                    max-width: 50%; /* 防止溢出 */
                    height: auto;
                    object-fit: cover;
                    border-radius: 4px;
                }

                .company-details {
                    flex: 0 0 50%;  /* 固定50%宽度 */
                    width: 50%;
                    display: flex;
                    flex-direction: column;
                    gap: 10px;
                }

                .detail-row {
                    display: flex;
                    gap: 15px;
                }

                .detail-cell {
                    flex: 1;
                    min-width: 200px;
                }

                @media (max-width: 768px) {
                    .company-container {
                        flex-direction: row; /* 强制水平布局 */
                        flex-wrap: nowrap;
                    }
                    .company-image {
                        width: 50%;        /* 移动端强制50% */
                        max-width: 50%;
                        margin-bottom: 0;  /* 移除底部间距 */
                    }
                    .company-details {
                        width: 50%;
                    }
                    .detail-row {
                        flex-direction: column;
                    }
                    .detail-cell {
                        min-width: 100%;
                    }
                    .analysis-value {
                        overflow: hidden;
                        text-overflow: ellipsis;
                        display: -webkit-box;
                        -webkit-line-clamp: 3;
                        -webkit-box-orient: vertical;
                        line-height: 1.4;
                        font-size: 0.9em;
                        color: #666;
                    }
                }

                .detail-cell strong {
                    display: block;
                    margin-bottom: 5px;
                    color: #3f51b5;
                }
            </style>
        </head>
        <body>
            <h1>Stock Analysis Result</h1>
            <table>
                <tr><th>Related News</th></tr>
        """

        for item in sorted_data:
            news_title = item.get("related_news_title", "")
            companies = item.get("related_company", [])

            html_content += f"""
            <tr>
                <td class="news-title" colspan="2">{news_title}</td>
            </tr>
            """

            for company in companies:
                stock_name = company.get("stock_name", "")
                stock_code = company.get("stock_code", "")
                analysis = company.get("analysis", "")
                analysis_result = company.get("analysis_result", "")

                image_pattern = str(Path(app.static_folder) / "stock" / f"{stock_name}*")
                image_url = next(iter(glob.glob(image_pattern)), None)
                if image_url:
                    image_url = url_for("static", filename=str(Path(image_url).relative_to(app.static_folder)))
                    image_tag = f'<img src="{image_url}" class="company-image">'
                else:
                    image_tag = ""

                html_content += f"""
                <tr>
                    <td colspan="2" class="company-container">
                        {image_tag}
                        <div class="company-details">
                            <div class="detail-row">
                                <div class="detail-cell">
                                    <strong>Stock Name:</strong> {stock_name}<br>
                                    <strong>Stock Code:</strong> {stock_code}
                                </div>
                                <div class="detail-cell">
                                    <strong>Analysis Result:</strong> {analysis_result}
                                </div>
                            </div>
                            <div class="analysis-value">{analysis}</div>
                        </div>
                    </td>
                </tr>
                """

            html_content += "<tr><td colspan='2' style='height:20px'></td></tr>"

        html_content += """
        </table>
        </body>
        </html>
        """
    # 保存 HTML 文件
    html_path = current_dir /"logs"/"stock_analysis_result.html"
    with open(html_path, "w", encoding="utf-8") as file:
        file.write(html_content)
    return html_content


@app.route("/get_stock_analysis_result")
def serve_html():
    """
    返回动态生成的 HTML 内容。
    """
    return Response(generate_html(), content_type="text/html")


if __name__ == "__main__":
    app.config.update(
        {"SERVER_NAME": "localhost:5011", "APPLICATION_ROOT": "/", "PREFERRED_URL_SCHEME": "http"}  # 添加服务器配置
    )

    # 创建后台任务调度器
    scheduler = BackgroundScheduler()
    scheduler.add_job(generate_html, "interval", minutes=1)
    scheduler.start()

    print("Flask server and scheduler started. Press Ctrl+C to exit")
    try:
        # 启动 Flask 应用
        app.run(host="0.0.0.0", port=5011, threaded=True)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
