"""Python 临时服务和 Nginx 静态直出服务。"""

from __future__ import annotations

import errno
import html
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.parse
from datetime import datetime
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Optional

from .models import APP_DIR, CHAT_MAX_MESSAGES, ShareItem
from .network import now_text
from .web import ShareHandler, item_allows_upload, page


def client_ip_from_handler(handler: ShareHandler) -> str:
    return handler.headers.get("X-Real-IP") or handler.client_address[0]


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


class PythonShareServer:
    """在独立线程中运行浏览器控制面和临时文件服务。"""

    def __init__(self, on_access: Callable[[dict[str, str]], None], record_requests: bool = True) -> None:
        self.on_access = on_access
        self.record_requests = record_requests
        self.httpd: Optional[ThreadingHTTPServer] = None
        self.thread: Optional[threading.Thread] = None
        self.items: list[ShareItem] = []
        self.items_by_id: dict[int, ShareItem] = {}
        self.chat_lock = threading.Lock()
        self.chat_messages: dict[int, list[dict[str, object]]] = {}
        self.chat_next_id = 1

    def refresh_items(self, items: list[ShareItem]) -> None:
        self.items = list(items)
        self.items_by_id = {item.item_id: item for item in items}

    def start(self, items: list[ShareItem], port: int, host: str = "0.0.0.0") -> int:
        self.refresh_items(items)
        try:
            self.httpd = ReusableThreadingHTTPServer((host, port), ShareHandler)
        except OSError as error:
            if error.errno in (errno.EADDRINUSE, 48, 98, 10048):
                raise RuntimeError(f"端口 {port} 已被占用。请换一个端口。") from error
            raise
        self.httpd.manager = self
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        return int(self.httpd.server_address[1])

    def stop(self) -> None:
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2)
        self.thread = None

    def chat_since(self, item_id: int, after: int = 0) -> list[dict[str, object]]:
        with self.chat_lock:
            return [dict(message) for message in self.chat_messages.get(item_id, []) if int(message["id"]) > after]

    def add_chat(self, item_id: int, nickname: str, message: str, client_ip: str) -> dict[str, object]:
        with self.chat_lock:
            entry: dict[str, object] = {
                "id": self.chat_next_id,
                "nickname": nickname,
                "message": message,
                "timestamp": time.time(),
                "ip": client_ip,
            }
            self.chat_next_id += 1
            messages = self.chat_messages.setdefault(item_id, [])
            messages.append(entry)
            del messages[:-CHAT_MAX_MESSAGES]
            return dict(entry)

    def record(self, handler: ShareHandler, code: str, size: str) -> None:
        parsed = urllib.parse.urlsplit(handler.path)
        match = re.match(r"^/items/(\d+)", parsed.path)
        item = self.items_by_id.get(int(match.group(1))) if match else None
        self.on_access({
            "time": now_text(), "ip": client_ip_from_handler(handler), "engine": "Python",
            "method": handler.command, "status": code, "item": item.name if item else "",
            "path": urllib.parse.unquote(parsed.path), "size": size,
        })

    def record_upload(self, handler: ShareHandler, code: str, item: ShareItem, filename: str, size: str, path: str) -> None:
        self.on_access({
            "time": now_text(), "ip": client_ip_from_handler(handler), "engine": "Python",
            "method": "POST", "status": code, "item": item.name,
            "path": path if code == "201" else f"上传失败：{filename}", "size": size,
        })


