import os
import re
import uuid
import json
import logging
import requests
import yt_dlp
from pathlib import Path
from typing import Dict
from urllib.parse import unquote
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
import time
import random
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
import http.cookiejar

# --- 基础配置 ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("SaveAny")

DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

tasks_db: Dict[str, dict] = {}


# ==========================================
# 工具函数：处理 Cookie
# ==========================================
def parse_cookies_from_file(cookie_file: str) -> dict:
    """
    解析导出的 Cookie 文件
    支持多种格式：
    1. JSON 数组格式 (Get Cookies 插件)
    2. JSON 对象格式
    3. Netscape 格式 (curl/wget 标准格式)
    4. 简单键值对格式 (name=value; name2=value2)
    """
    cookies = {}
    cookie_path = Path(cookie_file)

    if not cookie_path.exists():
        logger.warning(f"Cookie 文件不存在: {cookie_file}")
        return cookies

    try:
        with open(cookie_path, 'r', encoding='utf-8') as f:
            content = f.read().strip()

        logger.info(f"正在解析 Cookie 文件: {cookie_file}")

        # 方法 1：JSON 数组格式
        if content.startswith('['):
            try:
                data = json.loads(content)
                for item in data:
                    if isinstance(item, dict):
                        name = item.get('name') or item.get('Name')
                        value = item.get('value') or item.get('Value')
                        if name and value:
                            cookies[name] = value
                logger.info(f"成功解析 JSON 数组格式，获得 {len(cookies)} 个 Cookie")
                return cookies
            except:
                pass

        # 方法 2：JSON 对象格式
        if content.startswith('{'):
            try:
                data = json.loads(content)
                if isinstance(data, dict):
                    cookies = {k: str(v) for k, v in data.items()}
                    logger.info(f"成功解析 JSON 对象格式，获得 {len(cookies)} 个 Cookie")
                    return cookies
            except:
                pass

        # 方法 3：Netscape 格式 (curl 标准格式)
        # 格式: # domain, flag, path, secure, expiration, name, value
        if '#' in content or content.startswith('domain'):
            try:
                lines = content.split('\n')
                for line in lines:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    parts = line.split('\t')
                    if len(parts) >= 7:
                        name = parts[5]
                        value = parts[6]
                        if name and value:
                            cookies[name] = value

                if cookies:
                    logger.info(f"成功解析 Netscape 格式，获得 {len(cookies)} 个 Cookie")
                    return cookies
            except Exception as e:
                logger.warning(f"Netscape 格式解析失败: {e}")

        # 方法 4：简单键值对格式
        try:
            # 处理多行或单行格式
            if '=' in content:
                # 尝试多行格式
                lines = content.split('\n')
                if len(lines) > 1:
                    for line in lines:
                        line = line.strip()
                        if line and '=' in line:
                            parts = line.split(';')
                            if parts:
                                name_value = parts[0].strip()
                                if '=' in name_value:
                                    name, value = name_value.split('=', 1)
                                    cookies[name.strip()] = value.strip()
                else:
                    # 单行格式
                    pairs = content.split(';')
                    for pair in pairs:
                        pair = pair.strip()
                        if '=' in pair:
                            name, value = pair.split('=', 1)
                            cookies[name.strip()] = value.strip()

                if cookies:
                    logger.info(f"成功解析键值对格式，获得 {len(cookies)} 个 Cookie")
                    return cookies
        except Exception as e:
            logger.warning(f"键值对格式解析失败: {e}")

        logger.warning(f"无法识别 Cookie 文件格式，已读取内容: {content[:100]}...")
        return cookies

    except Exception as e:
        logger.error(f"加载 Cookie 失败: {e}")
        return cookies


