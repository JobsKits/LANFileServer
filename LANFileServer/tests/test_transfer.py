"""LANFileServer 的传输和 Nginx 路由回归测试。"""

from __future__ import annotations

import json
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from lanfileserver.models import ShareItem
from lanfileserver.servers import NginxShareServer, PythonShareServer
from lanfileserver.web import parse_range, sanitize_upload_path


class TransferTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.payload = bytes(range(256)) * 8192
        (self.root / "large.bin").write_bytes(self.payload)
        self.item = ShareItem(1, self.root, temporary=True, upload_allowed=True, running=True)
        self.events: list[dict[str, str]] = []
        self.server = PythonShareServer(self.events.append)
        self.port = self.server.start([self.item], 0, host="127.0.0.1")

    def tearDown(self) -> None:
        self.server.stop()
        self.temp.cleanup()

    def request(self, path: str, headers: dict[str, str] | None = None, data: bytes | None = None, method: str | None = None) -> urllib.response.addinfourl:
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", headers=headers or {}, data=data, method=method)
        return urllib.request.urlopen(request, timeout=5)

    def test_browser_page_and_range_download(self) -> None:
        with self.request("/items/1/") as response:
            body = response.read().decode()
        self.assertIn("实时速度", body)
        self.assertIn("large.bin", body)
        self.assertIn("显示二维码", body)
        self.assertIn("局域网聊天", body)
        with self.request("/items/1/__raw/large.bin", {"Range": "bytes=1024-2047"}) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(response.headers["Accept-Ranges"], "bytes")
            self.assertEqual(response.read(), self.payload[1024:2048])

    def test_heic_browser_preview_and_image_keyboard_navigation(self) -> None:
        (self.root / "01.jpg").write_bytes(b"jpeg")
        heic_path = self.root / "02.HEIC"
        heic_path.write_bytes(b"heic")
        (self.root / "03.png").write_bytes(b"png")

        with self.request("/items/1/") as response:
            directory_body = response.read().decode()
        self.assertIn("/items/1/__preview/02.HEIC?size=thumb", directory_body)

        with self.request("/items/1/02.HEIC") as response:
            detail_body = response.read().decode()
        self.assertIn('data-image-viewer data-prev="/items/1/01.jpg" data-next="/items/1/03.png"', detail_body)
        self.assertIn('src="/items/1/__preview/02.HEIC"', detail_body)
        self.assertNotIn(">查看</a>", detail_body)
        self.assertIn(">下载原文件</a>", detail_body)
        self.assertIn('data-image-zoom-out aria-label="缩小图片">－ 缩小</button>', detail_body)
        self.assertIn('data-image-zoom-value>100%</span>', detail_body)
        self.assertIn('data-image-zoom-in aria-label="放大图片">放大 ＋</button>', detail_body)
        self.assertIn("2 / 3 · 键盘 ← → 翻阅", detail_body)
        self.assertIn("ArrowLeft", detail_body)
        self.assertIn("ArrowRight", detail_body)
        self.assertIn("Math.min(4,Math.max(.5", detail_body)

        preview_bytes = b"jpeg preview"
        with mock.patch("lanfileserver.web.render_heif_preview", return_value=preview_bytes) as converter:
            with self.request("/items/1/__preview/02.HEIC?size=thumb") as response:
                self.assertEqual(response.headers.get_content_type(), "image/jpeg")
                self.assertIsNone(response.headers["Content-Disposition"])
                self.assertEqual(response.read(), preview_bytes)
        converter.assert_called_once_with(heic_path, 320)

        with self.request("/items/1/__raw/02.HEIC?download=1") as response:
            self.assertTrue(response.headers["Content-Disposition"].startswith("attachment;"))
            self.assertEqual(response.read(), b"heic")

    def test_upload_streams_into_uploads_without_overwrite(self) -> None:
        content = b"streamed upload"
        with self.request("/items/1/__upload?path=folder/demo.txt", data=content) as response:
            self.assertEqual(response.status, 201)
        with self.request("/items/1/__upload?path=folder/demo.txt", data=content) as response:
            self.assertEqual(response.status, 201)
        self.assertEqual((self.root / "Uploads/folder/demo.txt").read_bytes(), content)
        self.assertEqual((self.root / "Uploads/folder/demo (1).txt").read_bytes(), content)

    def test_local_qr_chat_and_controlled_delete(self) -> None:
        with self.request("/__qr?value=http%3A%2F%2F192.168.1.2%3A8080%2Fitems%2F1%2F") as response:
            self.assertEqual(response.headers.get_content_type(), "image/svg+xml")
            self.assertIn(b"<svg", response.read())

        payload = json.dumps({"nickname": "Jobs", "message": "局域网消息"}, ensure_ascii=False).encode()
        with self.request("/items/1/__chat", {"Content-Type": "application/json"}, payload) as response:
            self.assertEqual(response.status, 201)
        with self.request("/items/1/__chat?after=0") as response:
            messages = json.loads(response.read())["messages"]
        self.assertEqual(messages[0]["nickname"], "Jobs")
        self.assertEqual(messages[0]["message"], "局域网消息")
        self.assertNotIn("ip", messages[0])

        uploaded = self.root / "Uploads/remove-me.txt"
        uploaded.parent.mkdir(exist_ok=True)
        uploaded.write_text("remove", encoding="utf-8")
        with self.request("/items/1/__delete?path=remove-me.txt", method="DELETE") as response:
            self.assertEqual(response.status, 200)
        self.assertFalse(uploaded.exists())
        with self.assertRaises(urllib.error.HTTPError) as context:
            self.request("/items/1/__delete?path=../large.bin", method="DELETE")
        self.assertEqual(context.exception.code, 400)
        context.exception.close()

    def test_path_and_range_helpers(self) -> None:
        self.assertEqual(sanitize_upload_path("../../safe/file.txt"), Path("safe/file.txt"))
        self.assertEqual(parse_range("bytes=-100", 1000), (900, 999))
        self.assertIsNone(parse_range("bytes=1000-1001", 1000))


class NginxConfigTests(unittest.TestCase):
    def test_non_temporary_raw_bytes_use_alias(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            static_item = ShareItem(1, root, temporary=False)
            temporary_item = ShareItem(2, root, temporary=True)
            server = NginxShareServer()
            server.runtime_dir = root / "runtime"
            config = server.config_text([static_item, temporary_item], 8080, root / "access.log", root / "error.log", 54321)
        self.assertIn("location ^~ /items/1/__raw/", config)
        self.assertIn(f'alias "{server.nginx_path(root, True)}";', config)
        self.assertNotIn("location ^~ /items/2/__raw/", config)
        self.assertIn("proxy_pass http://127.0.0.1:54321", config)
        self.assertIn("sendfile on", config)


if __name__ == "__main__":
    unittest.main()