class NginxShareServer:
    """以前置 Nginx 直出非临时项目的原始文件字节。"""

    def __init__(self) -> None:
        self.process: Optional[subprocess.Popen] = None
        self.runtime_dir: Optional[Path] = None
        self.access_log: Optional[Path] = None

    def start(self, items: list[ShareItem], port: int, python_backend_port: Optional[int] = None) -> Path:
        nginx = self.find_nginx()
        if not nginx:
            raise RuntimeError("Nginx 尚未准备完成。")
        if python_backend_port is None:
            raise RuntimeError("Nginx 模式需要浏览器控制面后端。")
        self.runtime_dir = APP_DIR / "nginx" / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        logs_dir = self.runtime_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        self.access_log = logs_dir / "access.log"
        config = self.runtime_dir / "nginx.conf"
        config.write_text(self.config_text(items, port, self.access_log, logs_dir / "error.log", python_backend_port, self.find_mime_types(nginx)), encoding="utf-8")
        self.process = subprocess.Popen([nginx, "-p", str(self.runtime_dir), "-c", str(config)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(.8)
        if self.process.poll() is not None:
            detail = self.process.stderr.read() if self.process.stderr else ""
            raise RuntimeError(detail.strip() or "Nginx 启动失败。")
        return self.access_log

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.process = None
        if self.runtime_dir:
            self.terminate_pid_file(self.runtime_dir / "nginx.pid")

    @staticmethod
    def process_command(pid: int) -> str:
        if sys.platform.startswith("win"):
            return ""
        return subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True, check=False).stdout.strip()

    @classmethod
    def terminate_pid_file(cls, pid_path: Path) -> None:
        try:
            pid = int(pid_path.read_text().strip())
        except (OSError, ValueError):
            return
        command = cls.process_command(pid)
        if command and str(APP_DIR / "nginx") not in command:
            return
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            return

    @classmethod
    def cleanup_stale_instances(cls) -> None:
        if sys.platform.startswith("win"):
            return
        root = APP_DIR / "nginx"
        if root.exists():
            for pid_path in root.glob("*/nginx.pid"):
                cls.terminate_pid_file(pid_path)

    @staticmethod
    def find_nginx() -> Optional[str]:
        candidates = [
            shutil.which("nginx"), "/opt/homebrew/bin/nginx", "/opt/homebrew/opt/nginx/bin/nginx",
            "/usr/local/bin/nginx", "/usr/local/opt/nginx/bin/nginx", "/usr/sbin/nginx",
            r"C:\nginx\nginx.exe", r"C:\ProgramData\chocolatey\bin\nginx.exe",
        ]
        for candidate in candidates:
            if candidate and Path(candidate).is_file():
                return str(candidate)
        if sys.platform.startswith("win"):
            root = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
            if root.exists():
                for candidate in root.glob("nginx.nginx_*/**/nginx.exe"):
                    return str(candidate)
        return None

    @staticmethod
    def find_brew() -> Optional[str]:
        for candidate in (shutil.which("brew"), "/opt/homebrew/bin/brew", "/usr/local/bin/brew"):
            if candidate and Path(candidate).is_file():
                return str(candidate)
        return None

    @classmethod
    def install_nginx(cls) -> str:
        existing = cls.find_nginx()
        if existing:
            return existing
        if sys.platform == "darwin":
            brew = cls.find_brew()
            if not brew:
                raise RuntimeError("未检测到 Homebrew，可以先使用临时模式。")
            command = [brew, "install", "nginx"]
        elif sys.platform.startswith("win") and shutil.which("winget"):
            command = ["winget", "install", "--id", "nginx.nginx", "--exact", "--silent", "--accept-source-agreements", "--accept-package-agreements"]
        elif sys.platform.startswith("win") and shutil.which("choco"):
            command = ["choco", "install", "nginx", "-y"]
        else:
            raise RuntimeError("当前系统无法自动准备 Nginx，可以先使用临时模式。")
        env = os.environ.copy()
        env["HOMEBREW_NO_AUTO_UPDATE"] = "1"
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, env=env)
        if result.returncode:
            raise RuntimeError((result.stderr or result.stdout)[-1600:])
        installed = cls.find_nginx()
        if not installed:
            raise RuntimeError("Nginx 已安装，但暂时没有找到可执行文件。")
        return installed

    @staticmethod
    def find_mime_types(nginx_path: str) -> Optional[Path]:
        executable = Path(nginx_path).resolve()
        for candidate in (executable.parent.parent / "conf/mime.types", executable.parent / "conf/mime.types", Path("/opt/homebrew/etc/nginx/mime.types"), Path("/usr/local/etc/nginx/mime.types"), Path("/etc/nginx/mime.types"), Path(r"C:\nginx\conf\mime.types")):
            if candidate.is_file():
                return candidate
        return None

    @staticmethod
    def nginx_path(path: Path, trailing_slash: bool = False) -> str:
        value = str(path.resolve()).replace("\\", "/")
        if trailing_slash and not value.endswith("/"):
            value += "/"
        return value.replace('"', '\\"')

    def config_text(self, items: list[ShareItem], port: int, access_log: Path, error_log: Path, backend_port: int, mime_types: Optional[Path] = None) -> str:
        locations: list[str] = []
        for item in items:
            prefix = f"/items/{item.item_id}"
            if not item.temporary:
                if item.path.is_dir():
                    locations.append(f'''location ^~ {prefix}/__raw/ {{
            alias "{self.nginx_path(item.path, True)}";
            disable_symlinks on;
            add_header Accept-Ranges bytes always;
            add_header Content-Disposition $jobs_content_disposition always;
        }}''')
                else:
                    locations.append(f'''location = {prefix}/__raw {{
            alias "{self.nginx_path(item.path)}";
            add_header Accept-Ranges bytes always;
            add_header Content-Disposition $jobs_content_disposition always;
        }}''')
            locations.append(f'''location {prefix} {{
            proxy_pass http://127.0.0.1:{backend_port};
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header Range $http_range;
            proxy_request_buffering off;
            proxy_buffering off;
            client_max_body_size 0;
        }}''')
        mime = f'include "{self.nginx_path(mime_types)}";' if mime_types else ""
        return f'''daemon off;
worker_processes auto;
pid "{self.nginx_path(self.runtime_dir / "nginx.pid")}";
events {{ worker_connections 2048; }}
http {{
    {mime}
    default_type application/octet-stream;
    sendfile on;
    tcp_nopush on;
    keepalive_timeout 65;
    map $arg_download $jobs_content_disposition {{ default "inline"; 1 "attachment"; }}
    log_format jobs_main '$remote_addr|$time_local|$request|$status|$body_bytes_sent|$http_user_agent';
    access_log "{self.nginx_path(access_log)}" jobs_main;
    error_log "{self.nginx_path(error_log)}" warn;
    server {{
        listen {port};
        charset utf-8;
        location = /favicon.ico {{ return 204; }}
        {''.join(locations)}
        location / {{
            proxy_pass http://127.0.0.1:{backend_port};
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_buffering off;
        }}
    }}
}}'''

    @staticmethod
    def index_html(items: list[ShareItem]) -> str:
        rows = "".join(f"<li>{html.escape(item.name)}</li>" for item in items)
        return page("LANFileServer", f"<ul>{rows}</ul>").decode()
