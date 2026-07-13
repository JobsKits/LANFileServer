"""局域网地址和公网信息探测。"""

from __future__ import annotations

import ipaddress
import json
import socket
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def current_time_text() -> str:
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    weekdays = "一二三四五六日"
    return f"北京时间 {now:%Y-%m-%d %H:%M:%S} 星期{weekdays[now.weekday()]}"


def get_lan_ips() -> list[str]:
    candidates: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            candidates.add(info[4][0])
    except OSError:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("8.8.8.8", 80))
            candidates.add(probe.getsockname()[0])
    except OSError:
        pass
    valid = [ip for ip in candidates if not ip.startswith("127.") and not is_link_local_ip(ip)]
    return sorted(valid, key=lan_ip_sort_key) or ["127.0.0.1"]


def is_link_local_ip(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip).is_link_local
    except ValueError:
        return True


def lan_ip_sort_key(ip: str) -> tuple[int, int]:
    address = ipaddress.ip_address(ip)
    if ip.startswith("192.168."):
        priority = 0
    elif ip.startswith("10."):
        priority = 1
    elif ip.startswith("172.") and 16 <= int(ip.split(".")[1]) <= 31:
        priority = 2
    else:
        priority = 3
    return priority, int(address)


def compact_location_parts(*values: object) -> str:
    parts: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in parts:
            parts.append(text)
    return " ".join(parts)


def read_json_url(url: str) -> dict[str, object]:
    request = urllib.request.Request(url, headers={"User-Agent": "LANFileServer/2.0"})
    with urllib.request.urlopen(request, timeout=4) as response:
        return json.loads(response.read().decode("utf-8"))


def public_location_from_data(data: dict[str, object]) -> str:
    return compact_location_parts(data.get("country"), data.get("regionName") or data.get("region"), data.get("city")) or "位置未知"


def lookup_public_ip_location(ip: str) -> str:
    for url in (f"https://ip-api.com/json/{ip}?lang=zh-CN", f"https://ipwho.is/{ip}"):
        try:
            data = read_json_url(url)
            if data.get("success") is False or data.get("status") == "fail":
                continue
            location = public_location_from_data(data)
            if location != "位置未知":
                return location
        except Exception:
            continue
    return "位置获取失败"


def get_plain_public_ip() -> str:
    for url in ("https://api.ipify.org", "https://ifconfig.me/ip"):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "LANFileServer/2.0"})
            with urllib.request.urlopen(request, timeout=4) as response:
                value = response.read().decode("utf-8").strip()
            if value:
                return value
        except Exception:
            continue
    return "获取失败"


def get_public_ip_info() -> dict[str, str]:
    ip = get_plain_public_ip()
    return {"ip": ip, "location": lookup_public_ip_location(ip) if ip != "获取失败" else "位置获取失败"}
