import os
import re
import uuid
import threading
import tempfile
import shutil
import logging
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
import yt_dlp
import httpx

# --- 初始化与配置 ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("VideoDownloader")

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# 存储下载任务状态
download_tasks = {}
# 设置下载根目录
BASE_DOWNLOAD_DIR = os.path.join(os.getcwd(), "downloads")
os.makedirs(BASE_DOWNLOAD_DIR, exist_ok=True)


# --- 核心解析与下载类 ---

class CoreDownloader:
    @staticmethod
    def is_douyin(url: str) -> bool:
        return any(d in url for d in ["douyin.com", "iesdouyin.com", "v.douyin.com"])

    @staticmethod
    def get_ffmpeg() -> Optional[str]:
        return os.path.dirname(shutil.which("ffmpeg")) if shutil.which("ffmpeg") else None

    def download_worker(self, url: str, task_id: str):
        task_dir = os.path.join(BASE_DOWNLOAD_DIR, task_id)
        os.makedirs(task_dir, exist_ok=True)

        try:
            # 1. 如果是抖音，走专用解析
            if self.is_douyin(url):
                self._handle_douyin(url, task_id, task_dir)
            # 2. 其他走通用 yt-dlp
            else:
                self._handle_universal(url, task_id, task_dir)
        except Exception as e:
            logger.error(f"Download Error: {e}")
            download_tasks[task_id].update({"status": "error", "error": str(e)})

    def _handle_douyin(self, url: str, task_id: str, task_dir: str):
        # 极简模拟解析逻辑（实际建议配合你之前的 DouyinParser 完整算法）
        headers = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)"}
        with httpx.Client(follow_redirects=True, headers=headers, timeout=20) as client:
            resp = client.get(url)
            # 简单演示：直接用 yt-dlp 尝试解析抖音
            self._handle_universal(url, task_id, task_dir)

    def _handle_universal(self, url: str, task_id: str, task_dir: str):
        ffmpeg_path = self.get_ffmpeg()
        cookie_path = os.path.join(os.getcwd(), "www.youtube.com_cookies.txt")


        ydl_opts = {
            # 这里的 format 更加宽松，增加 best 兜底
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': os.path.join(task_dir, '%(title)s.%(ext)s'),
            'merge_output_format': 'mp4',
            # 关键：切换到 android 客户端，目前比 ios 稳定
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'web'],
                    'skip': ['dash', 'hls']
                }
            },
            # 强制不使用特定的签名算法，绕过 n-challenge
            'compatible_auth': True,
            'quiet': False,
            'no_warnings': False,
            'progress_hooks': [lambda d: self._progress_hook(d, task_id)],
        }

        if ffmpeg_path:
            ydl_opts['ffmpeg_location'] = ffmpeg_path
        if os.path.exists(cookie_path):
            ydl_opts['cookiefile'] = cookie_path

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.cache.remove()
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)
            # 检查是否有合并后的文件
            if not os.path.exists(file_path):
                name, _ = os.path.splitext(file_path)
                for ext in ['.mp4', '.mkv', '.webm']:
                    if os.path.exists(name + ext):
                        file_path = name + ext
                        break

            download_tasks[task_id].update({
                "status": "finished",
                "progress": 100,
                "file_path": file_path,
                "title": info.get('title', 'video')
            })

    def _progress_hook(self, d, task_id):
        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 100
            downloaded = d.get('downloaded_bytes', 0)
            percent = int(downloaded / total * 100)
            download_tasks[task_id]['progress'] = min(percent, 99)


# --- 路由逻辑 ---

core = CoreDownloader()