# ==========================================
# 核心引擎：PornHub 下载 (Selenium + Cookie)
# ==========================================
class PornHubSeleniumParser:
    """使用 Selenium 模拟真实浏览器访问 PornHub"""

    def __init__(self, cookies_dict: dict = None):
        self.driver = None
        self.cookies_dict = cookies_dict or {}

    def _init_driver(self):
        """初始化 Chrome 驱动"""
        chrome_options = Options()
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)

        try:
            self.driver = webdriver.Chrome(options=chrome_options)
        except Exception as e:
            logger.error(f"Chrome 驱动初始化失败: {e}")
            raise ValueError("需要安装 ChromeDriver")

    def _extract_url(self, text: str) -> str:
        pattern = r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
        links = re.findall(pattern, text)
        return links[0] if links else ""

    def _add_cookies(self):
        """添加 Cookie 到浏览器"""
        if not self.cookies_dict:
            logger.warning("[PornHub] 没有 Cookie 可用，将尝试无登录下载")
            return

        try:
            # 先访问一次主页以建立 session
            logger.info("[PornHub] 正在建立浏览器会话...")
            self.driver.get("https://www.pornhub.com/")
            time.sleep(2)

            # 添加 Cookie
            added_count = 0
            for name, value in self.cookies_dict.items():
                try:
                    self.driver.add_cookie({
                        'name': name,
                        'value': value,
                        'domain': '.pornhub.com',
                        'path': '/',
                    })
                    added_count += 1
                except Exception as e:
                    logger.debug(f"添加 Cookie '{name}' 失败: {e}")

            logger.info(f"[PornHub] 已成功添加 {added_count}/{len(self.cookies_dict)} 个 Cookie")
            time.sleep(1)
        except Exception as e:
            logger.warning(f"[PornHub] 添加 Cookie 失败: {e}")

    def parse_and_download(self, raw_input: str, task_id: str) -> str:
        """使用浏览器解析 PornHub 视频"""
        try:
            self._init_driver()

            url = self._extract_url(raw_input)
            if not url:
                raise ValueError("链接提取失败")

            logger.info(f"[PornHub] 正在添加 Cookie 到浏览器...")
            self._add_cookies()

            logger.info(f"[PornHub] 正在加载页面: {url}")
            self.driver.get(url)

            # 等待页面加载
            logger.info("[PornHub] 等待页面加载完成...")
            time.sleep(5)

            # 方法 1：尝试从 JavaScript 执行获取视频信息
            logger.info("[PornHub] 尝试从页面提取视频源...")
            try:
                video_data = self.driver.execute_script("""
                    var videos = [];
                    var sources = document.querySelectorAll('video source, source[type="video/mp4"]');
                    sources.forEach(function(source) {
                        var src = source.getAttribute('src');
                        if (src && (src.includes('mp4') || src.includes('video'))) {
                            videos.push(src);
                        }
                    });
                    return videos;
                """)

                if video_data and len(video_data) > 0:
                    logger.info(f"[PornHub] 找到 {len(video_data)} 个视频源")
                    for video_url in video_data:
                        try:
                            logger.info(f"[PornHub] 正在下载视频: {video_url[:100]}...")
                            title = f"pornhub_video_{task_id}"
                            file_path = DOWNLOAD_DIR / f"{title}.mp4"
                            self._download_video(video_url, file_path)
                            return str(file_path)
                        except Exception as e:
                            logger.warning(f"[PornHub] 视频下载失败: {e}")
                            continue
            except Exception as e:
                logger.warning(f"[PornHub] JavaScript 提取失败: {e}")

            # 方法 2：查找所有视频标签和链接
            logger.info("[PornHub] 尝试从 HTML 提取视频链接...")
            html = self.driver.page_source

            # 寻找各种格式的 mp4 链接
            mp4_pattern = r'https?://[^\s"\'<>]+\.mp4[^\s"\'<>]*'
            mp4_urls = re.findall(mp4_pattern, html)

            # 去重
            mp4_urls = list(set(mp4_urls))

            if mp4_urls:
                logger.info(f"[PornHub] 找到 {len(mp4_urls)} 个 MP4 链接")
                for video_url in mp4_urls:
                    try:
                        logger.info(f"[PornHub] 正在下载视频: {video_url[:100]}...")
                        title = f"pornhub_video_{task_id}"
                        file_path = DOWNLOAD_DIR / f"{title}.mp4"
                        self._download_video(video_url, file_path)
                        return str(file_path)
                    except Exception as e:
                        logger.warning(f"[PornHub] 下载失败，尝试下一个: {e}")
                        continue

            # 方法 3：从页面 JavaScript 代码中搜索视频 URL
            logger.info("[PornHub] 尝试从 JavaScript 代码中搜索...")
            js_video_pattern = r'"mp4Url"\s*:\s*"([^"]+)"'
            js_urls = re.findall(js_video_pattern, html)

            if js_urls:
                logger.info(f"[PornHub] 找到 {len(js_urls)} 个视频 URL")
                for video_url in js_urls:
                    try:
                        logger.info(f"[PornHub] 正在下载视频...")
                        title = f"pornhub_video_{task_id}"
                        file_path = DOWNLOAD_DIR / f"{title}.mp4"
                        self._download_video(video_url, file_path)
                        return str(file_path)
                    except Exception as e:
                        logger.warning(f"[PornHub] 下载失败: {e}")
                        continue

            raise ValueError("无法找到视频源。可能需要登录或视频不可用。请检查 Cookie 是否有效。")

        finally:
            if self.driver:
                self.driver.quit()

    def _download_video(self, url: str, file_path: Path):
        """下载视频文件"""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Referer": "https://www.pornhub.com/",
            "Range": "bytes=0-",
        }

        # 添加 Cookie 到请求头
        if self.cookies_dict:
            cookie_str = "; ".join([f"{k}={v}" for k, v in self.cookies_dict.items()])
            headers["Cookie"] = cookie_str

        logger.info(f"[PornHub] 正在建立下载连接...")
        response = requests.get(url, headers=headers, stream=True, timeout=30, allow_redirects=True)
        response.raise_for_status()

        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0

        logger.info(f"[PornHub] 文件大小: {total_size / (1024 * 1024):.2f} MB")

        with open(file_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        percent = (downloaded / total_size) * 100
                        logger.info(
                            f"[PornHub] 下载进度: {percent:.1f}% ({downloaded / (1024 * 1024):.2f} MB / {total_size / (1024 * 1024):.2f} MB)")

        logger.info(f"[PornHub] 下载完成: {file_path}")


# ==========================================
# 核心引擎 A：抖音 Selenium 方案
# ==========================================
class DouyinSeleniumParser:
    """使用 Selenium 模拟真实浏览器访问抖音"""

    def __init__(self):
        self.driver = None

    def _init_driver(self):
        """初始化 Chrome 驱动"""
        chrome_options = Options()
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)

        try:
            self.driver = webdriver.Chrome(options=chrome_options)
        except Exception as e:
            logger.error(f"Chrome 驱动初始化失败: {e}")
            raise ValueError("需要安装 ChromeDriver")

    def _extract_url(self, text: str) -> str:
        pattern = r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
        links = re.findall(pattern, text)
        return links[0] if links else ""

    def parse_and_download(self, raw_input: str, task_id: str) -> str:
        """使用浏览器解析抖音视频"""
        try:
            self._init_driver()

            url = self._extract_url(raw_input)
            if not url:
                raise ValueError("链接提取失败")

            logger.info(f"[抖音] 使用浏览器打开: {url}")
            self.driver.get(url)

            time.sleep(3)

            try:
                html = self.driver.page_source
                pattern = r'<script id="RENDER_DATA" type="application/json">(.*?)</script>'
                match = re.search(pattern, html)

                if match:
                    logger.info("[抖音] 成功获取 RENDER_DATA")
                    raw_json = unquote(match.group(1))
                    data = json.loads(raw_json)

                    video_info = None

                    def find_aweme(obj):
                        nonlocal video_info
                        if isinstance(obj, dict):
                            if "aweme" in obj and "detail" in obj["aweme"]:
                                video_info = obj["aweme"]["detail"]
                                return
                            for v in obj.values():
                                find_aweme(v)
                        elif isinstance(obj, list):
                            for i in obj:
                                find_aweme(i)

                    find_aweme(data)

                    if video_info:
                        play_url = video_info["video"]["play_addr"]["url_list"][0]
                        if play_url.startswith("//"):
                            play_url = "https:" + play_url

                        title = video_info.get("desc", "douyin_video")
                        safe_title = re.sub(r'[\\/*?:"<>|]', "_", title)[:50]
                        file_path = DOWNLOAD_DIR / f"{safe_title}_{task_id}.mp4"

                        logger.info(f"[抖音] 开始下载视频...")
                        self._download_video(play_url, file_path)

                        return str(file_path)
            except Exception as e:
                logger.warning(f"RENDER_DATA 解析失败: {e}")

            logger.info("[抖音] 尝试备选方案")
            video_urls = self._extract_video_from_page()
            if video_urls:
                for video_url in video_urls:
                    try:
                        file_path = DOWNLOAD_DIR / f"douyin_video_{task_id}.mp4"
                        self._download_video(video_url, file_path)
                        return str(file_path)
                    except:
                        continue

            raise ValueError("无法获取视频信息")

        finally:
            if self.driver:
                self.driver.quit()

    def _extract_video_from_page(self):
        """从页面源码中提取视频链接"""
        try:
            html = self.driver.page_source
            video_pattern = r'<video[^>]*>.*?<source[^>]*src=["\']([^"\']+)["\']'
            matches = re.findall(video_pattern, html, re.DOTALL)
            return matches
        except:
            return []

    def _download_video(self, url: str, file_path: Path):
        """下载视频文件"""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Referer": "https://www.douyin.com/",
        }

        response = requests.get(url, headers=headers, stream=True, timeout=30)
        response.raise_for_status()

        with open(file_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)

        logger.info(f"[抖音] 下载完成: {file_path}")


