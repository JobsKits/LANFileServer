#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LANFileServer

局域网文件服务器：
- 临时模式：内置 Python HTTP 服务，适合临时下载。
- Nginx 模式：使用本机 Nginx，适合长期运行、多用户访问和目录浏览。
"""

from __future__ import annotations

import errno
import html
import ipaddress
import json
import mimetypes
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Optional
from zoneinfo import ZoneInfo

try:
    from PySide6.QtCore import QEasingCurve, QEvent, QFileInfo, QMimeData, QPoint, QPropertyAnimation, QSize, Qt, QTimer, QUrl, Signal
    from PySide6.QtGui import QAction, QCloseEvent, QCursor, QDesktopServices, QDrag, QResizeEvent
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QFileDialog,
        QGraphicsOpacityEffect,
        QFileIconProvider,
        QFrame,
        QHBoxLayout,
        QHeaderView,
        QLabel,
        QMainWindow,
        QMenu,
        QMessageBox,
        QPushButton,
        QScrollArea,
        QSizePolicy,
        QSpinBox,
        QSplitter,
        QTableWidget,
        QTableWidgetItem,
        QToolButton,
        QVBoxLayout,
        QWidget,
    )
except ImportError as error:
    print("缺少 PySide6，请双击启动脚本自动安装依赖，或执行：python3 -m pip install -r requirements.txt")
    print(error)
    sys.exit(1)


APP_NAME = "LANFileServer"
APP_DIR = Path.home() / ".lan_file_server"
INTERNAL_ITEM_MIME = "application/x-lanfileserver-item-id"
UPLOAD_DIR_NAME = "Uploads"
UPLOAD_MAX_BYTES = 512 * 1024 * 1024
UPLOAD_CHUNK_SIZE = 1024 * 1024
PREVIEW_MAX_BYTES = 2 * 1024 * 1024
HELP_TEXT = """
每个文件 / 文件夹都可以独立选择模式。

临时模式（项目内勾选）

等价于：
cd /Users/jobs/Desktop/share
python3 -m http.server 8080

适合：
- 临时传一个文件
- 少量设备访问
- 不想安装 Nginx
- 用完即停

Nginx 模式（项目内不勾选）

适合 Nginx 的情况：
- 长期运行
- 多人访问
- 想要固定端口
- 想要目录浏览
- 想配置账号密码
- 想限制下载速度 / 访问权限
- 想做静态网站或局域网资源站
- 想反向代理接口
""".strip()
STATUS_HELP_TEXT = """
HTTP 状态码

200：访问成功，文件或目录已正常返回。
206：分段下载成功，常见于断点续传。
304：浏览器直接使用缓存，没有重复下载。
400：请求格式不正确。
403：没有权限访问该路径。
404：请求的文件或路径不存在。
500：服务器内部发生错误。
""".strip()
TEXT_FILE_EXTENSIONS = {
    ".bat",
    ".c",
    ".command",
    ".conf",
    ".cpp",
    ".css",
    ".csv",
    ".dart",
    ".h",
    ".hpp",
    ".html",
    ".ini",
    ".java",
    ".js",
    ".json",
    ".log",
    ".m",
    ".md",
    ".mm",
    ".py",
    ".rb",
    ".sh",
    ".swift",
    ".toml",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}


@dataclass
class ShareItem:
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


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def current_time_text() -> str:
    weekday_names = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    local_time = datetime.now().astimezone()
    zone_name = local_time.tzname() or str(local_time.tzinfo)
    try:
        local_time = datetime.now(ZoneInfo("Asia/Shanghai"))
        zone_name = "Asia/Shanghai"
    except Exception:
        pass
    weekday = weekday_names[local_time.weekday()]
    return f"{local_time.year}年{local_time.month}月{local_time.day}日{local_time.hour}时{local_time.minute}分{local_time.second}秒，{weekday}，时区：{zone_name}"


def get_lan_ips() -> list[str]:
    ips: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                ips.add(ip)
    except OSError:
        pass
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        if not ip.startswith("127."):
            ips.add(ip)
        sock.close()
    except OSError:
        pass
    sorted_ips = sorted(ips, key=lan_ip_sort_key)
    usable_ips = [ip for ip in sorted_ips if not is_link_local_ip(ip)]
    return usable_ips or sorted_ips or ["127.0.0.1"]


def is_link_local_ip(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip).is_link_local
    except ValueError:
        return False


def lan_ip_sort_key(ip: str) -> tuple[int, int]:
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return (9, 0)
    value = int(address)
    if address.is_loopback:
        return (8, value)
    if address.is_link_local:
        return (6, value)
    if address.is_private:
        return (0, value)
    return (4, value)


def compact_location_parts(*values: object) -> str:
    parts: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in parts:
            parts.append(text)
    return " / ".join(parts)


def read_json_url(url: str) -> dict[str, object]:
    request = urllib.request.Request(url, headers={"User-Agent": f"{APP_NAME}/1.0"})
    with urllib.request.urlopen(request, timeout=3) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def public_location_from_data(data: dict[str, object]) -> str:
    return compact_location_parts(
        data.get("country_name") or data.get("country"),
        data.get("regionName") or data.get("region"),
        data.get("city"),
        data.get("district"),
    )


def lookup_public_ip_location(ip: str) -> str:
    for url in (
        f"http://ip-api.com/json/{urllib.parse.quote(ip)}?lang=zh-CN&fields=status,message,country,regionName,city,district,query",
        f"https://ipwho.is/{urllib.parse.quote(ip)}?lang=zh-CN",
        f"https://ipapi.co/{urllib.parse.quote(ip)}/json/",
    ):
        try:
            data = read_json_url(url)
            if data.get("success") is False or data.get("status") == "fail":
                continue
            location = public_location_from_data(data)
            if location:
                return location
        except Exception:
            continue
    return "位置获取失败"


def get_plain_public_ip() -> str:
    for url in ("https://api.ipify.org", "https://ifconfig.me/ip"):
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                ip = response.read().decode("utf-8", errors="replace").strip()
            if re.fullmatch(r"[0-9a-fA-F:.]+", ip):
                return ip
        except Exception:
            continue
    return ""


def get_public_ip_info() -> dict[str, str]:
    ip = get_plain_public_ip()
    if ip:
        return {"ip": ip, "location": lookup_public_ip_location(ip)}
    for url in ("https://ipwho.is/", "https://ipapi.co/json/"):
        try:
            data = read_json_url(url)
            if data.get("success") is False:
                continue
            ip = str(data.get("ip") or "").strip()
            if re.fullmatch(r"[0-9a-fA-F:.]+", ip):
                return {"ip": ip, "location": public_location_from_data(data) or "位置获取失败"}
        except Exception:
            continue
    return {"ip": "获取失败", "location": "位置获取失败"}


def page(title: str, body: str) -> bytes:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" href="data:,">
  <title>{html.escape(title)}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 30px; color: #1f2937; }}
    h1 {{ font-size: 24px; }}
    a {{ color: #0369a1; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 16px; }}
    th, td {{ padding: 9px 8px; border-bottom: 1px solid #e5e7eb; text-align: left; }}
    th {{ background: #f8fafc; }}
    .hint {{ color: #64748b; }}
    .actions {{ width: 138px; white-space: nowrap; }}
    .action-link {{ display: inline-block; margin-right: 10px; font-size: 13px; }}
    .primary-actions {{ display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin: 16px 0; }}
    .primary-actions a {{ padding: 7px 14px; border: 1px solid #cbd5e1; background: #f8fafc; }}
    .preview-box {{ margin-top: 16px; }}
    .preview-box img, .preview-box video {{ max-width: 100%; height: auto; }}
    .preview-box iframe {{ width: 100%; height: 78vh; border: 1px solid #e5e7eb; }}
    pre {{ white-space: pre-wrap; word-break: break-word; padding: 14px; background: #0f172a; color: #e2e8f0; overflow: auto; }}
    .upload-panel {{ margin: 18px 0 8px; }}
    .upload-drop {{ min-height: 150px; padding: 18px; border: 2px dashed #94a3b8; background: #f8fafc; display: flex; align-items: center; justify-content: center; text-align: center; }}
    .upload-drop.dragging {{ border-color: #0369a1; background: #e0f2fe; }}
    .upload-panel form {{ display: flex; gap: 10px; align-items: center; justify-content: center; flex-wrap: wrap; margin: 10px 0; }}
    .upload-panel button {{ padding: 6px 14px; cursor: pointer; }}
    .upload-panel button:disabled {{ cursor: not-allowed; opacity: 0.5; }}
    .upload-list {{ margin: 8px auto 0; padding-left: 20px; max-width: 720px; max-height: 120px; overflow: auto; text-align: left; }}
    .upload-status {{ margin: 8px 0 0; color: #475569; }}
  </style>
  <script>
    document.addEventListener("DOMContentLoaded", () => {{
      document.querySelectorAll("[data-upload-panel]").forEach(setupUploadPanel);
    }});

    function setupUploadPanel(panel) {{
      const form = panel.querySelector("[data-upload-url]");
      const dropZone = panel.querySelector("[data-upload-drop]");
      const fileInput = panel.querySelector("[data-file-input]");
      const folderInput = panel.querySelector("[data-folder-input]");
      const chooseFiles = panel.querySelector("[data-choose-files]");
      const chooseFolder = panel.querySelector("[data-choose-folder]");
      const uploadButton = panel.querySelector("[data-upload-button]");
      const status = panel.querySelector(".upload-status");
      const list = panel.querySelector(".upload-list");
      let pendingFiles = [];

      const uploadPath = (file) => file.uploadPath || file.webkitRelativePath || file.name;
      const setStatus = (text) => {{ status.textContent = text; }};
      const refreshList = () => {{
        uploadButton.disabled = pendingFiles.length === 0;
        list.innerHTML = "";
        pendingFiles.slice(0, 60).forEach((file) => {{
          const item = document.createElement("li");
          item.textContent = uploadPath(file);
          list.appendChild(item);
        }});
        if (pendingFiles.length > 60) {{
          const item = document.createElement("li");
          item.textContent = `另外还有 ${{pendingFiles.length - 60}} 个文件...`;
          list.appendChild(item);
        }}
      }};
      const addFiles = (files) => {{
        pendingFiles = pendingFiles.concat(files.filter(Boolean));
        setStatus(pendingFiles.length ? `已选择 ${{pendingFiles.length}} 个文件，确认后再上传。` : "没有可上传的文件。");
        refreshList();
      }};
      const uploadPending = async () => {{
        if (!pendingFiles.length) {{
          setStatus("请先选择文件或文件夹。");
          return;
        }}
        uploadButton.disabled = true;
        try {{
          for (const file of pendingFiles) {{
            const path = uploadPath(file);
            setStatus(`正在上传：${{path}}`);
            const url = `${{form.dataset.uploadUrl}}?path=${{encodeURIComponent(path)}}`;
            const response = await fetch(url, {{
              method: "POST",
              headers: {{ "Content-Type": file.type || "application/octet-stream" }},
              body: file
            }});
            if (!response.ok) {{
              const text = await response.text();
              throw new Error(text || `上传失败：${{response.status}}`);
            }}
          }}
          setStatus("上传完成。");
          pendingFiles = [];
          refreshList();
          window.location.href = form.dataset.nextUrl;
        }} catch (error) {{
          setStatus(error.message || "上传失败。");
          refreshList();
        }}
      }};

      chooseFiles.addEventListener("click", () => fileInput.click());
      chooseFolder.addEventListener("click", () => folderInput.click());
      fileInput.addEventListener("change", () => {{
        addFiles(Array.from(fileInput.files));
        fileInput.value = "";
      }});
      folderInput.addEventListener("change", () => {{
        addFiles(Array.from(folderInput.files));
        folderInput.value = "";
      }});
      form.addEventListener("submit", (event) => {{
        event.preventDefault();
        uploadPending();
      }});
      ["dragenter", "dragover"].forEach((type) => {{
        dropZone.addEventListener(type, (event) => {{
          event.preventDefault();
          dropZone.classList.add("dragging");
        }});
      }});
      ["dragleave", "drop"].forEach((type) => {{
        dropZone.addEventListener(type, () => dropZone.classList.remove("dragging"));
      }});
      dropZone.addEventListener("drop", async (event) => {{
        event.preventDefault();
        const files = await collectDroppedFiles(event.dataTransfer);
        addFiles(files);
        if (files.length && window.confirm(`已拖入 ${{files.length}} 个文件，是否现在上传？`)) {{
          uploadPending();
        }}
      }});
      refreshList();
    }}

    async function collectDroppedFiles(dataTransfer) {{
      const items = Array.from(dataTransfer.items || []);
      if (!items.length) return Array.from(dataTransfer.files || []);
      const files = [];
      for (const item of items) {{
        const entry = item.webkitGetAsEntry ? item.webkitGetAsEntry() : null;
        if (entry) {{
          files.push(...await traverseEntry(entry, ""));
        }} else {{
          const file = item.getAsFile && item.getAsFile();
          if (file) files.push(file);
        }}
      }}
      return files;
    }}

    function traverseEntry(entry, prefix) {{
      return new Promise((resolve) => {{
        const entryPath = `${{prefix}}${{entry.name}}`;
        if (entry.isFile) {{
          entry.file((file) => {{
            file.uploadPath = entryPath;
            resolve([file]);
          }}, () => resolve([]));
          return;
        }}
        if (!entry.isDirectory) {{
          resolve([]);
          return;
        }}
        const reader = entry.createReader();
        const results = [];
        const readBatch = () => {{
          reader.readEntries(async (entries) => {{
            if (!entries.length) {{
              resolve(results);
              return;
            }}
            for (const child of entries) {{
              results.push(...await traverseEntry(child, `${{entryPath}}/`));
            }}
            readBatch();
          }}, () => resolve(results));
        }};
        readBatch();
      }});
    }}
  </script>
</head>
<body>{body}</body>
</html>""".encode("utf-8")