@app.get("/", response_class=HTMLResponse)
async def index():
    return """
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>万能视频下载器</title>
        <style>
            body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #c2e9fb; height: 100vh; display: flex; justify-content: center; align-items: center; }
            .card { background: rgba(255, 255, 255, 0.9); backdrop-filter: blur(10px); padding: 40px; border-radius: 24px; box-shadow: 0 10px 30px rgba(0,0,0,0.08); width: 100%; max-width: 400px; text-align: center; }
            h2 { margin-bottom: 24px; color: #333; display: flex; align-items: center; justify-content: center; gap: 10px; }
            input { width: 100%; padding: 14px; border: 1px solid #e0e0e0; border-radius: 12px; margin-bottom: 20px; box-sizing: border-box; outline: none; transition: 0.3s; }
            input:focus { border-color: #4facfe; box-shadow: 0 0 0 3px rgba(79, 172, 254, 0.2); }
            button { width: 100%; padding: 14px; background: #4facfe; color: white; border: none; border-radius: 12px; font-size: 16px; font-weight: 600; cursor: pointer; transition: 0.3s; }
            button:hover { background: #00f2fe; transform: translateY(-1px); }
            .progress-area { margin-top: 24px; display: none; }
            .bar { height: 8px; background: #eee; border-radius: 4px; overflow: hidden; margin-bottom: 8px; }
            .bar-fill { width: 0%; height: 100%; background: #43e97b; transition: width 0.3s; }
            .status { font-size: 14px; color: #666; }
            .error { color: #ff4d4f; font-size: 13px; margin-top: 10px; }
            .btn-download { display: inline-block; margin-top: 20px; padding: 10px 24px; background: #fff; border: 2px solid #4facfe; color: #4facfe; border-radius: 8px; text-decoration: none; font-weight: bold; transition: 0.3s; }
            .btn-download:hover { background: #4facfe; color: #fff; }
        </style>
    </head>
    <body>
        <div class="card">
            <h2>🎬 视频下载器</h2>
            <input type="text" id="url" placeholder="粘贴视频链接 (YouTube, 抖音...)" />
            <button onclick="startDownload()" id="btn-run">启动引擎</button>
            <div class="progress-area" id="p-area">
                <div class="bar"><div class="bar-fill" id="fill"></div></div>
                <div class="status" id="status">准备中...</div>
                <div id="error-box" class="error"></div>
                <div id="result"></div>
            </div>
        </div>
        <script>
            async function startDownload() {
                const url = document.getElementById('url').value;
                if(!url) return;

                const btn = document.getElementById('btn-run');
                const pArea = document.getElementById('p-area');
                const fill = document.getElementById('fill');
                const status = document.getElementById('status');
                const errorBox = document.getElementById('error-box');
                const result = document.getElementById('result');

                btn.disabled = true;
                pArea.style.display = 'block';
                errorBox.innerText = '';
                result.innerHTML = '';

                try {
                    const resp = await fetch(`/api/start?url=${encodeURIComponent(url)}`);
                    const { task_id } = await resp.json();

                    const timer = setInterval(async () => {
                        const pResp = await fetch(`/api/progress/${task_id}`);
                        const data = await pResp.json();

                        fill.style.width = data.progress + '%';
                        status.innerText = `处理中: ${data.progress}%`;

                        if(data.status === 'finished') {
                            clearInterval(timer);
                            status.innerText = '✅ 下载完成！';
                            btn.disabled = false;
                            result.innerHTML = `<a href="/api/get/${task_id}" class="btn-download">保存到本地</a>`;
                        } else if(data.status === 'error') {
                            clearInterval(timer);
                            status.innerText = '❌ 失败';
                            errorBox.innerText = data.error;
                            btn.disabled = false;
                        }
                    }, 1000);
                } catch(e) {
                    errorBox.innerText = '请求服务失败';
                    btn.disabled = false;
                }
            }
        </script>
    </body>
    </html>
    """


@app.get("/api/start")
def start(url: str):
    task_id = str(uuid.uuid4())
    download_tasks[task_id] = {"status": "downloading", "progress": 0, "error": None}
    threading.Thread(target=core.download_worker, args=(url, task_id), daemon=True).start()
    return {"task_id": task_id}


@app.get("/api/progress/{task_id}")
def progress(task_id: str):
    return download_tasks.get(task_id, {"status": "error", "error": "任务过期"})


@app.get("/api/get/{task_id}")
def get_file(task_id: str):
    task = download_tasks.get(task_id)
    if not task or not task.get("file_path"):
        raise HTTPException(404, "文件未找到")
    return FileResponse(task["file_path"], filename=os.path.basename(task["file_path"]))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)