# ==========================================
# 核心引擎 B：YouTube 下载
# ==========================================
def youtube_download(url: str, task_id: str):
    """YouTube 专用下载"""
    logger.info(f"[YouTube] 开始处理: {url}")

    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': str(DOWNLOAD_DIR / f'%(title)s_{task_id}.%(ext)s'),
        'merge_output_format': 'mp4',
        'noplaylist': True,
        'quiet': False,
        'socket_timeout': 30,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        },
        'extractor_args': {
            'youtube': {
                'skip': ['hls', 'dash']
            }
        }
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            logger.info(f"[YouTube] 正在提取视频信息...")
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)
            logger.info(f"[YouTube] 下载完成: {file_path}")
            return file_path
    except Exception as e:
        logger.error(f"[YouTube] 下载失败: {e}")
        raise


# ==========================================
# 核心引擎 C：通用下载
# ==========================================
def generic_download(url: str, task_id: str):
    """通用下载方案"""
    logger.info(f"[通用] 使用通用下载方案处理: {url}")

    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': str(DOWNLOAD_DIR / f'%(title)s_{task_id}.%(ext)s'),
        'merge_output_format': 'mp4',
        'noplaylist': True,
        'quiet': False,
        'socket_timeout': 30,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)
            logger.info(f"[通用] 下载完成: {file_path}")
            return file_path
    except Exception as e:
        logger.error(f"[通用] 下载失败: {e}")
        raise


