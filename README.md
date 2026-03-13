```Plaintext
E:.
|   .gitignore           # Git 忽略配置
|   cookies.txt          # (本地) YouTube 授权 Cookie
|   main.py              # FastAPI 后端逻辑与前端模板
|   README.md            # 项目说明文档
|   requirements.txt     # 项目依赖清单
|   test_main.http       # 接口测试文件 (用于 REST Client)
```

## 🛠️ 快速开始

### 1. 环境依赖

确保你的系统已安装 **FFmpeg**（用于合并音视频流）：

- **Ubuntu/Debian**: `sudo apt install ffmpeg`
- **Windows**:  并添加至环境变量 PATH。

### 2. 安装 Python环境 和 依赖

windows系统建议安装anaconda，在虚拟环境中执行：

```shell
conda create -n venv_downloader python=3.10 -y && conda activate venv_downloader && pip install fastapi uvicorn yt-dlp "numpy<2"
```

### 3. 配置 Cookie (可选)

为了下载 1080P+ 或受限视频，请将浏览器的 Cookie 导出为 `cookies.txt` (Netscape 格式) 并放入项目根目录。

通过**chrome浏览器插件**：Get cookies.txt LOCALLY

![chrome浏览器插件](https://cdn.jsdelivr.net/gh/pinkfufu/pinkfufu-img/img/image-20260310145419486.png)

导出Cookies：

![导出Cookie](https://cdn.jsdelivr.net/gh/pinkfufu/pinkfufu-img/img/image-20260310145929941.png)

利用插件导出Cookie后，重命名为`cookies.txt`

![重命名](https://cdn.jsdelivr.net/gh/pinkfufu/pinkfufu-img/img/image-20260310150039229.png)

![](https://cdn.jsdelivr.net/gh/pinkfufu/pinkfufu-img/img/image-20260310150708783.png)

### 4. 启动服务

或者：

```shell
uvicorn main:app --host 0.0.0.0 --port 8000
```

![启动](https://cdn.jsdelivr.net/gh/pinkfufu/pinkfufu-img/img/image-20260310150859958.png)

访问：`http://localhost:8000` 即可开始使用。

## 🤝 贡献指南

1. Fork 本项目。
2. 创建特性分支：`git checkout -b feature/AmazingFeature`。
3. 提交改动：`git commit -m 'Add some AmazingFeature'`。
4. 推送到分支：`git push origin feature/AmazingFeature`。
5. 提交 Pull Request。

------

**ZhangYao** - *Initial work* - 