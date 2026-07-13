"""共享模型和跨模块常量。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


APP_NAME = "LANFileServer"
APP_DIR = Path.home() / ".lan_file_server"
INTERNAL_ITEM_MIME = "application/x-lanfileserver-item-id"
THEME_SETTING_KEY = "appearance/theme"
THEME_SYSTEM = "system"
THEME_LIGHT = "light"
THEME_DARK = "dark"
THEME_OPTIONS = (
    (THEME_SYSTEM, "跟随系统"),
    (THEME_LIGHT, "白天模式"),
    (THEME_DARK, "黑夜模式"),
)
UPLOAD_DIR_NAME = "Uploads"
UPLOAD_CHUNK_SIZE = 1024 * 1024
UPLOAD_FREE_SPACE_RESERVE = 32 * 1024 * 1024
PREVIEW_MAX_BYTES = 2 * 1024 * 1024
CHAT_MAX_BODY_BYTES = 16 * 1024
CHAT_MAX_MESSAGES = 200

HELP_TEXT = """
每个文件 / 文件夹都可以独立选择模式。

临时模式（项目内勾选）

适合：
- 临时传文件
- 不想安装 Nginx
- 用完即停

Nginx 模式（项目内不勾选）

适合：
- 长期运行和多人访问
- 大文件、断点续传和视频拖动
- 让文件字节由 Nginx 直接传输

说明：浏览器页面和上传控制仍由本机 Python 后端处理，文件预览与下载由 Nginx 直接输出。
""".strip()

STATUS_HELP_TEXT = """
HTTP 状态码

200：访问成功。
206：分段下载成功，常见于断点续传或视频拖动。
304：浏览器使用缓存。
400：请求格式不正确。
403：没有权限访问该路径。
404：文件或路径不存在。
413：请求超过可接受范围。
500：服务器内部发生错误。
507：磁盘剩余空间不足。
""".strip()


@dataclass
class ShareItem:
    """描述一个可独立启停的共享项目。"""

    item_id: int
    path: Path
    temporary: bool = True
    upload_allowed: bool = False
    running: bool = False

    @property
    def name(self) -> str:
        return self.path.name or str(self.path)

    @property
    def kind(self) -> str:
        return "文件夹" if self.path.is_dir() else "文件"