# ==========================================
# 后台调度逻辑
# ==========================================
def download_worker(url: str, task_id: str):
    try:
        if "douyin.com" in url or "v.douyin" in url:
            logger.info(f"[任务 {task_id}] 识别为抖音链接")
            path = DouyinSeleniumParser().parse_and_download(url, task_id)
        elif "youtube.com" in url or "youtu.be" in url:
            logger.info(f"[任务 {task_id}] 识别为 YouTube 链接")
            path = youtube_download(url, task_id)
        elif "pornhub.com" in url:
            logger.info(f"[任务 {task_id}] 识别为 PornHub 链接")

            # 加载 Cookie
            cookies_dict = parse_cookies_from_file("cookies.txt")

            if not cookies_dict:
                logger.warning(f"[任务 {task_id}] 没有找到有效的 Cookie")
                raise ValueError("Cookie 文件不存在或格式不正确。请将导出的 cookies.txt 放在项目根目录。")

            path = PornHubSeleniumParser(cookies_dict).parse_and_download(url, task_id)
        else:
            logger.info(f"[任务 {task_id}] 使用通用下载方案")
            path = generic_download(url, task_id)

        tasks_db[task_id].update({
            "status": "finished",
            "file_path": path,
            "filename": os.path.basename(path)
        })
        logger.info(f"[任务 {task_id}] 完成")
    except Exception as e:
        logger.error(f"[任务 {task_id}] 执行失败: {e}")
        tasks_db[task_id].update({"status": "error", "error": str(e)})


