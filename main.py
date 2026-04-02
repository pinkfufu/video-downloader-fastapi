from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
import yt_dlp
import tempfile
import os
import threading
import uuid

# 安装环境：conda create -n venv_downloader python=3.10 -y && conda activate venv_downloader && pip install fastapi uvicorn yt-dlp "numpy<2"
# 启动命令：uvicorn main:app --host 0.0.0.0 --port 8000
# 警告：不要在开发环境下频繁保存代码触发 reload，否则会导致内存中的 download_tasks 任务丢失报错 404。

# 服务器部署：
# sudo apt update && sudo apt install ffmpeg -y
# apt install uvicorn
# apt install python3.12-venv
# python3 -m venv venv
# source venv/bin/activate
# pip install fastapi uvicorn yt-dlp "numpy<2"
# nohup uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1 > /dev/null 2>&1 &
app = FastAPI()

# 全局任务字典 (生产环境建议使用 SQLite 或 Redis)
download_tasks = {}

COOKIES_FILE = "cookies.txt"


def download_worker(url, task_id):
    # 使用系统临时目录下的子文件夹，避免权限问题
    temp_dir = os.path.join(tempfile.gettempdir(), "video_downloads", task_id)
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)

    output_tmpl = os.path.join(temp_dir, '%(title)s.%(ext)s')

    ydl_opts = {
        'outtmpl': output_tmpl,
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'merge_output_format': 'mp4',
        'quiet': True,
        'no_warnings': True,
        'progress_hooks': [lambda d: ydl_progress_hook(d, task_id)],
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    }

    # Cookie 逻辑优化
    cookie_path = os.path.join(os.getcwd(), COOKIES_FILE)
    if os.path.isfile(cookie_path):
        ydl_opts['cookiefile'] = cookie_path
    else:
        # 针对 Windows，尝试从浏览器提取
        ydl_opts['cookiesfrombrowser'] = ('chrome',)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # 获取视频信息并执行下载
            info = ydl.extract_info(url, download=True)
            # 获取最终生成的本地文件绝对路径
            final_path = ydl.prepare_filename(info)

            # 处理可能的格式转换后缀变化
            if not os.path.exists(final_path):
                # 尝试检查 .mp4 结尾
                base_path = os.path.splitext(final_path)[0]
                if os.path.exists(base_path + ".mp4"):
                    final_path = base_path + ".mp4"

            download_tasks[task_id]['status'] = 'finished'
            download_tasks[task_id]['filename'] = final_path

    except Exception as e:
        download_tasks[task_id]['status'] = 'error'
        error_msg = str(e)
        if "ffmpeg" in error_msg.lower():
            error_msg = "系统未安装 FFmpeg，无法合并音视频。请安装 FFmpeg 并添加到环境变量。"
        download_tasks[task_id]['error'] = error_msg


def ydl_progress_hook(d, task_id):
    if d['status'] == 'downloading':
        total = d.get('total_bytes') or d.get('total_bytes_estimate') or 100
        downloaded = d.get('downloaded_bytes', 0)
        percent = int(downloaded / total * 100)
        # 限制最高 99%，留 1% 给合并阶段
        download_tasks[task_id]['progress'] = min(percent, 99)
    elif d['status'] == 'finished':
        download_tasks[task_id]['progress'] = 100


@app.get("/", response_class=HTMLResponse)
def index():
    return """
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="UTF-8">
        <title>视频下载器</title>
        <style>
            body { margin: 0; font-family: 'Segoe UI', sans-serif; background: linear-gradient(135deg, #a1c4fd, #c2e9fb); height: 100vh; display: flex; justify-content: center; align-items: center; }
            .container { background: rgba(255, 255, 255, 0.8); backdrop-filter: blur(10px); border-radius: 20px; padding: 40px; width: 450px; box-shadow: 0 10px 30px rgba(0,0,0,0.1); text-align: center; }
            input { width: 100%; padding: 12px; margin-bottom: 20px; border: 1px solid #ddd; border-radius: 8px; box-sizing: border-box; }
            button { background: #4facfe; color: white; border: none; padding: 12px 30px; border-radius: 25px; cursor: pointer; transition: 0.3s; width: 100%; font-size: 16px; }
            button:hover { background: #00f2fe; transform: translateY(-2px); }
            #progress-container { margin-top: 25px; display: none; }
            #progress-bar { height: 12px; background: #eee; border-radius: 6px; overflow: hidden; }
            #bar-inner { width: 0%; height: 100%; background: #43e97b; transition: width 0.3s; }
            #status-text { margin-top: 10px; font-size: 14px; color: #666; }
            #result-link { margin-top: 20px; }
            a { color: #007aff; text-decoration: none; font-weight: bold; border: 1px solid #007aff; padding: 8px 20px; border-radius: 5px; }
        </style>
    </head>
    <body>
        <div class="container">
            <h2>🎥 视频下载器</h2>
            <input type="text" id="url" placeholder="支持 YouTube, BiliBili 等..." />
            <button onclick="startDownload()">启动引擎</button>
            <div id="progress-container">
                <div id="progress-bar"><div id="bar-inner"></div></div>
                <div id="status-text">准备下载...</div>
            </div>
            <div id="result-link"></div>
        </div>
        <script>
            function startDownload() {
                const url = document.getElementById('url').value;
                if(!url) return alert('请输入链接');

                document.getElementById('progress-container').style.display = 'block';
                document.getElementById('result-link').innerHTML = '';

                fetch(`/start_download?url=${encodeURIComponent(url)}`)
                    .then(r => r.json())
                    .then(data => poll(data.task_id));
            }
            function poll(id) {
                fetch(`/progress?task_id=${id}`)
                    .then(r => r.json())
                    .then(data => {
                        document.getElementById('bar-inner').style.width = data.progress + '%';
                        document.getElementById('status-text').innerText = `已下载: ${data.progress}%`;

                        if(data.status === 'finished') {
                            document.getElementById('status-text').innerText = '🎉 下载成功！';
                            document.getElementById('result-link').innerHTML = `<a href="/download_file?task_id=${id}">立即保存到本地</a>`;
                        } else if(data.status === 'error') {
                            document.getElementById('status-text').innerText = '❌ 错误: ' + data.error;
                            document.getElementById('status-text').style.color = 'red';
                        } else {
                            setTimeout(() => poll(id), 1000);
                        }
                    });
            }
        </script>
    </body>
    </html>
    """


@app.get("/start_download")
def start_download(url: str):
    task_id = str(uuid.uuid4())
    download_tasks[task_id] = {'status': 'downloading', 'progress': 0, 'filename': None, 'error': None}
    threading.Thread(target=download_worker, args=(url, task_id), daemon=True).start()
    return {"task_id": task_id}


@app.get("/progress")
def get_progress(task_id: str):
    task = download_tasks.get(task_id)
    if not task:
        # 如果重启了，这里会报 404
        return {"status": "error", "progress": 0, "error": "任务已失效（服务器可能已重启）"}
    return task


@app.get("/download_file")
def download_file(task_id: str):
    task = download_tasks.get(task_id)
    if not task or task['status'] != 'finished' or not task['filename']:
        raise HTTPException(status_code=404, detail="文件不存在")

    # 真正的文件名
    real_name = os.path.basename(task['filename'])
    return FileResponse(
        path=task['filename'],
        filename=real_name,
        media_type='application/octet-stream'
    )