def safe_child(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def file_content_type(file_path: Path) -> str:
    content_type = mimetypes.guess_type(file_path.name)[0]
    if not content_type and file_path.suffix.lower() in TEXT_FILE_EXTENSIONS:
        content_type = "text/plain"
    if content_type and content_type.startswith("text/") and "charset=" not in content_type.lower():
        return f"{content_type}; charset=utf-8"
    return content_type or "application/octet-stream"


def content_disposition(disposition: str, filename: str) -> str:
    fallback = re.sub(r"[^A-Za-z0-9._ -]+", "_", filename).strip() or "download"
    fallback = fallback.replace("\\", "_").replace('"', "'")
    encoded = urllib.parse.quote(filename)
    return f'{disposition}; filename="{fallback}"; filename*=UTF-8\'\'{encoded}'


def item_allows_upload(item: ShareItem) -> bool:
    return item.upload_allowed and item.path.is_dir()


def item_uses_python_backend(item: ShareItem) -> bool:
    return True


def client_ip_from_handler(handler: BaseHTTPRequestHandler) -> str:
    return handler.headers.get("X-Real-IP") or handler.client_address[0]


def human_size(size: int) -> str:
    value = float(size)
    for unit in ["B", "KB", "MB", "GB"]:
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"


def sanitize_upload_filename(filename: str) -> str:
    name = urllib.parse.unquote(filename or "").strip()
    name = re.split(r"[\\/]+", name)[-1]
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", name).strip()
    if name in {"", ".", ".."}:
        return "upload.bin"
    return name[:180]


def sanitize_upload_path_part(part: str) -> str:
    name = urllib.parse.unquote(part or "").strip()
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", name).strip()
    if name in {"", ".", ".."}:
        return ""
    return name[:120]


def sanitize_upload_relative_path(value: str) -> Path:
    raw_parts = urllib.parse.unquote(value or "").replace("\\", "/").split("/")
    parts = [part for part in (sanitize_upload_path_part(raw_part) for raw_part in raw_parts) if part]
    if not parts:
        return Path("upload.bin")
    return Path(*parts)


def unique_upload_path(upload_dir: Path, filename: str) -> Path:
    target = upload_dir / filename
    if not target.exists():
        return target
    stem = target.stem or "upload"
    suffix = target.suffix
    for index in range(1, 10000):
        candidate = upload_dir / f"{stem} ({index}){suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError("同名文件过多，无法生成安全文件名。")


def quote_path(path: Path) -> str:
    return "/".join(urllib.parse.quote(part) for part in path.parts)


def is_text_preview(file_path: Path, content_type: str) -> bool:
    return content_type.startswith("text/") or file_path.suffix.lower() in TEXT_FILE_EXTENSIONS


def archive_download_name(source: Path) -> str:
    name = sanitize_upload_filename(source.name or "download")
    return f"{name}.zip"


def build_path_archive(source: Path) -> Path:
    temp_file = tempfile.NamedTemporaryFile("wb", delete=False, suffix=".zip")
    temp_path = Path(temp_file.name)
    temp_file.close()
    try:
        with zipfile.ZipFile(temp_path, "w", zipfile.ZIP_DEFLATED) as archive:
            if source.is_symlink():
                raise RuntimeError("不打包符号链接。")
            if source.is_file():
                archive.write(source, sanitize_upload_filename(source.name))
            else:
                root_name = sanitize_upload_filename(source.name or "folder")
                archive.writestr(f"{root_name}/", b"")
                for child in sorted(source.rglob("*"), key=lambda path: str(path).lower()):
                    if child.is_symlink() or not safe_child(child, source):
                        continue
                    relative = child.relative_to(source)
                    archive_name = str(Path(root_name) / relative).replace("\\", "/")
                    if child.is_dir():
                        archive.write(child, archive_name.rstrip("/") + "/")
                    elif child.is_file():
                        archive.write(child, archive_name)
    except Exception:
        try:
            temp_path.unlink()
        except OSError:
            pass
        raise
    return temp_path


class ShareHandler(BaseHTTPRequestHandler):
    server_version = "LANFileServerPython/1.0"

    def do_GET(self) -> None:
        self.serve_request(True)

    def do_HEAD(self) -> None:
        self.serve_request(False)

    def do_POST(self) -> None:
        self.handle_upload()

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        parsed = urllib.parse.urlsplit(self.path)
        if re.match(r"^/items/\d+/__upload$", parsed.path):
            return
        manager = getattr(self.server, "manager", None)
        if manager and manager.record_requests:
            manager.record(self, str(code), str(size))

    def send_bytes(self, status: int, body: bytes, content_type: str, send_body: bool) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if send_body:
            self.wfile.write(body)

    def send_json(self, status: int, payload: dict[str, object], headers: Optional[dict[str, str]] = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def serve_request(self, send_body: bool) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        if parsed.path in ("", "/"):
            self.send_index(send_body)
            return
        match = re.match(r"^/items/(\d+)(?:/(.*))?$", parsed.path)
        if not match:
            self.send_error(404, "Not Found")
            return
        manager = getattr(self.server, "manager", None)
        item = manager.items_by_id.get(int(match.group(1))) if manager else None
        if not item or not item.path.exists():
            self.send_error(404, "Share item not found")
            return
        extra = match.group(2)
        if item.path.is_file():
            if extra == "__preview":
                self.send_file(item.path, send_body, False)
            elif extra == "__download":
                self.send_path_archive(item.path, send_body)
            elif extra:
                self.send_error(404, "Not Found")
            else:
                self.send_file_page(item, item.path, "", send_body)
            return
        if extra is None:
            self.send_response(302)
            self.send_header("Location", f"/items/{item.item_id}/")
            self.end_headers()
            return
        parts = [part for part in urllib.parse.unquote(extra).split("/") if part]
        action = parts[-1] if parts and parts[-1] in {"__preview", "__download"} else ""
        target_parts = parts[:-1] if action else parts
        target = item.path.joinpath(*target_parts)
        if not safe_child(target, item.path):
            self.send_error(403, "Forbidden")
        elif action == "__preview" and target.is_file():
            self.send_file(target, send_body, False)
        elif action == "__download" and (target.is_file() or target.is_dir()):
            self.send_path_archive(target, send_body)
        elif action:
            self.send_error(404, "Not Found")
        elif target.is_dir():
            self.send_directory(item, target, parsed.path, send_body)
        elif target.is_file():
            self.send_file_page(item, target, quote_path(Path(*target_parts)), send_body)
        else:
            self.send_error(404, "Not Found")

    def upload_panel(self, item: ShareItem) -> str:
        if not item_allows_upload(item):
            return ""
        action = f"/items/{item.item_id}/__upload"
        next_url = f"/items/{item.item_id}/{urllib.parse.quote(UPLOAD_DIR_NAME)}/"
        limit = html.escape(human_size(UPLOAD_MAX_BYTES))
        return f"""
<div class="upload-panel" data-upload-panel>
  <div class="upload-drop" data-upload-drop>
    <div>
      <strong>拖入要上传的文件 / 文件夹</strong>
      <form data-upload-url="{action}" data-next-url="{next_url}">
        <input data-file-input type="file" multiple hidden>
        <input data-folder-input type="file" webkitdirectory directory multiple hidden>
        <button type="button" data-choose-files>选择文件</button>
        <button type="button" data-choose-folder>选择文件夹</button>
        <button type="submit" data-upload-button disabled>上传</button>
        <span class="hint">上传到 {html.escape(UPLOAD_DIR_NAME)}/，单文件上限 {limit}</span>
      </form>
      <ol class="upload-list"></ol>
      <p class="upload-status"></p>
    </div>
  </div>
</div>
"""

    def send_index(self, send_body: bool) -> None:
        manager = getattr(self.server, "manager", None)
        rows = []
        for item in manager.items:
            href = f"/items/{item.item_id}/" if item.path.is_dir() else f"/items/{item.item_id}"
            download_link = f"<a class=\"action-link\" href=\"/items/{item.item_id}/__download\" download>下载</a>"
            rows.append(
                f"<tr><td>{item.item_id}</td><td><a href=\"{href}\">{html.escape(item.name)}</a></td>"
                f"<td>{html.escape(item.kind)}</td><td>{download_link}</td><td>{html.escape(str(item.path))}</td></tr>"
            )
        body = (
            "<h1>LANFileServer</h1><p class=\"hint\">同一局域网设备可访问本页查看或下载文件。</p>"
            "<table><thead><tr><th>ID</th><th>名称</th><th>类型</th><th class=\"actions\">操作</th><th>本机路径</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>"
        )
        self.send_bytes(200, page("LANFileServer", body), "text/html; charset=utf-8", send_body)

    def send_directory(self, item: ShareItem, directory: Path, raw_path: str, send_body: bool) -> None:
        if not raw_path.endswith("/"):
            self.send_response(302)
            self.send_header("Location", raw_path + "/")
            self.end_headers()
            return
        try:
            children = sorted(directory.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except OSError as error:
            self.send_error(403, str(error))
            return
        rows = []
        if directory.resolve() != item.path.resolve():
            rows.append('<tr><td><a href="../">../</a></td><td>文件夹</td><td></td><td></td></tr>')
        for child in children:
            name = child.name + ("/" if child.is_dir() else "")
            href = urllib.parse.quote(child.name) + ("/" if child.is_dir() else "")
            size = "" if child.is_dir() else f"{child.stat().st_size:,} B"
            download_href = f"{href}__download" if child.is_dir() else f"{href}/__download"
            download_link = f"<a class=\"action-link\" href=\"{download_href}\" download>下载</a>"
            rows.append(
                f"<tr><td><a href=\"{href}\">{html.escape(name)}</a></td>"
                f"<td>{'文件夹' if child.is_dir() else '文件'}</td><td>{size}</td><td>{download_link}</td></tr>"
            )
        title = item.name if directory.resolve() == item.path.resolve() else f"{item.name}/{directory.resolve().relative_to(item.path.resolve())}"
        body = (
            f"<h1>{html.escape(title)}</h1>"
            "<p class=\"hint\">点击文件名直接查看，下载请点右侧操作。</p>"
            f"{self.upload_panel(item)}"
            "<table><thead><tr><th>名称</th><th>类型</th><th>大小</th><th class=\"actions\">操作</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>"
        )
        self.send_bytes(200, page(title, body), "text/html; charset=utf-8", send_body)

    def send_file_page(self, item: ShareItem, file_path: Path, relative_href: str, send_body: bool) -> None:
        try:
            stat = file_path.stat()
        except Exception as error:
            self.send_error(404, str(error))
            return
        base_url = f"/items/{item.item_id}" if not relative_href else f"/items/{item.item_id}/{relative_href}"
        preview_url = f"{base_url}/__preview"
        download_url = f"{base_url}/__download"
        content_type = file_content_type(file_path)
        title = file_path.name
        body = (
            f"<h1>{html.escape(title)}</h1>"
            f"<p class=\"hint\">类型：{html.escape(content_type)}｜大小：{html.escape(human_size(stat.st_size))}</p>"
            "<div class=\"primary-actions\">"
            f"<a href=\"{preview_url}\" target=\"_blank\" rel=\"noopener\">查看</a>"
            f"<a href=\"{download_url}\" download>下载</a>"
            "</div>"
            f"{self.file_preview_html(file_path, preview_url, content_type, stat.st_size)}"
        )
        self.send_bytes(200, page(title, body), "text/html; charset=utf-8", send_body)

    def file_preview_html(self, file_path: Path, preview_url: str, content_type: str, size: int) -> str:
        if content_type.startswith("image/"):
            return f'<div class="preview-box"><img src="{preview_url}" alt="{html.escape(file_path.name)}"></div>'
        if content_type.startswith("video/"):
            return f'<div class="preview-box"><video controls src="{preview_url}"></video></div>'
        if content_type.startswith("audio/"):
            return f'<div class="preview-box"><audio controls src="{preview_url}"></audio></div>'
        if content_type.startswith("application/pdf"):
            return f'<div class="preview-box"><iframe src="{preview_url}" title="{html.escape(file_path.name)}"></iframe></div>'
        if is_text_preview(file_path, content_type):
            if size > PREVIEW_MAX_BYTES:
                return f'<p class="hint">文本文件超过 {html.escape(human_size(PREVIEW_MAX_BYTES))}，请点“查看”单独打开。</p>'
            try:
                text = file_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return '<p class="hint">这个文件暂时无法读取预览。</p>'
            return f'<div class="preview-box"><pre>{html.escape(text)}</pre></div>'
        return '<p class="hint">这个文件类型浏览器可能不能直接预览；当前页面不会自动下载，需要下载时请点“下载”。</p>'

    def send_file(self, file_path: Path, send_body: bool, download: bool) -> None:
        try:
            stat = file_path.stat()
            disposition = "attachment" if download else "inline"
            self.send_response(200)
            self.send_header("Content-Type", file_content_type(file_path))
            self.send_header("Content-Length", str(stat.st_size))
            self.send_header("Last-Modified", self.date_time_string(stat.st_mtime))
            self.send_header("Content-Disposition", content_disposition(disposition, file_path.name))
            self.end_headers()
            if send_body:
                with file_path.open("rb") as source:
                    shutil.copyfileobj(source, self.wfile)
        except Exception as error:
            self.send_error(404, str(error))

    def send_path_archive(self, source: Path, send_body: bool) -> None:
        archive_path: Optional[Path] = None
        try:
            archive_path = build_path_archive(source)
            stat = archive_path.stat()
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(stat.st_size))
            self.send_header("Content-Disposition", content_disposition("attachment", archive_download_name(source)))
            self.end_headers()
            if send_body:
                with archive_path.open("rb") as source:
                    shutil.copyfileobj(source, self.wfile)
        except Exception as error:
            self.send_error(404, str(error))
        finally:
            if archive_path:
                try:
                    archive_path.unlink()
                except OSError:
                    pass

    def handle_upload(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        match = re.match(r"^/items/(\d+)/__upload$", parsed.path)
        if not match:
            self.send_error(404, "Not Found")
            return
        manager = getattr(self.server, "manager", None)
        item = manager.items_by_id.get(int(match.group(1))) if manager else None
        query = urllib.parse.parse_qs(parsed.query)
        relative_path = sanitize_upload_relative_path((query.get("path") or query.get("filename") or [""])[0])
        filename = str(relative_path)
        if not item or not item.path.exists():
            self.reject_upload(manager, "404", filename, "共享项目不存在。")
            return
        if not item_allows_upload(item):
            self.reject_upload(manager, "403", filename, "这个项目没有开启上传。")
            return
        length_text = self.headers.get("Content-Length", "").strip()
        if not length_text.isdigit():
            self.reject_upload(manager, "411", filename, "缺少 Content-Length。")
            return
        content_length = int(length_text)
        if content_length <= 0:
            self.reject_upload(manager, "400", filename, "不能上传空文件。")
            return
        if content_length > UPLOAD_MAX_BYTES:
            self.reject_upload(manager, "413", filename, f"单文件不能超过 {human_size(UPLOAD_MAX_BYTES)}。", str(content_length))
            return
        try:
            upload_dir, target = self.prepare_upload_target(item, relative_path)
            temp_path = self.write_upload_temp(target.parent, target.name, content_length)
            if target.exists():
                target = unique_upload_path(target.parent, target.name)
            temp_path.replace(target)
        except Exception as error:
            self.reject_upload(manager, "500", filename, str(error), str(content_length))
            return
        upload_relative_path = quote_path(target.relative_to(upload_dir))
        location = f"/items/{item.item_id}/{urllib.parse.quote(UPLOAD_DIR_NAME)}/{upload_relative_path}"
        self.send_json(201, {"ok": True, "name": str(target.relative_to(upload_dir)), "size": content_length, "path": location}, {"Location": location})
        if manager:
            manager.record_upload(self, "201", item, str(target.relative_to(upload_dir)), str(content_length), location)

    def reject_upload(
        self,
        manager: Optional["PythonShareServer"],
        status: str,
        filename: str,
        message: str,
        size: str = "0",
    ) -> None:
        self.send_json(int(status), {"ok": False, "message": message})
        if manager:
            item_match = re.match(r"^/items/(\d+)/__upload$", urllib.parse.urlsplit(self.path).path)
            item = manager.items_by_id.get(int(item_match.group(1))) if item_match else None
            manager.record_upload(self, status, item, filename, size, f"上传失败：{message}")

    def prepare_upload_dir(self, item: ShareItem) -> Path:
        upload_dir = item.path / UPLOAD_DIR_NAME
        if upload_dir.exists() and not upload_dir.is_dir():
            raise RuntimeError(f"{UPLOAD_DIR_NAME} 已存在但不是文件夹。")
        upload_dir.mkdir(parents=True, exist_ok=True)
        if not safe_child(upload_dir, item.path):
            raise RuntimeError("上传目录不在共享文件夹内。")
        return upload_dir

    def prepare_upload_target(self, item: ShareItem, relative_path: Path) -> tuple[Path, Path]:
        upload_dir = self.prepare_upload_dir(item)
        target_dir = upload_dir / relative_path.parent
        if not safe_child(target_dir, upload_dir):
            raise RuntimeError("上传路径不在上传目录内。")
        target_dir.mkdir(parents=True, exist_ok=True)
        target = unique_upload_path(target_dir, relative_path.name)
        if not safe_child(target, upload_dir):
            raise RuntimeError("上传文件不在上传目录内。")
        return upload_dir, target

    def write_upload_temp(self, upload_dir: Path, filename: str, content_length: int) -> Path:
        temp_file = tempfile.NamedTemporaryFile("wb", delete=False, dir=upload_dir, prefix=f".{filename}.", suffix=".uploading")
        temp_path = Path(temp_file.name)
        remaining = content_length
        try:
            with temp_file:
                while remaining > 0:
                    chunk = self.rfile.read(min(UPLOAD_CHUNK_SIZE, remaining))
                    if not chunk:
                        raise RuntimeError("连接中断，上传没有完成。")
                    temp_file.write(chunk)
                    remaining -= len(chunk)
        except Exception:
            try:
                temp_path.unlink()
            except OSError:
                pass
            raise
        return temp_path


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


class PythonShareServer:
    def __init__(self, on_access: Callable[[dict[str, str]], None], record_requests: bool = True) -> None:
        self.on_access = on_access
        self.record_requests = record_requests
        self.httpd: Optional[ThreadingHTTPServer] = None
        self.thread: Optional[threading.Thread] = None
        self.items: list[ShareItem] = []
        self.items_by_id: dict[int, ShareItem] = {}

    def refresh_items(self, items: list[ShareItem]) -> None:
        self.items = list(items)
        self.items_by_id = {item.item_id: item for item in items}

    def start(self, items: list[ShareItem], port: int, host: str = "0.0.0.0") -> int:
        self.refresh_items(items)
        try:
            self.httpd = ReusableThreadingHTTPServer((host, port), ShareHandler)
        except OSError as error:
            if error.errno in (errno.EADDRINUSE, 48, 98, 10048):
                raise RuntimeError(f"端口 {port} 已被占用。请换一个端口，或先停止占用该端口的程序。") from error
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

    def record(self, handler: ShareHandler, code: str, size: str) -> None:
        parsed = urllib.parse.urlsplit(handler.path)
        if parsed.path == "/favicon.ico":
            return
        item_name = ""
        match = re.match(r"^/items/(\d+)", parsed.path)
        if match:
            item = self.items_by_id.get(int(match.group(1)))
            item_name = item.name if item else ""
        self.on_access(
            {
                "time": now_text(),
                "ip": client_ip_from_handler(handler),
                "engine": "Python",
                "method": handler.command,
                "status": code,
                "item": item_name,
                "path": urllib.parse.unquote(parsed.path),
                "size": size,
            }
        )

    def record_upload(
        self,
        handler: ShareHandler,
        code: str,
        item: Optional[ShareItem],
        filename: str,
        size: str,
        path: str,
    ) -> None:
        self.on_access(
            {
                "time": now_text(),
                "ip": client_ip_from_handler(handler),
                "engine": "Python",
                "method": "POST",
                "status": code,
                "item": item.name if item else "",
                "path": path if code == "201" else f"上传失败：{filename or '-'}｜{path}",
                "size": size,
            }
        )


class NginxShareServer:
    def __init__(self) -> None:
        self.process: Optional[subprocess.Popen] = None
        self.runtime_dir: Optional[Path] = None
        self.access_log: Optional[Path] = None

    def start(self, items: list[ShareItem], port: int, python_backend_port: Optional[int] = None) -> Path:
        nginx = self.find_nginx()
        if not nginx:
            raise RuntimeError("Nginx 尚未准备完成。")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.runtime_dir = APP_DIR / "nginx" / stamp
        logs_dir = self.runtime_dir / "logs"
        www_dir = self.runtime_dir / "www"
        logs_dir.mkdir(parents=True, exist_ok=True)
        www_dir.mkdir(parents=True, exist_ok=True)
        self.access_log = logs_dir / "access.log"
        config_path = self.runtime_dir / "nginx.conf"
        (www_dir / "index.html").write_text(self.index_html(items), encoding="utf-8")
        config_path.write_text(
            self.config_text(items, port, www_dir, self.access_log, logs_dir / "error.log", python_backend_port, self.find_mime_types(nginx)),
            encoding="utf-8",
        )
        self.process = subprocess.Popen([nginx, "-p", str(self.runtime_dir), "-c", str(config_path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(0.8)
        if self.process.poll() is not None:
            stderr = self.process.stderr.read() if self.process.stderr else ""
            if "Address already in use" in stderr or "bind()" in stderr:
                raise RuntimeError(f"端口 {port} 已被占用。请换一个端口，或先停止占用该端口的程序。")
            raise RuntimeError(stderr.strip() or "Nginx 启动失败")
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
        result = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True, check=False)
        return result.stdout.strip()

    @staticmethod
    def terminate_pid(pid: int) -> None:
        if pid <= 0:
            return
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        except PermissionError:
            return
        for _ in range(20):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.1)
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            return

    @classmethod
    def terminate_pid_file(cls, pid_path: Path) -> None:
        try:
            pid = int(pid_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return
        command = cls.process_command(pid)
        if command and str(APP_DIR / "nginx") not in command:
            return
        cls.terminate_pid(pid)

    @classmethod
    def cleanup_stale_instances(cls) -> None:
        if sys.platform.startswith("win"):
            return
        runtime_root = APP_DIR / "nginx"
        if not runtime_root.exists():
            return
        for pid_path in runtime_root.glob("*/nginx.pid"):
            cls.terminate_pid_file(pid_path)

    @staticmethod
    def find_nginx() -> Optional[str]:
        candidates = [
            shutil.which("nginx"),
            "/opt/homebrew/bin/nginx",
            "/opt/homebrew/opt/nginx/bin/nginx",
            "/usr/local/bin/nginx",
            "/usr/local/opt/nginx/bin/nginx",
            "/usr/sbin/nginx",
            r"C:\nginx\nginx.exe",
            r"C:\ProgramData\chocolatey\bin\nginx.exe",
        ]
        for candidate in candidates:
            if candidate and Path(candidate).is_file():
                return str(candidate)
        if sys.platform.startswith("win"):
            local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
            package_root = local_app_data / "Microsoft" / "WinGet" / "Packages"
            if package_root.exists():
                for candidate in package_root.glob("nginx.nginx_*/**/nginx.exe"):
                    if candidate.is_file():
                        return str(candidate)
        return None

    @staticmethod
    def find_mime_types(nginx_path: str) -> Optional[Path]:
        nginx_file = Path(nginx_path).resolve()
        candidates = [
            nginx_file.parent.parent / "conf" / "mime.types",
            nginx_file.parent / "conf" / "mime.types",
            Path("/opt/homebrew/etc/nginx/mime.types"),
            Path("/usr/local/etc/nginx/mime.types"),
            Path("/etc/nginx/mime.types"),
            Path(r"C:\nginx\conf\mime.types"),
        ]
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return None

    @staticmethod
    def find_brew() -> Optional[str]:
        for candidate in [shutil.which("brew"), "/opt/homebrew/bin/brew", "/usr/local/bin/brew"]:
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
                raise RuntimeError("未检测到 Homebrew，无法自动准备 Nginx。可以先勾选“临时”继续使用。")
            command = [brew, "install", "nginx"]
        elif sys.platform.startswith("win"):
            if shutil.which("winget"):
                command = [
                    "winget",
                    "install",
                    "--id",
                    "nginx.nginx",
                    "--exact",
                    "--silent",
                    "--accept-source-agreements",
                    "--accept-package-agreements",
                ]
            elif shutil.which("choco"):
                command = ["choco", "install", "nginx", "-y"]
            else:
                raise RuntimeError("未检测到 winget 或 Chocolatey，无法自动准备 Nginx。可以先勾选“临时”继续使用。")
        else:
            raise RuntimeError("当前系统暂不支持自动准备 Nginx。可以先勾选“临时”继续使用。")
        install_env = os.environ.copy()
        if sys.platform == "darwin":
            install_env["HOMEBREW_NO_AUTO_UPDATE"] = "1"
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            env=install_env,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise RuntimeError(f"Nginx 自动安装失败。\n{detail[-1600:]}")
        installed = cls.find_nginx()
        if not installed:
            raise RuntimeError("Nginx 已安装，但应用暂时没有找到可执行文件。请重新启动应用后再试。")
        return installed

    @staticmethod
    def nginx_path(path: Path, trailing_slash: bool = False) -> str:
        value = str(path.resolve()).replace("\\", "/")
        if trailing_slash and not value.endswith("/"):
            value += "/"
        return value.replace('"', '\\"')

    def config_text(
        self,
        items: list[ShareItem],
        port: int,
        www_dir: Path,
        access_log: Path,
        error_log: Path,
        python_backend_port: Optional[int] = None,
        mime_types: Optional[Path] = None,
    ) -> str:
        locations = []
        for item in items:
            if item_uses_python_backend(item):
                if python_backend_port is None:
                    raise RuntimeError("需要 Python 后端的项目缺少端口。")
                upload_location = ""
                if item_allows_upload(item):
                    upload_location = f"""
        location = /items/{item.item_id}/__upload {{
            proxy_pass http://127.0.0.1:{python_backend_port};
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_request_buffering off;
            proxy_buffering off;
            client_max_body_size 0;
        }}
"""
                locations.append(
                    f"""
{upload_location}
        location = /items/{item.item_id} {{
            proxy_pass http://127.0.0.1:{python_backend_port};
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_buffering off;
        }}
        location /items/{item.item_id}/ {{
            proxy_pass http://127.0.0.1:{python_backend_port};
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_buffering off;
        }}
"""
                )
                continue
            if item.path.is_dir():
                locations.append(
                    f"""
        location = /items/{item.item_id} {{ return 302 /items/{item.item_id}/; }}
        location /items/{item.item_id}/ {{
            alias "{self.nginx_path(item.path, True)}";
            autoindex on;
            autoindex_exact_size off;
            autoindex_localtime on;
            add_header Content-Disposition $jobs_content_disposition always;
        }}
"""
                )
            else:
                locations.append(
                    f"""
        location = /items/{item.item_id} {{
            alias "{self.nginx_path(item.path)}";
            add_header Content-Disposition $jobs_content_disposition always;
        }}
"""
                )
        mime_types_include = f'    include "{self.nginx_path(mime_types)}";\n' if mime_types else ""
        return f"""
daemon off;
worker_processes 1;
pid "{self.nginx_path(self.runtime_dir / "nginx.pid")}";
events {{ worker_connections 1024; }}
http {{
{mime_types_include}    map $arg_download $jobs_content_disposition {{
        default "inline";
        1 "attachment";
        true "attachment";
        yes "attachment";
        on "attachment";
    }}
    default_type application/octet-stream;
    log_format jobs_main '$remote_addr|$time_local|$request|$status|$body_bytes_sent|$http_user_agent';
    access_log "{self.nginx_path(access_log)}" jobs_main;
    error_log "{self.nginx_path(error_log)}" warn;
    server {{
        listen {port};
        server_name localhost;
        charset utf-8;
        location = / {{
            root "{self.nginx_path(www_dir)}";
            index index.html;
        }}
        location = /favicon.ico {{
            access_log off;
            log_not_found off;
            return 204;
        }}
{''.join(locations)}
    }}
}}
""".strip()

    @staticmethod
    def index_html(items: list[ShareItem]) -> str:
        rows = []
        for item in items:
            href = f"/items/{item.item_id}/" if item.path.is_dir() else f"/items/{item.item_id}"
            mode = "Python 临时" if item.temporary else "Nginx"
            download_link = f"<a class=\"action-link\" href=\"/items/{item.item_id}/__download\" download>下载</a>"
            rows.append(
                f"<tr><td>{item.item_id}</td><td><a href=\"{href}\">{html.escape(item.name)}</a></td>"
                f"<td>{html.escape(item.kind)}</td><td>{mode}</td><td>{download_link}</td><td>{html.escape(str(item.path))}</td></tr>"
            )
        body = (
            "<h1>LANFileServer</h1><p class=\"hint\">每个共享项目使用各自选择的服务模式。</p>"
            "<table><thead><tr><th>ID</th><th>名称</th><th>类型</th><th>模式</th><th class=\"actions\">操作</th><th>本机路径</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>"
        )
        return page("LANFileServer", body).decode("utf-8")


class HelpPopup(QWidget):
    def __init__(self, help_text: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent, Qt.ToolTip | Qt.FramelessWindowHint)
        self.setObjectName("helpPopup")
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setMouseTracking(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        label = QLabel(help_text)
        label.setWordWrap(False)
        layout.addWidget(label)
        self.setStyleSheet(
            "QWidget#helpPopup{border:1px solid palette(mid);background:palette(window);"
            "color:palette(window-text);} QLabel{color:palette(window-text);}"
        )

    def show_at(self, position: QPoint) -> None:
        self.adjustSize()
        target = QPoint(position)
        screen = QApplication.screenAt(position)
        if screen:
            area = screen.availableGeometry()
            width = self.sizeHint().width()
            height = self.sizeHint().height()
            if target.x() + width > area.right():
                target.setX(position.x() - width - 6)
            if target.y() + height > area.bottom():
                target.setY(position.y() - height - 6)
            target.setX(max(area.left(), target.x()))
            target.setY(max(area.top(), target.y()))
        self.move(target)
        self.show()
        self.raise_()


class HelpButton(QToolButton):
    def __init__(
        self,
        help_text: str = HELP_TEXT,
        accent: bool = False,
        diameter: int = 24,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.popup = HelpPopup(help_text, self)
        self.left_at: Optional[float] = None
        self.hide_timer = QTimer(self)
        self.hide_timer.setInterval(80)
        self.hide_timer.timeout.connect(self.hide_popup_if_left)
        self.setMouseTracking(True)
        self.setText("?")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(diameter, diameter)
        radius = diameter // 2
        if accent:
            self.setStyleSheet(
                f"QToolButton{{border:2px solid #ef4444;border-radius:{radius}px;background:transparent;"
                "color:#ef4444;font-weight:700;padding:0;} QToolButton:hover{background:palette(light);}"
            )
        else:
            self.setStyleSheet(
                f"QToolButton{{border:1px solid palette(mid);border-radius:{radius}px;background:palette(button);"
                "color:palette(button-text);font-weight:700;padding:0;} QToolButton:hover{background:palette(light);}"
            )

    def enterEvent(self, event) -> None:  # noqa: ANN001
        self.show_popup()
        super().enterEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: ANN001
        self.show_popup()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: ANN001
        self.left_at = time.monotonic()
        super().leaveEvent(event)

    def show_popup(self) -> None:
        self.left_at = None
        self.popup.show_at(QCursor.pos() + QPoint(6, 6))
        if not self.hide_timer.isActive():
            self.hide_timer.start()

    def hide_popup_if_left(self) -> None:
        if not self.popup.isVisible():
            self.hide_timer.stop()
            return
        cursor = QCursor.pos()
        inside_button = self.rect().contains(self.mapFromGlobal(cursor))
        inside_popup = self.popup.geometry().contains(cursor)
        if inside_button or inside_popup:
            self.left_at = None
            return
        if self.left_at is None:
            self.left_at = time.monotonic()
            return
        if time.monotonic() - self.left_at >= 0.18:
            self.popup.hide()
            self.hide_timer.stop()


class AccessHeader(QHeaderView):
    def __init__(self, status_column: int, parent: Optional[QWidget] = None) -> None:
        super().__init__(Qt.Horizontal, parent)
        self.status_column = status_column
        self.status_help = HelpButton(STATUS_HELP_TEXT, accent=True, diameter=18, parent=self.viewport())
        self.sectionResized.connect(self.position_status_help)
        self.sectionMoved.connect(self.position_status_help)
        self.geometriesChanged.connect(self.position_status_help)
        QTimer.singleShot(0, self.position_status_help)

    def position_status_help(self, *_args) -> None:
        section_x = self.sectionViewportPosition(self.status_column)
        section_width = self.sectionSize(self.status_column)
        if section_x < 0 or section_width <= 0:
            self.status_help.hide()
            return
        x = section_x + section_width - self.status_help.width() - 6
        y = max(0, (self.height() - self.status_help.height()) // 2)
        self.status_help.move(x, y)
        self.status_help.show()
        self.status_help.raise_()

    def resizeEvent(self, event) -> None:  # noqa: ANN001, N802
        super().resizeEvent(event)
        self.position_status_help()


class ClickableLabel(QLabel):
    clicked = Signal()

    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event) -> None:  # noqa: ANN001
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class ShareCard(QFrame):
    clicked = Signal(int, object)
    contextRequested = Signal(int, QPoint)
    deleteRequested = Signal()
    modeChanged = Signal(int, bool)
    uploadChanged = Signal(int, bool)
    reorderDragStarted = Signal(int)
    reorderDragEnded = Signal(int)

    def __init__(self, share_item: ShareItem, icon_provider: QFileIconProvider) -> None:
        super().__init__()
        self.item_id = share_item.item_id
        self.path = share_item.path
        self.selected = False
        self.running = share_item.running
        self.press_position = QPoint()
        self.drag_ready = False
        self.drag_started = False
        self.dragging = False
        self.long_press_timer = QTimer(self)
        self.long_press_timer.setSingleShot(True)
        self.long_press_timer.setInterval(350)
        self.long_press_timer.timeout.connect(self.enable_drag_after_hold)
        self.setObjectName("shareCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumHeight(104)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setToolTip(str(self.path))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)

        self.icon_label = QLabel()
        self.icon_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setPixmap(icon_provider.icon(QFileInfo(str(self.path))).pixmap(QSize(48, 48)))
        self.icon_label.setFixedSize(56, 56)
        layout.addWidget(self.icon_label, 0)

        text_box = QWidget()
        text_box.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        text_layout = QVBoxLayout(text_box)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(3)

        self.name_label = QLabel(self.path.name or str(self.path))
        self.name_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.name_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.name_label.setWordWrap(True)
        text_layout.addWidget(self.name_label)

        self.path_label = QLabel(str(self.path))
        self.path_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.path_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.path_label.setWordWrap(True)
        text_layout.addWidget(self.path_label)
        layout.addWidget(text_box, 1)

        right_box = QWidget()
        right_layout = QVBoxLayout(right_box)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)

        self.mode_checkbox = QCheckBox("临时")
        self.mode_checkbox.setChecked(share_item.temporary)
        self.mode_checkbox.setToolTip("勾选使用 Python 临时服务；不勾选使用 Nginx")
        self.mode_checkbox.toggled.connect(lambda checked: self.modeChanged.emit(self.item_id, checked))
        right_layout.addWidget(self.mode_checkbox, 0, Qt.AlignTop)

        self.upload_checkbox = QCheckBox("允许上传")
        self.upload_checkbox.setChecked(item_allows_upload(share_item))
        self.upload_checkbox.setToolTip("只对文件夹生效，上传会写入共享目录下的 Uploads 文件夹")
        self.upload_checkbox.toggled.connect(lambda checked: self.uploadChanged.emit(self.item_id, checked))
        right_layout.addWidget(self.upload_checkbox, 0, Qt.AlignTop)

        self.state_label = QLabel()
        self.state_label.setObjectName("itemStateLabel")
        self.state_label.setAlignment(Qt.AlignCenter)
        right_layout.addWidget(self.state_label, 0, Qt.AlignTop)
        right_layout.addStretch()
        layout.addWidget(right_box, 0, Qt.AlignTop)
        self.sync_state()

    def set_selected(self, selected: bool) -> None:
        self.selected = selected
        self.setProperty("selected", "true" if selected else "false")
        self.sync_state()
        self.style().unpolish(self)
        self.style().polish(self)

    def sync_state(self) -> None:
        self.setFrameShape(QFrame.StyledPanel)
        self.setLineWidth(1)
        self.setProperty("running", "true" if self.running else "false")
        self.state_label.setText("已启动" if self.running else "未启动")

    def set_mode_enabled(self, enabled: bool) -> None:
        self.mode_checkbox.setEnabled(enabled)

    def set_upload_enabled(self, enabled: bool) -> None:
        self.upload_checkbox.setEnabled(enabled and self.path.is_dir())

    def set_upload_allowed(self, allowed: bool) -> None:
        blocked = self.upload_checkbox.blockSignals(True)
        self.upload_checkbox.setChecked(allowed and self.path.is_dir())
        self.upload_checkbox.blockSignals(blocked)

    def set_running(self, running: bool) -> None:
        self.running = running
        self.sync_state()
        self.style().unpolish(self)
        self.style().polish(self)

    def set_dragging(self, dragging: bool) -> None:
        self.dragging = dragging
        self.setProperty("dragging", "true" if dragging else "false")
        if dragging:
            effect = QGraphicsOpacityEffect(self)
            effect.setOpacity(0.35)
            self.setGraphicsEffect(effect)
        else:
            self.setGraphicsEffect(None)
        self.style().unpolish(self)
        self.style().polish(self)

    def enable_drag_after_hold(self) -> None:
        self.drag_ready = True

    def mousePressEvent(self, event) -> None:  # noqa: ANN001
        if event.button() == Qt.LeftButton:
            self.setFocus(Qt.MouseFocusReason)
            self.press_position = event.position().toPoint()
            self.drag_ready = False
            self.drag_started = False
            self.long_press_timer.start()
            self.clicked.emit(self.item_id, event.modifiers())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: ANN001
        if event.buttons() & Qt.LeftButton and self.drag_ready and not self.drag_started:
            distance = (event.position().toPoint() - self.press_position).manhattanLength()
            if distance >= QApplication.startDragDistance():
                self.start_reorder_drag()
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: ANN001
        self.long_press_timer.stop()
        self.drag_ready = False
        self.drag_started = False
        super().mouseReleaseEvent(event)

    def start_reorder_drag(self) -> None:
        self.drag_started = True
        self.long_press_timer.stop()
        mime_data = QMimeData()
        mime_data.setData(INTERNAL_ITEM_MIME, str(self.item_id).encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime_data)
        drag.setPixmap(self.grab())
        drag.setHotSpot(self.press_position)
        self.reorderDragStarted.emit(self.item_id)
        self.set_dragging(True)
        try:
            drag.exec(Qt.MoveAction)
        finally:
            self.set_dragging(False)
            self.reorderDragEnded.emit(self.item_id)

    def contextMenuEvent(self, event) -> None:  # noqa: ANN001
        self.contextRequested.emit(self.item_id, event.globalPos())
        event.accept()

    def keyPressEvent(self, event) -> None:  # noqa: ANN001
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self.deleteRequested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class DropListWidget(QScrollArea):
    pathsDropped = Signal(list)
    itemContextRequested = Signal(int, QPoint)
    blankContextRequested = Signal(QPoint)
    removeRequested = Signal()
    selectionChanged = Signal()
    modeChanged = Signal(int, bool)
    uploadChanged = Signal(int, bool)
    orderChanged = Signal(list)

    def __init__(self, icon_provider: QFileIconProvider) -> None:
        super().__init__()
        self.icon_provider = icon_provider
        self.cards: dict[int, ShareCard] = {}
        self.card_order: list[int] = []
        self.selected: set[int] = set()
        self.reorder_animations: list[QPropertyAnimation] = []
        self.drag_source_id: Optional[int] = None
        self.drag_original_order: list[int] = []
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.viewport().setAcceptDrops(True)
        self.viewport().installEventFilter(self)
        self.setWidgetResizable(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)

        self.content = QWidget()
        self.content.setAcceptDrops(True)
        self.content.installEventFilter(self)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_layout = QVBoxLayout(self.content)
        self.list_layout.setContentsMargins(8, 8, 8, 8)
        self.list_layout.setSpacing(8)
        self.list_layout.setAlignment(Qt.AlignTop)
        self.placeholder = QLabel("拖入文件 / 文件夹")
        self.placeholder.setAlignment(Qt.AlignCenter)
        self.placeholder.setMinimumHeight(180)
        self.list_layout.addWidget(self.placeholder)
        self.list_layout.addStretch(1)
        self.setWidget(self.content)

    def eventFilter(self, source, event) -> bool:  # noqa: ANN001
        if source in (self.viewport(), self.content) and event.type() in (QEvent.DragEnter, QEvent.DragMove, QEvent.Drop):
            if self.handle_reorder_event(event, None):
                return True
            return self.handle_drop_event(event)
        if source in (self.viewport(), self.content) and event.type() == QEvent.ContextMenu:
            self.blankContextRequested.emit(event.globalPos())
            event.accept()
            return True
        if isinstance(source, ShareCard) and event.type() in (QEvent.DragEnter, QEvent.DragMove, QEvent.Drop):
            if self.handle_reorder_event(event, source.item_id):
                return True
            return self.handle_drop_event(event)
        return super().eventFilter(source, event)

    def dragEnterEvent(self, event) -> None:  # noqa: ANN001
        if self.handle_reorder_event(event, None):
            return
        self.handle_drop_event(event)

    def dragMoveEvent(self, event) -> None:  # noqa: ANN001
        if self.handle_reorder_event(event, None):
            return
        self.handle_drop_event(event)

    def dropEvent(self, event) -> None:  # noqa: ANN001
        if self.handle_reorder_event(event, None):
            return
        self.handle_drop_event(event)

    def handle_drop_event(self, event) -> bool:  # noqa: ANN001
        if event.type() in (QEvent.DragEnter, QEvent.DragMove):
            if event.mimeData().hasUrls():
                event.setDropAction(Qt.CopyAction)
                event.accept()
                return True
            event.ignore()
            return True
        if event.type() != QEvent.Drop:
            return False
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.pathsDropped.emit(paths)
            event.setDropAction(Qt.CopyAction)
            event.accept()
        else:
            event.ignore()
        return True

    def handle_reorder_event(self, event, target_id: Optional[int]) -> bool:  # noqa: ANN001
        mime_data = event.mimeData()
        if not mime_data.hasFormat(INTERNAL_ITEM_MIME):
            return False
        if event.type() not in (QEvent.DragEnter, QEvent.DragMove, QEvent.Drop):
            return False
        source_id = self.dragged_item_id(mime_data)
        if source_id is None or source_id not in self.cards:
            event.ignore()
            return True
        self.begin_drag_session(source_id)
        if event.type() == QEvent.DragMove:
            self.preview_reorder(source_id, target_id, self.drop_after_target(event, target_id))
        elif event.type() == QEvent.Drop:
            self.preview_reorder(source_id, target_id, self.drop_after_target(event, target_id))
            self.finish_drag_session(source_id)
        event.setDropAction(Qt.MoveAction)
        event.accept()
        return True

    def begin_drag_session(self, source_id: int) -> None:
        if self.drag_source_id == source_id:
            return
        self.drag_source_id = source_id
        self.drag_original_order = list(self.card_order)

    def finish_drag_session(self, source_id: int) -> None:
        if self.drag_source_id != source_id:
            return
        changed = self.card_order != self.drag_original_order
        self.drag_source_id = None
        self.drag_original_order = []
        if changed:
            self.orderChanged.emit(list(self.card_order))

    def preview_reorder(self, source_id: int, target_id: Optional[int], insert_after: bool) -> bool:
        return self.reorder_card(source_id, target_id, insert_after)

    def dragged_item_id(self, mime_data: QMimeData) -> Optional[int]:
        try:
            return int(bytes(mime_data.data(INTERNAL_ITEM_MIME)).decode("utf-8"))
        except (TypeError, ValueError):
            return None

    def drop_after_target(self, event, target_id: Optional[int]) -> bool:  # noqa: ANN001
        if target_id is None:
            return True
        card = self.cards.get(target_id)
        if not card:
            return True
        return event.position().toPoint().y() > card.height() // 2

    def reorder_card(self, source_id: int, target_id: Optional[int], insert_after: bool) -> bool:
        if source_id not in self.card_order:
            return False
        if target_id == source_id:
            return False
        before_geometries = self.card_geometries()
        before = list(self.card_order)
        ordered = [item_id for item_id in self.card_order if item_id != source_id]
        if target_id is None or target_id not in ordered:
            insert_index = len(ordered)
        else:
            target_index = ordered.index(target_id)
            insert_index = target_index + (1 if insert_after else 0)
        ordered.insert(insert_index, source_id)
        if ordered == before:
            return False
        self.card_order = ordered
        self.refresh_grid()
        self.animate_reorder_from(before_geometries)
        return True

    def card_geometries(self) -> dict[int, object]:
        return {item_id: card.geometry() for item_id, card in self.cards.items()}

    def animate_reorder_from(self, before_geometries: dict[int, object]) -> None:
        self.list_layout.activate()
        self.content.adjustSize()
        QApplication.processEvents()
        self.reorder_animations.clear()
        for item_id in self.card_order:
            card = self.cards.get(item_id)
            if not card or item_id not in before_geometries:
                continue
            start_geometry = before_geometries[item_id]
            end_geometry = card.geometry()
            if start_geometry == end_geometry:
                continue
            card.setGeometry(start_geometry)
            animation = QPropertyAnimation(card, b"geometry", self)
            animation.setDuration(180)
            animation.setEasingCurve(QEasingCurve.OutCubic)
            animation.setStartValue(start_geometry)
            animation.setEndValue(end_geometry)
            animation.finished.connect(lambda animation=animation: self.remove_reorder_animation(animation))
            self.reorder_animations.append(animation)
            animation.start()

    def remove_reorder_animation(self, animation: QPropertyAnimation) -> None:
        if animation in self.reorder_animations:
            self.reorder_animations.remove(animation)

    def add_card(self, share_item: ShareItem) -> None:
        if self.placeholder:
            self.placeholder.setParent(None)
            self.placeholder.deleteLater()
            self.placeholder = None
        card = ShareCard(share_item, self.icon_provider)
        card.clicked.connect(self.set_selected_card)
        card.contextRequested.connect(self.itemContextRequested.emit)
        card.deleteRequested.connect(self.removeRequested.emit)
        card.modeChanged.connect(self.modeChanged.emit)
        card.uploadChanged.connect(self.uploadChanged.emit)
        card.reorderDragStarted.connect(self.begin_drag_session)
        card.reorderDragEnded.connect(self.finish_drag_session)
        card.setAcceptDrops(True)
        card.installEventFilter(self)
        self.cards[share_item.item_id] = card
        self.card_order.append(share_item.item_id)
        self.refresh_grid()

    def remove_cards(self, item_ids: set[int]) -> None:
        for item_id in item_ids:
            card = self.cards.pop(item_id, None)
            if card:
                card.setParent(None)
                card.deleteLater()
        self.card_order = [item_id for item_id in self.card_order if item_id not in item_ids]
        self.selected.difference_update(item_ids)
        self.refresh_grid()
        self.selectionChanged.emit()

    def selected_ids(self) -> set[int]:
        return set(self.selected)

    def set_mode_controls_enabled(self, enabled: bool) -> None:
        for card in self.cards.values():
            card.set_mode_enabled(enabled)

    def set_item_running(self, item_id: int, running: bool) -> None:
        card = self.cards.get(item_id)
        if card:
            card.set_running(running)

    def set_item_mode_enabled(self, item_id: int, enabled: bool) -> None:
        card = self.cards.get(item_id)
        if card:
            card.set_mode_enabled(enabled)

    def set_item_upload_enabled(self, item_id: int, enabled: bool) -> None:
        card = self.cards.get(item_id)
        if card:
            card.set_upload_enabled(enabled)

    def set_item_upload_allowed(self, item_id: int, allowed: bool) -> None:
        card = self.cards.get(item_id)
        if card:
            card.set_upload_allowed(allowed)

    def select_single(self, item_id: int) -> None:
        if item_id not in self.cards:
            return
        self.clear_selection(False)
        self.selected.add(item_id)
        self.cards[item_id].set_selected(True)
        self.selectionChanged.emit()

    def set_selected_card(self, item_id: int, modifiers) -> None:  # noqa: ANN001
        self.setFocus(Qt.MouseFocusReason)
        before = set(self.selected)
        if not (modifiers & Qt.MetaModifier or modifiers & Qt.ControlModifier):
            self.clear_selection(False)
        if item_id in self.selected:
            self.selected.remove(item_id)
            self.cards[item_id].set_selected(False)
        else:
            self.selected.add(item_id)
            self.cards[item_id].set_selected(True)
        if before != self.selected:
            self.selectionChanged.emit()

    def clear_selection(self, emit_signal: bool = True) -> None:
        changed = bool(self.selected)
        for selected_id in list(self.selected):
            card = self.cards.get(selected_id)
            if card:
                card.set_selected(False)
        self.selected.clear()
        if changed and emit_signal:
            self.selectionChanged.emit()

    def refresh_grid(self) -> None:
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)
        if not self.cards:
            self.placeholder = QLabel("拖入文件 / 文件夹")
            self.placeholder.setAlignment(Qt.AlignCenter)
            self.placeholder.setMinimumHeight(180)
            self.list_layout.addWidget(self.placeholder)
            self.list_layout.addStretch(1)
            return
        for item_id in self.card_order:
            card = self.cards.get(item_id)
            if not card:
                continue
            self.list_layout.addWidget(card)
        self.list_layout.addStretch(1)

    def keyPressEvent(self, event) -> None:  # noqa: ANN001
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self.removeRequested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class MainWindow(QMainWindow):
    accessReceived = Signal(dict)
    publicIpResolved = Signal(dict)
    nginxInstallFinished = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("LANFileServer - 局域网文件服务器")
        self.resize(1120, 720)
        self.setAcceptDrops(True)
        self.icon_provider = QFileIconProvider()
        self.next_id = 0
        self.items: list[ShareItem] = []
        self.python_server: Optional[PythonShareServer] = None
        self.nginx_server: Optional[NginxShareServer] = None
        self.nginx_log_path: Optional[Path] = None
        self.nginx_offset = 0
        self.nginx_installing = False
        self.pending_start_item_id: Optional[int] = None
        self.lan_ips = get_lan_ips()
        self.public_ip = "获取中"
        self.public_ip_location = "位置获取中"
        self.status_text = "未启动"
        self.accessReceived.connect(self.add_access_row)
        self.publicIpResolved.connect(self.set_public_ip)
        self.nginxInstallFinished.connect(self.finish_nginx_install)
        self.log_timer = QTimer(self)
        self.log_timer.timeout.connect(self.read_nginx_log)
        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self.refresh_clock)
        self.build_ui()
        self.apply_style()
        self.refresh_status("未启动")
        self.refresh_clock()
        self.clock_timer.start(1000)
        self.resolve_public_ip_async()

    def build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 8, 10, 10)
        root.setSpacing(8)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)
        temp_box = QWidget()
        temp_layout = QVBoxLayout(temp_box)
        temp_layout.setContentsMargins(0, 0, 0, 0)
        temp_layout.setSpacing(2)
        temp_row = QHBoxLayout()
        temp_row.setContentsMargins(0, 0, 0, 0)
        temp_row.setSpacing(6)
        self.mode_title_label = QLabel()
        temp_row.addWidget(self.mode_title_label)
        temp_row.addWidget(HelpButton())
        temp_row.addStretch()
        temp_layout.addLayout(temp_row)
        self.temp_hint_widget = QWidget()
        temp_hint_layout = QHBoxLayout(self.temp_hint_widget)
        temp_hint_layout.setContentsMargins(0, 0, 0, 0)
        temp_hint_layout.setSpacing(4)
        self.temp_hint_label = ClickableLabel()
        self.temp_hint_label.setObjectName("tempHintLabel")
        self.temp_hint_label.setWordWrap(True)
        self.temp_hint_label.clicked.connect(self.copy_url)
        temp_hint_layout.addWidget(self.temp_hint_label, 1)
        self.temp_hint_widget.setVisible(False)
        temp_layout.addWidget(self.temp_hint_widget)

        control_row = QHBoxLayout()
        control_row.setContentsMargins(0, 0, 0, 0)
        control_row.setSpacing(8)
        control_row.addWidget(QLabel("端口"))
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(8080)
        self.port_spin.setFixedWidth(96)
        self.port_spin.valueChanged.connect(self.refresh_temp_hint)
        control_row.addWidget(self.port_spin)
        self.toggle_button = QPushButton("启动")
        self.toggle_button.clicked.connect(self.toggle_server)
        control_row.addWidget(self.toggle_button)
        control_row.addStretch()
        temp_layout.addLayout(control_row)

        top.addWidget(temp_box, 0, Qt.AlignTop)
        top.addStretch()
        status_box = QWidget()
        status_layout = QVBoxLayout(status_box)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(1)
        self.status_label = QLabel()
        self.status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        status_layout.addWidget(self.status_label)
        self.time_label = QLabel()
        self.time_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        status_layout.addWidget(self.time_label)
        self.lan_ip_label = ClickableLabel()
        self.lan_ip_label.setObjectName("ipLabel")
        self.lan_ip_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.lan_ip_label.clicked.connect(self.copy_lan_ip)
        status_layout.addWidget(self.lan_ip_label)
        self.public_ip_label = ClickableLabel()
        self.public_ip_label.setObjectName("ipLabel")
        self.public_ip_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.public_ip_label.clicked.connect(self.copy_public_ip)
        status_layout.addWidget(self.public_ip_label)
        top.addWidget(status_box)
        root.addLayout(top, 0)
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 8, 0)
        left_layout.setSpacing(8)
        left_layout.addWidget(QLabel("对外暴露的文件 / 文件夹（可直接拖入）"))
        self.share_list = DropListWidget(self.icon_provider)
        self.share_list.pathsDropped.connect(self.add_paths)
        self.share_list.itemContextRequested.connect(self.open_share_context_menu)
        self.share_list.blankContextRequested.connect(self.open_blank_share_context_menu)
        self.share_list.removeRequested.connect(self.remove_selected)
        self.share_list.selectionChanged.connect(self.refresh_selection_state)
        self.share_list.modeChanged.connect(self.set_item_temporary)
        self.share_list.uploadChanged.connect(self.set_item_upload_allowed)
        self.share_list.orderChanged.connect(self.reorder_items)
        left_layout.addWidget(self.share_list, 1)
        left_buttons = QHBoxLayout()
        left_buttons.setContentsMargins(0, 0, 0, 0)
        left_buttons.setSpacing(8)
        add_file = QPushButton("添加文件")
        add_file.clicked.connect(self.choose_files)
        left_buttons.addWidget(add_file)
        add_dir = QPushButton("添加文件夹")
        add_dir.clicked.connect(self.choose_dir)
        left_buttons.addWidget(add_dir)
        self.remove_button = QPushButton("移除")
        self.remove_button.setEnabled(False)
        self.remove_button.clicked.connect(self.remove_selected)
        left_buttons.addWidget(self.remove_button)
        left_layout.addLayout(left_buttons)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 0, 0, 0)
        right_layout.setSpacing(8)
        right_layout.addWidget(QLabel("访问记录"))
        self.access_table = QTableWidget(0, 8)
        self.access_header = AccessHeader(5, self.access_table)
        self.access_table.setHorizontalHeader(self.access_header)
        self.access_table.setHorizontalHeaderLabels(["序号", "时间", "访问人 IP", "引擎", "方法", "状态", "对象", "路径"])
        self.access_table.verticalHeader().setVisible(False)
        for col in range(7):
            self.access_header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.access_header.setSectionResizeMode(0, QHeaderView.Fixed)
        self.access_header.resizeSection(0, 58)
        self.access_header.setSectionResizeMode(5, QHeaderView.Fixed)
        self.access_header.resizeSection(5, 82)
        self.access_header.setSectionResizeMode(7, QHeaderView.Stretch)
        self.access_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.access_table.setAlternatingRowColors(True)
        self.access_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.access_table.customContextMenuRequested.connect(self.open_access_context_menu)
        self.access_placeholder = QLabel("启动服务以后查看", self.access_table.viewport())
        self.access_placeholder.setObjectName("accessPlaceholder")
        self.access_placeholder.setAlignment(Qt.AlignCenter)
        self.access_placeholder.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.access_placeholder.hide()
        self.access_table.viewport().installEventFilter(self)
        right_layout.addWidget(self.access_table, 1)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([360, 720])
        root.addWidget(splitter, 1)
        self.setCentralWidget(central)
        self.toast_label = QLabel(self)
        self.toast_label.setObjectName("toastLabel")
        self.toast_label.setAlignment(Qt.AlignCenter)
        self.toast_label.hide()
        self.toast_timer = QTimer(self)
        self.toast_timer.setSingleShot(True)
        self.toast_timer.timeout.connect(self.toast_label.hide)
        self.refresh_selection_state()
        self.refresh_access_placeholder()

    def apply_style(self) -> None:
        self.setStyleSheet(
            """
            QWidget { font-size: 14px; }
            QPushButton { padding: 7px 12px; }
            QScrollArea, QTableWidget { border: 1px solid palette(mid); border-radius: 6px; background: palette(base); color: palette(text); }
            QFrame#shareCard { border: 1px solid palette(mid); border-radius: 6px; background: palette(base); color: palette(text); }
            QFrame#shareCard[running="true"] { border-color: palette(link); }
            QFrame#shareCard[selected="true"] { border: 2px solid palette(highlight); background: palette(highlight); color: palette(highlighted-text); }
            QFrame#shareCard[selected="true"] QLabel { color: palette(highlighted-text); }
            QFrame#shareCard[selected="true"] QCheckBox { color: palette(highlighted-text); }
            QFrame#shareCard[dragging="true"] { border: 1px dashed palette(highlight); }
            QLabel#tempHintLabel { color: palette(link); font-size: 12px; }
            QLabel#itemStateLabel { color: palette(link); font-size: 12px; }
            QLabel#tempHintLabel:hover, QLabel#ipLabel:hover { text-decoration: underline; }
            QLabel#ipLabel { color: palette(link); }
            QLabel#accessPlaceholder { color: palette(mid); font-size: 16px; font-weight: 700; background: transparent; }
            QLabel#toastLabel { padding: 8px 14px; border-radius: 6px; background: palette(highlight); color: palette(highlighted-text); }
            QHeaderView::section { padding: 8px; font-weight: 700; background: palette(button); color: palette(button-text); border: none; border-bottom: 1px solid palette(mid); }
            """
        )

    def add_paths(self, paths: list[str]) -> None:
        if not self.items:
            self.next_id = 0
        existing = {str(item.path.resolve()) for item in self.items if item.path.exists()}
        last_added_id: Optional[int] = None
        for value in paths:
            path = Path(value).expanduser()
            if not path.exists():
                continue
            resolved = str(path.resolve())
            if resolved in existing:
                continue
            item = ShareItem(self.next_id, path, temporary=True)
            self.next_id += 1
            self.items.append(item)
            self.share_list.add_card(item)
            existing.add(resolved)
            last_added_id = item.item_id
        if last_added_id is not None:
            self.share_list.select_single(last_added_id)
        else:
            self.refresh_selection_state()

    def choose_files(self) -> None:
        dialog = QFileDialog(self, "选择要暴露的文件")
        dialog.setOption(QFileDialog.DontUseNativeDialog, True)
        dialog.setFileMode(QFileDialog.ExistingFiles)
        dialog.setAcceptMode(QFileDialog.AcceptOpen)
        dialog.setViewMode(QFileDialog.Detail)
        paths = dialog.selectedFiles() if dialog.exec() == QFileDialog.Accepted else []
        if paths:
            self.add_paths(paths)

    def choose_dir(self) -> None:
        dialog = QFileDialog(self, "选择要暴露的文件夹")
        dialog.setOption(QFileDialog.DontUseNativeDialog, True)
        dialog.setOption(QFileDialog.ShowDirsOnly, True)
        dialog.setFileMode(QFileDialog.Directory)
        dialog.setAcceptMode(QFileDialog.AcceptOpen)
        dialog.setViewMode(QFileDialog.Detail)
        paths = dialog.selectedFiles() if dialog.exec() == QFileDialog.Accepted else []
        if paths:
            self.add_paths(paths)

    def dragEnterEvent(self, event) -> None:  # noqa: ANN001
        self.share_list.handle_drop_event(event)

    def dragMoveEvent(self, event) -> None:  # noqa: ANN001
        self.share_list.handle_drop_event(event)

    def dropEvent(self, event) -> None:  # noqa: ANN001
        self.share_list.handle_drop_event(event)

    def remove_selected(self) -> None:
        selected = self.share_list.selected_ids()
        if not selected:
            return
        removed_running = any(item.running for item in self.items if item.item_id in selected)
        self.items = [item for item in self.items if item.item_id not in selected]
        self.share_list.remove_cards(selected)
        self.select_default_item()
        if removed_running:
            self.rebuild_runtime_safely()
            self.refresh_running_status("已停止")
        if not self.items:
            self.next_id = 0
        self.refresh_selection_state()

    def clear_all_items(self) -> None:
        if not self.items:
            return
        self.stop_runtime()
        self.items.clear()
        self.next_id = 0
        self.share_list.remove_cards(set(self.share_list.cards.keys()))
        self.refresh_status("未启动")
        self.refresh_selection_state()

    def open_blank_share_context_menu(self, global_position: QPoint) -> None:
        menu = QMenu(self)
        clear_action = menu.addAction("全部清除")
        clear_action.setEnabled(bool(self.items))
        if menu.exec(global_position) == clear_action:
            self.clear_all_items()

    def open_share_context_menu(self, item_id: int, global_position: QPoint) -> None:
        self.share_list.clear_selection()
        card = self.share_list.cards.get(item_id)
        if card:
            self.share_list.selected.add(item_id)
            card.set_selected(True)
            self.share_list.selectionChanged.emit()
        share_item = next((item for item in self.items if item.item_id == item_id), None)
        menu = QMenu(self)
        toggle_action = menu.addAction("停止" if share_item and share_item.running else "启动")
        toggle_action.setEnabled(bool(share_item) and not self.nginx_installing)
        copy_url_action = menu.addAction("复制URL")
        copy_url_action.setEnabled(bool(share_item))
        open_url_action = menu.addAction("本机默认浏览器打开")
        open_url_action.setEnabled(bool(share_item and share_item.running))
        show_action = menu.addAction("Show in Finder")
        remove_action = menu.addAction("移除")
        selected_action = menu.exec(global_position)
        if selected_action == toggle_action and share_item:
            self.stop_item(share_item) if share_item.running else self.start_item(share_item)
        elif selected_action == copy_url_action and share_item:
            self.copy_item_url(share_item)
        elif selected_action == open_url_action and share_item:
            self.open_item_url(share_item)
        elif selected_action == show_action:
            self.show_item_in_finder(item_id)
        elif selected_action == remove_action:
            self.remove_selected()

    def open_access_context_menu(self, position: QPoint) -> None:
        menu = QMenu(self)
        clear_action = menu.addAction("清除记录")
        clear_action.setEnabled(self.access_table.rowCount() > 0)
        selected_action = menu.exec(self.access_table.viewport().mapToGlobal(position))
        if selected_action == clear_action:
            self.clear_access_records()

    def clear_access_records(self) -> None:
        self.access_table.setRowCount(0)
        self.refresh_access_placeholder()
        self.show_toast("访问记录已清除")

    def reorder_items(self, item_order: list[int]) -> None:
        items_by_id = {item.item_id: item for item in self.items}
        ordered_items = [items_by_id[item_id] for item_id in item_order if item_id in items_by_id]
        ordered_ids = {item.item_id for item in ordered_items}
        ordered_items.extend(item for item in self.items if item.item_id not in ordered_ids)
        self.items = ordered_items
        if self.active_items():
            self.rebuild_runtime_safely()

    def show_item_in_finder(self, item_id: int) -> None:
        share_item = next((item for item in self.items if item.item_id == item_id), None)
        if not share_item or not share_item.path.exists():
            QMessageBox.warning(self, "路径不存在", "这个文件 / 文件夹已经不存在。")
            return
        if sys.platform == "darwin":
            subprocess.run(["open", "-R", str(share_item.path)], check=False)
        elif sys.platform.startswith("win"):
            subprocess.run(["explorer", "/select,", str(share_item.path)], check=False)
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(share_item.path.parent)))

    def home_url(self) -> str:
        return f"http://{self.lan_ips[0]}:{self.port_spin.value()}/"

    def item_url(self, item: ShareItem) -> str:
        return f"{self.home_url()}items/{item.item_id}/"

    def copy_item_url(self, item: ShareItem) -> None:
        QApplication.clipboard().setText(self.item_url(item))
        self.show_toast("访问地址已复制")

    def open_item_url(self, item: ShareItem) -> None:
        if not item.running:
            self.show_toast("请先启动这个项目")
            return
        QDesktopServices.openUrl(QUrl(self.item_url(item)))

    def selected_share_item(self) -> Optional[ShareItem]:
        selected = self.share_list.selected_ids()
        if len(selected) != 1:
            return None
        selected_id = next(iter(selected))
        return next((item for item in self.items if item.item_id == selected_id), None)

    def current_access_url(self) -> str:
        item = self.selected_share_item()
        return self.item_url(item) if item else ""

    def current_share_item(self) -> Optional[ShareItem]:
        return self.selected_share_item() or (self.items[-1] if self.items else None)

    def select_default_item(self) -> None:
        if self.items and not self.share_list.selected_ids():
            self.share_list.select_single(self.items[-1].item_id)

    def refresh_selection_state(self) -> None:
        self.remove_button.setEnabled(bool(self.share_list.selected_ids()))
        self.refresh_item_cards_state()
        self.refresh_start_button_state()
        self.refresh_mode_title()
        self.refresh_temp_hint()

    def set_item_temporary(self, item_id: int, temporary: bool) -> None:
        item = next((entry for entry in self.items if entry.item_id == item_id), None)
        if item:
            if item.running:
                self.share_list.set_item_mode_enabled(item_id, False)
                return
            item.temporary = temporary
        self.refresh_mode_title()

    def set_item_upload_allowed(self, item_id: int, allowed: bool) -> None:
        item = next((entry for entry in self.items if entry.item_id == item_id), None)
        if item:
            if item.running:
                self.share_list.set_item_upload_allowed(item_id, item_allows_upload(item))
                return
            item.upload_allowed = allowed and item.path.is_dir()
            self.share_list.set_item_upload_allowed(item_id, item.upload_allowed)
        self.refresh_mode_title()

    def item_mode_text(self, item: ShareItem) -> str:
        return "临时（Python）" if item.temporary else "非临时（Nginx）"

    def refresh_mode_title(self) -> None:
        selected_ids = self.share_list.selected_ids()
        if len(selected_ids) == 1:
            item = self.selected_share_item()
            if item:
                self.mode_title_label.setText(f"当前模式：{self.item_mode_text(item)}")
                return
        if len(selected_ids) > 1:
            self.mode_title_label.setText(f"共享模式：已选 {len(selected_ids)} 项")
        elif self.items:
            self.mode_title_label.setText("共享模式：点击左侧项目查看")
        else:
            self.mode_title_label.setText("共享模式：未添加")

    def active_items(self) -> list[ShareItem]:
        return [item for item in self.items if item.running]

    def requires_nginx(self, items: Optional[list[ShareItem]] = None) -> bool:
        targets = items if items is not None else self.active_items()
        return any(not item.temporary for item in targets)

    def server_running(self) -> bool:
        return bool(self.active_items())

    def refresh_start_button_state(self) -> None:
        if self.nginx_installing:
            self.toggle_button.setEnabled(False)
            return
        item = self.selected_share_item()
        self.toggle_button.setText("停止" if item and item.running else "启动")
        can_toggle = item is not None
        self.toggle_button.setEnabled(can_toggle)
        if can_toggle:
            self.toggle_button.setToolTip("")
        elif self.items:
            self.toggle_button.setToolTip("请先点选一个要启动或停止的文件 / 文件夹")
        else:
            self.toggle_button.setToolTip("请先拖入或添加要对外暴露的文件 / 文件夹")

    def refresh_item_cards_state(self) -> None:
        for item in self.items:
            self.share_list.set_item_running(item.item_id, item.running)
            self.share_list.set_item_mode_enabled(item.item_id, not item.running and not self.nginx_installing)
            self.share_list.set_item_upload_enabled(item.item_id, not item.running and not self.nginx_installing)
            self.share_list.set_item_upload_allowed(item.item_id, item_allows_upload(item))

    def refresh_runtime_controls(self) -> None:
        self.port_spin.setEnabled(not self.server_running() and not self.nginx_installing)
        self.refresh_item_cards_state()
        self.refresh_start_button_state()
        self.refresh_temp_hint()
        self.refresh_access_placeholder()

    def refresh_temp_hint(self) -> None:
        if not self.selected_share_item():
            self.temp_hint_label.clear()
            self.temp_hint_widget.setVisible(False)
            return
        self.temp_hint_label.setText(self.current_access_url())
        self.temp_hint_widget.setVisible(True)

    def refresh_status(self, text: str) -> None:
        self.status_text = text
        self.status_label.setText(text)
        self.lan_ip_label.setText(f"内网 IP：{', '.join(self.lan_ips)}")
        self.public_ip_label.setText(f"（目前的）外网 IP：{self.public_ip}｜位置：{self.public_ip_location}")

    def refresh_clock(self) -> None:
        self.time_label.setText(current_time_text())

    def set_public_ip(self, public_info: dict[str, str]) -> None:
        self.public_ip = public_info.get("ip", "获取失败")
        self.public_ip_location = public_info.get("location", "位置获取失败")
        self.refresh_status(self.status_text)

    def resolve_public_ip_async(self) -> None:
        threading.Thread(target=lambda: self.publicIpResolved.emit(get_public_ip_info()), daemon=True).start()

    def toggle_server(self) -> None:
        if self.nginx_installing:
            return
        item = self.selected_share_item()
        if not item:
            return
        if item.running:
            self.stop_item(item)
        else:
            self.start_item(item)

    def start_item(self, item: ShareItem) -> None:
        if not item.path.exists():
            QMessageBox.warning(self, "路径不存在", "这个文件 / 文件夹已经不存在。")
            return
        if not item.temporary and not NginxShareServer.find_nginx():
            self.begin_nginx_install(item.item_id)
            return
        item.running = True
        self.refresh_runtime_controls()
        try:
            self.rebuild_runtime_for_active_items()
        except Exception as error:
            item.running = False
            self.refresh_runtime_controls()
            self.rebuild_runtime_safely()
            QMessageBox.critical(self, "启动失败", str(error))
            self.refresh_status("启动失败")

    def stop_item(self, item: ShareItem, silent: bool = False) -> None:
        item.running = False
        self.refresh_runtime_controls()
        self.rebuild_runtime_safely()
        if not silent:
            self.refresh_running_status("已停止")

    def begin_nginx_install(self, item_id: int) -> None:
        self.nginx_installing = True
        self.pending_start_item_id = item_id
        self.toggle_button.setText("安装中")
        self.toggle_button.setEnabled(False)
        self.port_spin.setEnabled(False)
        self.refresh_item_cards_state()
        self.refresh_status("正在自动准备 Nginx，请稍候")
        threading.Thread(target=self.install_nginx_worker, daemon=True).start()

    def install_nginx_worker(self) -> None:
        try:
            nginx_path = NginxShareServer.install_nginx()
            self.nginxInstallFinished.emit(nginx_path, "")
        except Exception as error:
            self.nginxInstallFinished.emit("", str(error))

    def finish_nginx_install(self, nginx_path: str, error_text: str) -> None:
        self.nginx_installing = False
        pending_item_id = self.pending_start_item_id
        self.pending_start_item_id = None
        self.refresh_runtime_controls()
        if error_text:
            QMessageBox.critical(self, "Nginx 准备失败", error_text)
            self.refresh_status("Nginx 准备失败")
            return
        self.show_toast(f"Nginx 已准备完成：{Path(nginx_path).name}")
        item = next((entry for entry in self.items if entry.item_id == pending_item_id), None)
        if item:
            self.start_item(item)

    def stop_runtime(self) -> None:
        if self.python_server:
            self.python_server.stop()
            self.python_server = None
        if self.nginx_server:
            self.nginx_server.stop()
            self.nginx_server = None
        self.log_timer.stop()
        self.nginx_log_path = None
        self.nginx_offset = 0

    def stop_all_servers(self, silent: bool = False) -> None:
        for item in self.items:
            item.running = False
        self.stop_runtime()
        self.refresh_runtime_controls()
        if not silent:
            self.refresh_status("已停止")

    def rebuild_runtime_safely(self) -> None:
        try:
            self.rebuild_runtime_for_active_items()
        except Exception as error:
            QMessageBox.critical(self, "服务刷新失败", str(error))
            for item in self.items:
                item.running = False
            self.stop_runtime()
            self.refresh_runtime_controls()
            self.refresh_status("启动失败")

    def rebuild_runtime_for_active_items(self) -> None:
        active_items = self.active_items()
        nginx_items = [item for item in active_items if not item.temporary]
        if active_items and not nginx_items and self.python_server and not self.nginx_server:
            self.python_server.refresh_items(active_items)
            self.refresh_running_status()
            self.refresh_runtime_controls()
            return
        self.stop_runtime()
        NginxShareServer.cleanup_stale_instances()
        if not active_items:
            self.refresh_runtime_controls()
            return
        temporary_items = [item for item in active_items if item.temporary]
        backend_items = [item for item in active_items if item_uses_python_backend(item)]
        if nginx_items:
            backend_port = None
            if backend_items:
                self.python_server = PythonShareServer(lambda payload: self.accessReceived.emit(payload), record_requests=False)
                backend_port = self.python_server.start(backend_items, 0, host="127.0.0.1")
            self.nginx_server = NginxShareServer()
            self.nginx_log_path = self.nginx_server.start(active_items, self.port_spin.value(), backend_port)
            self.nginx_offset = 0
            self.log_timer.start(1000)
        elif temporary_items:
            self.python_server = PythonShareServer(lambda payload: self.accessReceived.emit(payload))
            self.python_server.start(temporary_items, self.port_spin.value())
        else:
            self.nginx_server = NginxShareServer()
            self.nginx_log_path = self.nginx_server.start(nginx_items, self.port_spin.value())
            self.nginx_offset = 0
            self.log_timer.start(1000)
        self.refresh_running_status()
        self.refresh_runtime_controls()

    def refresh_running_status(self, stopped_text: str = "未启动") -> None:
        active_items = self.active_items()
        if not active_items:
            self.refresh_status(stopped_text)
            return
        if len(active_items) == 1:
            item = active_items[0]
            self.refresh_status(f"{self.item_mode_text(item)} 已启动：{self.item_url(item)}")
            return
        modes = {self.item_mode_text(item) for item in active_items}
        mode_text = "混合模式" if len(modes) > 1 else next(iter(modes))
        self.refresh_status(f"{mode_text} 已启动 {len(active_items)} 个项目")

    def copy_url(self) -> None:
        url = self.current_access_url()
        if not url:
            self.show_toast("请先选择一个项目")
            return
        QApplication.clipboard().setText(url)
        self.show_toast("访问地址已复制")

    def copy_lan_ip(self) -> None:
        text = ", ".join(self.lan_ips)
        QApplication.clipboard().setText(text)
        self.show_toast("内网 IP 已复制")

    def copy_public_ip(self) -> None:
        QApplication.clipboard().setText(f"{self.public_ip} {self.public_ip_location}")
        self.show_toast("外网 IP 已复制")

    def show_toast(self, text: str) -> None:
        self.toast_label.setText(text)
        self.toast_label.adjustSize()
        self.position_toast()
        self.toast_label.show()
        self.toast_label.raise_()
        self.toast_timer.start(1600)

    def position_toast(self) -> None:
        width = self.toast_label.width()
        x = max(10, (self.width() - width) // 2)
        self.toast_label.move(x, 76)

    def position_access_placeholder(self) -> None:
        if not hasattr(self, "access_placeholder"):
            return
        viewport = self.access_table.viewport()
        self.access_placeholder.setGeometry(0, 0, viewport.width(), viewport.height())

    def refresh_access_placeholder(self) -> None:
        if not hasattr(self, "access_placeholder"):
            return
        should_show = self.access_table.rowCount() == 0 and not self.server_running()
        self.access_placeholder.setVisible(should_show)
        if should_show:
            self.position_access_placeholder()
            self.access_placeholder.raise_()

    def eventFilter(self, source, event) -> bool:  # noqa: ANN001
        if hasattr(self, "access_table") and source == self.access_table.viewport() and event.type() == QEvent.Resize:
            self.position_access_placeholder()
        return super().eventFilter(source, event)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "toast_label") and self.toast_label.isVisible():
            self.position_toast()
        self.position_access_placeholder()

    def add_access_row(self, payload: dict[str, str]) -> None:
        if payload.get("path") == "/favicon.ico":
            return
        row = self.access_table.rowCount()
        self.access_table.insertRow(row)
        values = [str(row + 1)]
        values.extend(payload.get(key, "") for key in ["time", "ip", "engine", "method", "status", "item", "path"])
        for column, value in enumerate(values):
            self.access_table.setItem(row, column, QTableWidgetItem(value))
        self.access_table.scrollToBottom()
        self.refresh_access_placeholder()

    def read_nginx_log(self) -> None:
        if not self.nginx_log_path or not self.nginx_log_path.exists():
            return
        with self.nginx_log_path.open("r", encoding="utf-8", errors="replace") as log_file:
            log_file.seek(self.nginx_offset)
            lines = log_file.readlines()
            self.nginx_offset = log_file.tell()
        for line in lines:
            payload = self.parse_nginx_line(line)
            if payload:
                self.accessReceived.emit(payload)

    def parse_nginx_line(self, line: str) -> Optional[dict[str, str]]:
        parts = line.rstrip("\n").split("|", 5)
        if len(parts) < 5:
            return None
        request_match = re.match(r"(?P<method>\S+) (?P<path>\S+)", parts[2])
        path = urllib.parse.unquote(request_match.group("path")) if request_match else parts[2]
        if path == "/favicon.ico":
            return None
        if re.match(r"^/items/\d+/__upload$", path):
            return None
        item_name = ""
        engine = "Nginx"
        item_match = re.match(r"^/items/(\d+)", path)
        if item_match:
            item = next((entry for entry in self.items if entry.item_id == int(item_match.group(1))), None)
            item_name = item.name if item else ""
            if item and item.temporary:
                engine = "Python"
        return {"time": now_text(), "ip": parts[0], "engine": engine, "method": request_match.group("method") if request_match else "", "status": parts[3], "item": item_name, "path": path, "size": parts[4]}

    def confirm_close_with_active_services(self) -> str:
        active_count = len(self.active_items())
        message = QMessageBox(self)
        message.setIcon(QMessageBox.Question)
        message.setWindowTitle("服务仍在运行")
        message.setText(f"还有 {active_count} 个服务没有结束，是否最小化到任务栏继续运行？")
        message.setInformativeText("选择最小化后，当前共享服务会继续运行；选择停止并退出会关闭所有服务。")
        minimize_button = message.addButton("最小化到任务栏", QMessageBox.AcceptRole)
        stop_button = message.addButton("停止服务并退出", QMessageBox.DestructiveRole)
        cancel_button = message.addButton("取消", QMessageBox.RejectRole)
        message.setDefaultButton(minimize_button)
        message.exec()
        clicked_button = message.clickedButton()
        if clicked_button == minimize_button:
            return "minimize"
        if clicked_button == stop_button:
            return "stop"
        if clicked_button == cancel_button:
            return "cancel"
        return "cancel"

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.active_items():
            action = self.confirm_close_with_active_services()
            if action == "minimize":
                event.ignore()
                self.showMinimized()
                return
            if action == "cancel":
                event.ignore()
                return
        self.stop_all_servers(silent=True)
        event.accept()


def main() -> int:
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