# ==========================================
# FastAPI 路由层
# ==========================================
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/", response_class=HTMLResponse)
async def index():
    return """
    <!DOCTYPE html>
    <html lang="zh">
    <head><meta charset="UTF-8"><title>SaveAny - 强效无损版</title></head>
    <body style="font-family:sans-serif; background:#f0f2f5; display:flex; justify-content:center; padding-top:100px;">
        <div style="background:white; padding:40px; border-radius:24px; box-shadow:0 12px 30px rgba(0,0,0,0.1); width:400px; text-align:center;">
            <h2 style="color:#1a1a1a;">🎬 SaveAny Pro</h2>
            <p style="color:#666; font-size:13px;">免登录 | 无水印 | 高清解析</p>
            <p style="color:#999; font-size:12px;">支持: 抖音 | YouTube | PornHub | 其他平台</p>
            <input id="url" style="width:100%; padding:15px; border:2px solid #eee; border-radius:12px; margin:20px 0; box-sizing:border-box;" placeholder="粘贴视频链接...">
            <button id="btn" style="width:100%; padding:15px; background:#007AFF; color:white; border:none; border-radius:12px; cursor:pointer; font-weight:600;">立即解析下载</button>
            <div id="msg" style="margin-top:20px; color:#888; font-size:14px;"></div>
            <div id="res"></div>
        </div>
        <script>
            const btn = document.getElementById('btn');
            const msg = document.getElementById('msg');
            btn.onclick = async () => {
                const url = document.getElementById('url').value.trim();
                if(!url) return;
                btn.disabled = true; msg.innerText = '正在处理...';
                try {
                    const res = await fetch(`/api/start?url=${encodeURIComponent(url)}`);
                    const { task_id } = await res.json();
                    const timer = setInterval(async () => {
                        const ck = await fetch(`/api/progress/${task_id}`);
                        const d = await ck.json();
                        if(d.status === 'finished') {
                            clearInterval(timer); btn.disabled = false; msg.innerText = '解析成功！';
                            document.getElementById('res').innerHTML = `<a href="/api/get/${task_id}" style="display:block; margin-top:20px; padding:15px; background:#34C759; color:white; text-decoration:none; border-radius:12px;" download>点击下载 MP4 视频</a>`;
                        } else if(d.status === 'error') {
                            clearInterval(timer); btn.disabled = false; msg.innerText = '错误: ' + d.error;
                        } else {
                            msg.innerText = '正在处理中...';
                        }
                    }, 2000);
                } catch(e) { btn.disabled = false; msg.innerText = '服务连接失败'; }
            }
        </script>
    </body>
    </html>
    """


@app.get("/api/start")
async def api_start(url: str, bg: BackgroundTasks):
    tid = str(uuid.uuid4())
    tasks_db[tid] = {"status": "loading"}
    bg.add_task(download_worker, url, tid)
    return {"task_id": tid}


@app.get("/api/progress/{task_id}")
async def api_progress(task_id: str):
    return tasks_db.get(task_id, {"status": "error", "error": "任务过期"})


@app.get("/api/get/{task_id}")
async def api_get(task_id: str):
    task = tasks_db.get(task_id)
    if task and task.get("file_path"):
        return FileResponse(task["file_path"], filename=task.get("filename", "video.mp4"))
    raise HTTPException(404)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)