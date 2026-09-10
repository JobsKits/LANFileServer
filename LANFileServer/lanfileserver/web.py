"""浏览器界面、路径安全和流式 HTTP 传输。"""

from __future__ import annotations

import html
import io
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import zipfile
from datetime import datetime
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Optional

from .models import (
    CHAT_MAX_BODY_BYTES,
    PREVIEW_MAX_BYTES,
    UPLOAD_CHUNK_SIZE,
    UPLOAD_DIR_NAME,
    UPLOAD_FREE_SPACE_RESERVE,
    ShareItem,
)


TEXT_FILE_EXTENSIONS = {
    ".bat", ".c", ".command", ".cpp", ".css", ".csv", ".dart", ".h", ".hpp",
    ".html", ".ini", ".java", ".js", ".json", ".log", ".m", ".md", ".mm",
    ".py", ".rb", ".sh", ".swift", ".toml", ".txt", ".xml", ".yaml", ".yml",
}

HEIF_FILE_EXTENSIONS = {".heic", ".heif"}
HEIF_CONTENT_TYPES = {".heic": "image/heic", ".heif": "image/heif"}
IMAGE_PREVIEW_MAX_DIMENSION = 2560
IMAGE_THUMBNAIL_MAX_DIMENSION = 320


CSS = r"""
:root{color-scheme:light dark;--bg:#f4f7fb;--panel:rgba(255,255,255,.88);--text:#142033;--muted:#66758c;--line:#dce3ed;--brand:#1677ff;--brand2:#55a6ff;--danger:#d9363e;--shadow:0 20px 55px rgba(32,61,96,.13)}
@media(prefers-color-scheme:dark){:root{--bg:#0c111b;--panel:rgba(22,29,43,.88);--text:#eef4ff;--muted:#94a3b8;--line:#2b3548;--brand:#4c9aff;--brand2:#75b7ff;--danger:#ff6b72;--shadow:0 24px 70px rgba(0,0,0,.35)}}
*{box-sizing:border-box}body{margin:0;min-height:100vh;background:radial-gradient(circle at 10% 0,rgba(22,119,255,.16),transparent 28rem),var(--bg);color:var(--text);font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",sans-serif}.shell{width:min(1120px,calc(100% - 28px));margin:0 auto;padding:24px 0 56px}.top{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:18px}.brand{display:flex;align-items:center;gap:12px}.logo{display:grid;place-items:center;width:42px;height:42px;border-radius:13px;background:linear-gradient(145deg,var(--brand),var(--brand2));color:#fff;font-size:21px;font-weight:800;box-shadow:0 9px 28px rgba(22,119,255,.3)}h1{margin:0;font-size:22px}.sub{color:var(--muted);font-size:12px}.actions{display:flex;gap:8px;flex-wrap:wrap}.btn,a.btn{appearance:none;border:1px solid var(--line);background:var(--panel);color:var(--text);border-radius:10px;padding:9px 13px;text-decoration:none;cursor:pointer;font-weight:600}.btn:hover{border-color:var(--brand);color:var(--brand)}.btn.primary{border-color:transparent;background:var(--brand);color:#fff}.btn.danger{color:var(--danger)}.card{border:1px solid var(--line);border-radius:18px;background:var(--panel);box-shadow:var(--shadow);backdrop-filter:blur(18px);overflow:hidden}.hero{padding:22px}.crumbs{display:flex;gap:7px;align-items:center;flex-wrap:wrap;color:var(--muted);margin-bottom:14px}.crumbs a{color:var(--brand);text-decoration:none}.headline{display:flex;justify-content:space-between;gap:16px;align-items:flex-end}.headline h2{font-size:25px;margin:0 0 3px;word-break:break-all}.meta{color:var(--muted)}.upload{margin-top:18px;border:2px dashed color-mix(in srgb,var(--brand) 46%,var(--line));border-radius:15px;padding:22px;text-align:center;transition:.2s;background:color-mix(in srgb,var(--brand) 4%,transparent)}.upload.drag{transform:scale(1.006);border-color:var(--brand);background:color-mix(in srgb,var(--brand) 10%,transparent)}.upload strong{display:block;font-size:16px;margin-bottom:4px}.upload-controls{display:flex;justify-content:center;gap:8px;flex-wrap:wrap;margin-top:13px}.queue{display:grid;gap:8px;margin-top:13px;text-align:left}.job{padding:10px 12px;border:1px solid var(--line);border-radius:11px;background:color-mix(in srgb,var(--panel) 80%,transparent)}.jobline{display:flex;justify-content:space-between;gap:12px}.jobname{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.jobmeta{color:var(--muted);font-variant-numeric:tabular-nums;white-space:nowrap}.bar{height:5px;background:var(--line);border-radius:9px;margin-top:8px;overflow:hidden}.bar i{display:block;width:0;height:100%;background:linear-gradient(90deg,var(--brand),#63d4ff);transition:width .15s}.toolbar{padding:13px 17px;border-top:1px solid var(--line);border-bottom:1px solid var(--line);display:flex;gap:10px;align-items:center}.search,.sort,.chat input{min-width:0;border:1px solid var(--line);border-radius:10px;padding:9px 12px;background:transparent;color:var(--text);outline:none}.search{flex:1}.search:focus,.sort:focus,.chat input:focus{border-color:var(--brand)}.list{width:100%;border-collapse:collapse}.list th,.list td{padding:12px 17px;border-bottom:1px solid var(--line);text-align:left}.list th{font-size:12px;color:var(--muted);font-weight:600}.list tr:last-child td{border-bottom:0}.list tr:hover td{background:color-mix(in srgb,var(--brand) 4%,transparent)}.name{display:flex;align-items:center;gap:10px;min-width:0}.ico,.thumb{display:grid;place-items:center;width:40px;height:40px;border-radius:10px;background:color-mix(in srgb,var(--brand) 10%,transparent);font-size:17px;flex:0 0 40px}.thumb{object-fit:cover}.name a{color:var(--text);text-decoration:none;font-weight:650;word-break:break-all}.name a:hover{color:var(--brand)}.file-actions{display:flex;gap:7px;justify-content:flex-end;align-items:center}.file-actions a{color:var(--brand);text-decoration:none;font-weight:600}.file-actions button{border:0;background:none;color:var(--danger);cursor:pointer;font:inherit;font-weight:600;padding:0}.preview{padding:18px;border-top:1px solid var(--line);text-align:center}.preview img,.preview video,.preview iframe{max-width:100%;max-height:70vh;border:0;border-radius:12px}.preview audio{width:min(620px,100%)}.image-tools{display:flex;justify-content:center;align-items:center;gap:9px;margin-bottom:14px}.image-tools .btn{min-width:92px}.image-tools .btn:disabled{opacity:.36;cursor:not-allowed;border-color:var(--line);color:var(--muted)}.image-zoom-value{width:58px;color:var(--muted);font-variant-numeric:tabular-nums}.image-stage{overflow:auto;max-height:70vh;border-radius:12px}.image-canvas{display:grid;place-items:center;min-width:100%;min-height:280px}.image-stage img{box-shadow:0 12px 36px rgba(0,0,0,.18);transition:width .16s ease,height .16s ease}.image-viewer.zoomed .image-stage img{max-width:none;max-height:none}.image-pager{display:grid;grid-template-columns:120px 1fr 120px;align-items:center;gap:12px;margin-top:16px}.image-pager .btn{white-space:nowrap}.image-pager .disabled{opacity:.36;pointer-events:none}.image-count{color:var(--muted)}pre{text-align:left;overflow:auto;padding:16px;border-radius:12px;background:#0f172a;color:#dbeafe}.chat{margin-top:18px}.chat-head{padding:18px 20px 10px}.chat-messages{height:250px;overflow:auto;padding:8px 20px;display:grid;align-content:start;gap:9px}.chat-message{max-width:min(78%,620px);padding:9px 12px;border-radius:12px;background:color-mix(in srgb,var(--brand) 9%,var(--panel));word-break:break-word}.chat-meta{display:flex;gap:8px;color:var(--muted);font-size:11px;margin-bottom:3px}.chat-empty{color:var(--muted);text-align:center;padding:62px 12px}.chat-compose{display:grid;grid-template-columns:150px 1fr auto;gap:8px;padding:13px 20px 18px;border-top:1px solid var(--line)}.overlay{position:fixed;inset:0;display:none;place-items:center;padding:20px;background:rgba(0,0,0,.62);backdrop-filter:blur(6px);z-index:20}.overlay.show{display:grid}.modal{width:min(390px,100%);padding:22px;border:1px solid var(--line);border-radius:18px;background:var(--bg);box-shadow:var(--shadow);text-align:center}.modal img{width:min(280px,100%);background:#fff;border-radius:12px}.modal-url{margin:10px 0 16px;color:var(--muted);word-break:break-all}.empty{padding:42px;text-align:center;color:var(--muted)}.toast{position:fixed;left:50%;bottom:28px;transform:translate(-50%,20px);opacity:0;background:#101827;color:#fff;padding:10px 15px;border-radius:11px;transition:.2s;pointer-events:none;z-index:30}.toast.show{opacity:1;transform:translate(-50%,0)}
@media(max-width:700px){.shell{width:min(calc(100% - 16px),1120px);padding-top:12px}.top,.headline{align-items:flex-start;flex-direction:column}.top .actions{width:100%;display:grid;grid-template-columns:repeat(2,minmax(0,1fr))}.top .btn{width:100%;text-align:center}.hero{padding:16px}.toolbar{align-items:stretch;flex-direction:column}.list th:nth-child(2),.list td:nth-child(2),.list th:nth-child(3),.list td:nth-child(3),.list th:nth-child(4),.list td:nth-child(4){display:none}.list th,.list td{padding:11px}.file-actions{flex-direction:column}.upload{padding:18px 10px}.image-tools{flex-wrap:wrap}.image-canvas{min-height:180px}.image-pager{grid-template-columns:1fr 1fr}.image-count{grid-column:1/-1;grid-row:1}.chat-compose{grid-template-columns:1fr}.chat-message{max-width:92%}}
"""


JS = r"""
const $=(s,r=document)=>r.querySelector(s);const $$=(s,r=document)=>[...r.querySelectorAll(s)];
const fmt=n=>{let v=Number(n)||0,u=['B','KB','MB','GB','TB'],i=0;while(v>=1024&&i<u.length-1){v/=1024;i++}return `${v>=10||i===0?v.toFixed(0):v.toFixed(1)} ${u[i]}`};
function toast(t){const e=$('.toast');e.textContent=t;e.classList.add('show');clearTimeout(e._t);e._t=setTimeout(()=>e.classList.remove('show'),1800)}
async function sharePage(){if(navigator.share){await navigator.share({title:document.title,url:location.href})}else{await navigator.clipboard.writeText(location.href);toast('访问地址已复制')}}
async function copyPage(){try{await navigator.clipboard.writeText(location.href)}catch{const t=document.createElement('textarea');t.value=location.href;document.body.append(t);t.select();document.execCommand('copy');t.remove()}toast('当前链接已复制')}
function showQR(){const overlay=$('#qr-overlay'),url=location.href;$('#qr-image').src='/__qr?value='+encodeURIComponent(url);$('#qr-url').textContent=url;overlay.classList.add('show')}
function hideQR(){const overlay=$('#qr-overlay');overlay.classList.remove('show');$('#qr-image').src=''}
function filterRows(v){v=v.trim().toLowerCase();$$('[data-file-row]').forEach(r=>r.hidden=!r.dataset.name.includes(v))}
function sortRows(mode){$$('.list tbody').forEach(body=>{const rows=$$('[data-file-row]',body),parent=rows.find(r=>r.dataset.parent==='1'),items=rows.filter(r=>r!==parent);items.sort((a,b)=>{const ak=Number(a.dataset.kind),bk=Number(b.dataset.kind);if(ak!==bk)return ak-bk;if(mode==='size')return Number(b.dataset.size)-Number(a.dataset.size);if(mode==='time')return Number(b.dataset.time)-Number(a.dataset.time);return a.dataset.name.localeCompare(b.dataset.name,'zh-CN')});body.replaceChildren(...(parent?[parent]:[]),...items)})}
async function deleteUpload(button){const path=button.dataset.deletePath;if(!path||!confirm(`确定删除上传文件「${path}」？\n此操作不能撤销。`))return;const response=await fetch(button.dataset.endpoint+'?path='+encodeURIComponent(path),{method:'DELETE'});let data={};try{data=await response.json()}catch{}if(response.ok){toast('文件已删除');setTimeout(()=>location.reload(),500)}else toast(data.message||'删除失败')}
const imageViewer=$('[data-image-viewer]');
document.addEventListener('keydown',event=>{if(event.key==='Escape')hideQR();const tag=event.target?.tagName;if(['INPUT','TEXTAREA','SELECT'].includes(tag)||event.target?.isContentEditable)return;if(!imageViewer)return;const target=event.key==='ArrowLeft'?imageViewer.dataset.prev:event.key==='ArrowRight'?imageViewer.dataset.next:'';if(target){event.preventDefault();location.href=target}});
if(imageViewer){const stage=$('.image-stage',imageViewer),canvas=$('.image-canvas',imageViewer),image=$('img',canvas),zoomOut=$('[data-image-zoom-out]',imageViewer),zoomIn=$('[data-image-zoom-in]',imageViewer),zoomValue=$('[data-image-zoom-value]',imageViewer);let zoom=1,baseWidth=0,baseHeight=0;
 const measure=()=>{if(!image.complete||!image.naturalWidth)return false;image.style.width='';image.style.height='';canvas.style.width='';canvas.style.height='';const rect=image.getBoundingClientRect();baseWidth=rect.width;baseHeight=rect.height;return baseWidth>0&&baseHeight>0};
 const apply=next=>{if(!baseWidth&&!measure())return;const oldWidth=stage.scrollWidth||1,oldHeight=stage.scrollHeight||1,centerX=(stage.scrollLeft+stage.clientWidth/2)/oldWidth,centerY=(stage.scrollTop+stage.clientHeight/2)/oldHeight;zoom=Math.min(4,Math.max(.5,Math.round(next*100)/100));const width=Math.round(baseWidth*zoom),height=Math.round(baseHeight*zoom);imageViewer.classList.toggle('zoomed',zoom!==1);image.style.width=width+'px';image.style.height=height+'px';canvas.style.width=Math.max(stage.clientWidth,width)+'px';canvas.style.height=Math.max(stage.clientHeight,height)+'px';zoomValue.textContent=Math.round(zoom*100)+'%';zoomOut.disabled=zoom<=.5;zoomIn.disabled=zoom>=4;requestAnimationFrame(()=>{stage.scrollLeft=Math.max(0,centerX*stage.scrollWidth-stage.clientWidth/2);stage.scrollTop=Math.max(0,centerY*stage.scrollHeight-stage.clientHeight/2)})};
 zoomOut.addEventListener('click',()=>apply(zoom-.25));zoomIn.addEventListener('click',()=>apply(zoom+.25));image.addEventListener('load',measure);if(image.complete)measure();window.addEventListener('resize',()=>{if(zoom===1)measure()});
}
const upload=$('[data-upload]');
if(upload){const queue=$('.queue',upload),endpoint=upload.dataset.endpoint;let jobs=[];
 const pathOf=f=>f._path||f.webkitRelativePath||f.name;
 function add(files){for(const f of files){jobs.push({file:f,path:pathOf(f)})}render();pump()}
 function render(){queue.innerHTML='';jobs.forEach((j,i)=>{if(j.node)return;const n=document.createElement('div');n.className='job';n.innerHTML=`<div class="jobline"><span class="jobname"></span><span class="jobmeta">等待中</span></div><div class="bar"><i></i></div>`;$('.jobname',n).textContent=j.path;queue.append(n);j.node=n})}
 async function pump(){for(const j of jobs){if(j.started)continue;j.started=true;await send(j)}if(jobs.length&&jobs.every(j=>j.done&&j.ok)){toast('上传完成，正在刷新');setTimeout(()=>location.reload(),900)}else{setTimeout(()=>{jobs=jobs.filter(j=>!j.done);jobs.forEach(j=>j.node=null);render()},1600)}}
 function send(j){return new Promise(resolve=>{const x=new XMLHttpRequest(),started=performance.now();x.open('POST',endpoint+'?path='+encodeURIComponent(j.path));x.setRequestHeader('Content-Type','application/octet-stream');x.upload.onprogress=e=>{if(!e.lengthComputable)return;const pct=e.loaded/e.total*100,sec=Math.max((performance.now()-started)/1000,.01),speed=e.loaded/sec;$('.bar i',j.node).style.width=pct+'%';$('.jobmeta',j.node).textContent=`${pct.toFixed(0)}% · ${fmt(speed)}/s`};x.onload=()=>{j.done=true;j.ok=x.status===201;$('.jobmeta',j.node).textContent=j.ok?'完成':'失败';$('.bar i',j.node).style.width=j.ok?'100%':'0';if(!j.ok){try{toast(JSON.parse(x.responseText).message)}catch{toast('上传失败')}}resolve()};x.onerror=()=>{j.done=true;j.ok=false;$('.jobmeta',j.node).textContent='网络错误';resolve()};x.send(j.file)})}
 function walk(entry,prefix=''){return new Promise(resolve=>{if(entry.isFile){entry.file(f=>{f._path=prefix+f.name;resolve([f])},()=>resolve([]))}else if(entry.isDirectory){const reader=entry.createReader(),all=[];const next=()=>reader.readEntries(async es=>{if(!es.length){resolve(all);return}for(const e of es)all.push(...await walk(e,prefix+entry.name+'/'));next()},()=>resolve(all));next()}else resolve([])})}
 async function dropped(dt){const entries=[...dt.items].map(i=>i.webkitGetAsEntry?.()).filter(Boolean);if(!entries.length)return [...dt.files];const files=[];for(const entry of entries)files.push(...await walk(entry));return files}
 upload.addEventListener('dragover',e=>{e.preventDefault();upload.classList.add('drag')});upload.addEventListener('dragleave',()=>upload.classList.remove('drag'));upload.addEventListener('drop',async e=>{e.preventDefault();upload.classList.remove('drag');add(await dropped(e.dataTransfer))});
 $('[data-files]',upload).onchange=e=>add(e.target.files);$('[data-folder]',upload).onchange=e=>add(e.target.files);
 document.addEventListener('paste',e=>{const fs=[...e.clipboardData.files];if(fs.length){add(fs);toast(`已加入 ${fs.length} 个剪贴板文件`)}});
}
const chat=$('[data-chat]');
if(chat){const endpoint=chat.dataset.endpoint,list=$('.chat-messages',chat),nickname=$('[data-chat-nickname]',chat),input=$('[data-chat-input]',chat),send=$('[data-chat-send]',chat);let lastId=0,loading=false;nickname.value=localStorage.getItem('lanfileserver-chat-nickname')||'';
 const empty=()=>{if(!list.children.length){const node=document.createElement('div');node.className='chat-empty';node.textContent='还没有消息，打个招呼吧';list.append(node)}};
 const append=message=>{const placeholder=$('.chat-empty',list);if(placeholder)placeholder.remove();const node=document.createElement('div'),meta=document.createElement('div'),nick=document.createElement('strong'),time=document.createElement('span'),text=document.createElement('div');node.className='chat-message';meta.className='chat-meta';nick.textContent=message.nickname;time.textContent=new Date(Number(message.timestamp)*1000).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});text.textContent=message.message;meta.append(nick,time);node.append(meta,text);list.append(node);lastId=Math.max(lastId,Number(message.id)||0);list.scrollTop=list.scrollHeight};
 async function load(){if(loading)return;loading=true;try{const response=await fetch(endpoint+'?after='+lastId,{cache:'no-store'}),data=await response.json();for(const message of data.messages||[])append(message);empty()}catch{}finally{loading=false}}
 async function submit(){const message=input.value.trim(),name=nickname.value.trim()||'匿名用户';if(!message)return;localStorage.setItem('lanfileserver-chat-nickname',name);send.disabled=true;try{const response=await fetch(endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({nickname:name,message})}),data=await response.json();if(response.ok){input.value='';await load()}else toast(data.message||'消息发送失败')}catch{toast('消息发送失败')}finally{send.disabled=false;input.focus()}}
 send.addEventListener('click',submit);input.addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();submit()}});load();setInterval(load,3000);
}
"""


def safe_child(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def file_content_type(file_path: Path) -> str:
    content_type = HEIF_CONTENT_TYPES.get(file_path.suffix.lower()) or mimetypes.guess_type(file_path.name)[0]
    if not content_type and file_path.suffix.lower() in TEXT_FILE_EXTENSIONS:
        content_type = "text/plain"
    if content_type and content_type.startswith("text/") and "charset=" not in content_type.lower():
        return f"{content_type}; charset=utf-8"
    return content_type or "application/octet-stream"


def is_image_file(file_path: Path) -> bool:
    return file_content_type(file_path).startswith("image/")


def render_heif_preview(file_path: Path, max_dimension: int) -> bytes:
    if sys.platform == "darwin":
        handle = tempfile.NamedTemporaryFile("wb", delete=False, suffix=".jpg")
        output_path = Path(handle.name)
        handle.close()
        try:
            result = subprocess.run(
                ["sips", "-s", "format", "jpeg", "-s", "formatOptions", "85", "-Z", str(max_dimension), str(file_path), "--out", str(output_path)],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode or not output_path.stat().st_size:
                raise RuntimeError((result.stderr or result.stdout).strip() or "系统未能转换 HEIC 图片。")
            return output_path.read_bytes()
        finally:
            output_path.unlink(missing_ok=True)

    try:
        from PIL import Image, ImageOps
        from pillow_heif import register_heif_opener
    except ImportError as error:
        raise RuntimeError("缺少 HEIC 预览组件，请重新运行启动脚本安装依赖。") from error

    register_heif_opener(thumbnails=False)
    output = io.BytesIO()
    with Image.open(file_path) as source:
        image = ImageOps.exif_transpose(source)
        image.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
        image.convert("RGB").save(output, "JPEG", quality=85, optimize=True)
    return output.getvalue()


def content_disposition(disposition: str, filename: str) -> str:
    fallback = re.sub(r"[^A-Za-z0-9._ -]+", "_", filename).strip() or "download"
    fallback = fallback.replace("\\", "_").replace('"', "'")
    return f'{disposition}; filename="{fallback}"; filename*=UTF-8\'\'{urllib.parse.quote(filename)}'


def item_allows_upload(item: ShareItem) -> bool:
    return item.upload_allowed and item.path.is_dir()


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"


def modified_text(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")


def qr_svg(value: str) -> bytes:
    import qrcode
    from qrcode.image.svg import SvgPathImage

    image = qrcode.make(value, image_factory=SvgPathImage, box_size=8, border=3)
    output = io.BytesIO()
    image.save(output)
    return output.getvalue()


def sanitize_upload_path(value: str) -> Path:
    parts = []
    for raw in urllib.parse.unquote(value or "").replace("\\", "/").split("/"):
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", raw.strip())[:120]
        if name not in {"", ".", ".."}:
            parts.append(name)
    return Path(*parts) if parts else Path("upload.bin")


def unique_upload_path(target: Path) -> Path:
    if not target.exists():
        return target
    for index in range(1, 10000):
        candidate = target.with_name(f"{target.stem or 'upload'} ({index}){target.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError("同名文件过多，无法生成安全文件名。")


def quote_path(path: Path) -> str:
    return "/".join(urllib.parse.quote(part) for part in path.parts)


def build_path_archive(source: Path) -> Path:
    handle = tempfile.NamedTemporaryFile("wb", delete=False, suffix=".zip")
    target = Path(handle.name)
    handle.close()
    try:
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            if source.is_symlink():
                raise RuntimeError("不打包符号链接。")
            if source.is_file():
                archive.write(source, source.name)
            else:
                root = source.name or "folder"
                for child in sorted(source.rglob("*"), key=lambda value: str(value).lower()):
                    if child.is_symlink() or not safe_child(child, source):
                        continue
                    archive_name = str(Path(root) / child.relative_to(source)).replace("\\", "/")
                    archive.write(child, archive_name + "/" if child.is_dir() else archive_name)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return target


def page(title: str, body: str) -> bytes:
    document = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="color-scheme" content="light dark"><title>{html.escape(title)} · LANFileServer</title><style>{CSS}</style></head><body><main class="shell"><header class="top"><div class="brand"><div class="logo">L</div><div><h1>LANFileServer</h1><div class="sub">局域网高速文件传输</div></div></div><div class="actions"><button class="btn" onclick="copyPage()">复制链接</button><button class="btn" onclick="showQR()">显示二维码</button><button class="btn" onclick="sharePage()">系统分享</button><a class="btn" href="/">全部共享</a></div></header>{body}</main><div class="overlay" id="qr-overlay" onclick="if(event.target===this)hideQR()"><div class="modal"><img id="qr-image" alt="当前页面二维码"><div class="modal-url" id="qr-url"></div><button class="btn primary" onclick="hideQR()">关闭</button></div></div><div class="toast"></div><script>{JS}</script></body></html>'''
    return document.encode("utf-8")


def chat_html(item_id: int) -> str:
    endpoint = f"/items/{item_id}/__chat"
    return f'''<section class="card chat" data-chat data-endpoint="{endpoint}"><div class="chat-head"><div class="headline"><div><h2>局域网聊天</h2><div class="meta">同一共享项目内实时沟通 · 最近保留 200 条消息</div></div></div></div><div class="chat-messages"></div><div class="chat-compose"><input data-chat-nickname maxlength="20" placeholder="你的昵称"><input data-chat-input maxlength="2000" placeholder="输入消息，回车发送"><button class="btn primary" data-chat-send>发送</button></div></section>'''


def parse_range(value: str, size: int) -> Optional[tuple[int, int]]:
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", value.strip())
    if not match or size <= 0:
        return None
    left, right = match.groups()
    if not left:
        length = min(int(right or 0), size)
        return (size - length, size - 1) if length else None
    start = int(left)
    end = min(int(right), size - 1) if right else size - 1
    return (start, end) if 0 <= start <= end < size else None


class ShareHandler(BaseHTTPRequestHandler):
    """提供共享页面、上传以及 Python 临时模式下的文件流。"""

    server_version = "LANFileServerPython/2.0"

    def do_GET(self) -> None:
        self.serve_request(True)

    def do_HEAD(self) -> None:
        self.serve_request(False)

    def do_POST(self) -> None:
        if re.fullmatch(r"/items/\d+/__chat", urllib.parse.urlsplit(self.path).path):
            self.handle_chat_post()
        else:
            self.handle_upload()

    def do_DELETE(self) -> None:
        self.handle_delete()

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        manager = getattr(self.server, "manager", None)
        if manager and manager.record_requests and "__upload" not in urllib.parse.urlsplit(self.path).path:
            manager.record(self, str(code), str(size))

    def send_bytes(self, status: int, body: bytes, content_type: str, send_body: bool) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if send_body:
            self.wfile.write(body)

    def send_json(self, status: int, payload: dict[str, object]) -> None:
        self.send_bytes(status, json.dumps(payload, ensure_ascii=False).encode(), "application/json; charset=utf-8", True)

    def serve_request(self, send_body: bool) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == "/favicon.ico":
            self.send_response(204); self.end_headers(); return
        if parsed.path == "/__qr":
            self.send_qr(parsed, send_body); return
        if parsed.path in {"", "/"}:
            self.send_index(send_body); return
        match = re.match(r"^/items/(\d+)(?:/(.*))?$", parsed.path)
        manager = getattr(self.server, "manager", None)
        item = manager.items_by_id.get(int(match.group(1))) if match and manager else None
        if not match or not item or not item.path.exists():
            self.send_error(404); return
        extra = urllib.parse.unquote(match.group(2) or "")
        if extra == "__chat":
            self.send_chat(item, parsed); return
        if extra == "__preview" and item.path.is_file() and is_image_file(item.path):
            self.send_image_preview(item.path, parsed, send_body); return
        if extra.startswith("__preview/") and item.path.is_dir():
            target = item.path.joinpath(*[part for part in extra[10:].split("/") if part])
            if safe_child(target, item.path) and target.is_file() and is_image_file(target):
                self.send_image_preview(target, parsed, send_body); return
            self.send_error(404); return
        if extra == "__raw" and item.path.is_file():
            self.send_file(item.path, send_body, parsed.query); return
        if extra.startswith("__raw/") and item.path.is_dir():
            target = item.path.joinpath(*[part for part in extra[6:].split("/") if part])
            if safe_child(target, item.path) and target.is_file():
                self.send_file(target, send_body, parsed.query); return
            self.send_error(404); return
        if item.path.is_file():
            if extra == "__download": self.send_archive(item.path, send_body)
            elif extra: self.send_error(404)
            else: self.send_file_page(item, item.path, "", send_body)
            return
        if match.group(2) is None:
            self.send_response(302); self.send_header("Location", f"/items/{item.item_id}/"); self.end_headers(); return
        parts = [part for part in extra.split("/") if part]
        action = parts[-1] if parts and parts[-1] == "__download" else ""
        target_parts = parts[:-1] if action else parts
        target = item.path.joinpath(*target_parts)
        if not safe_child(target, item.path): self.send_error(403)
        elif action and target.exists(): self.send_archive(target, send_body)
        elif target.is_dir(): self.send_directory(item, target, Path(*target_parts), send_body)
        elif target.is_file(): self.send_file_page(item, target, Path(*target_parts), send_body)
        else: self.send_error(404)

    def send_qr(self, parsed: urllib.parse.SplitResult, send_body: bool) -> None:
        value = (urllib.parse.parse_qs(parsed.query).get("value") or [""])[0].strip()
        if not value or len(value) > 2048:
            self.send_error(400, "二维码内容无效。")
            return
        try:
            self.send_bytes(200, qr_svg(value), "image/svg+xml; charset=utf-8", send_body)
        except Exception as error:
            self.send_error(500, str(error))

    def send_chat(self, item: ShareItem, parsed: urllib.parse.SplitResult) -> None:
        manager = getattr(self.server, "manager", None)
        after_text = (urllib.parse.parse_qs(parsed.query).get("after") or ["0"])[0]
        after = int(after_text) if after_text.isdigit() else 0
        messages = manager.chat_since(item.item_id, after) if manager else []
        for message in messages:
            message.pop("ip", None)
        self.send_json(200, {"messages": messages})

    def send_index(self, send_body: bool) -> None:
        manager = getattr(self.server, "manager", None)
        rows = []
        for item in manager.items:
            href = f"/items/{item.item_id}/" if item.path.is_dir() else f"/items/{item.item_id}"
            download = f"/items/{item.item_id}/__download" if item.path.is_dir() else f"/items/{item.item_id}/__raw?download=1"
            stat = item.path.stat()
            thumbnail = f"/items/{item.item_id}/__preview?size=thumb" if item.path.is_file() and is_image_file(item.path) else ""
            rows.append(self.file_row(item.name, href, item.kind, stat.st_size if item.path.is_file() else None, download, stat.st_mtime, thumbnail=thumbnail))
        toolbar = '<div class="toolbar"><input class="search" placeholder="搜索共享项目" oninput="filterRows(this.value)"><select class="sort" onchange="sortRows(this.value)"><option value="name">名称排序</option><option value="time">最近修改</option><option value="size">文件大小</option></select></div>'
        body = f'<section class="card"><div class="hero"><div class="headline"><div><h2>全部共享</h2><div class="meta">{len(rows)} 个共享项目</div></div></div></div>{toolbar}{self.list_html(rows)}</section>'
        self.send_bytes(200, page("全部共享", body), "text/html; charset=utf-8", send_body)

    def send_directory(self, item: ShareItem, directory: Path, relative: Path, send_body: bool) -> None:
        rows = []
        try:
            children = sorted(directory.iterdir(), key=lambda value: (not value.is_dir(), value.name.lower()))
        except OSError as error:
            self.send_error(403, str(error)); return
        base = f"/items/{item.item_id}/" + (quote_path(relative) + "/" if relative.parts else "")
        if relative.parts:
            rows.append(self.file_row("../", "../", "上级目录", None, "", 0, parent=True))
        upload_root = item.path / UPLOAD_DIR_NAME
        for child in children:
            if child.name.endswith(".uploading"):
                continue
            href = base + urllib.parse.quote(child.name) + ("/" if child.is_dir() else "")
            raw = f"/items/{item.item_id}/__raw/{quote_path(child.relative_to(item.path))}"
            download = href + "__download" if child.is_dir() else raw + "?download=1"
            delete_path = ""
            if item_allows_upload(item) and not upload_root.is_symlink() and child.is_file() and safe_child(child, upload_root):
                delete_path = str(child.resolve().relative_to(upload_root.resolve())).replace("\\", "/")
            thumbnail = f"/items/{item.item_id}/__preview/{quote_path(child.relative_to(item.path))}?size=thumb" if child.is_file() and is_image_file(child) else ""
            stat = child.stat()
            rows.append(self.file_row(child.name + ("/" if child.is_dir() else ""), href, "文件夹" if child.is_dir() else "文件", stat.st_size if child.is_file() else None, download, stat.st_mtime, thumbnail, delete_path, item.item_id))
        upload = ""
        if item_allows_upload(item):
            upload = f'''<div class="upload" data-upload data-endpoint="/items/{item.item_id}/__upload"><strong>拖入文件或文件夹开始上传</strong><div class="meta">支持粘贴截图 · 实时速度 · 不覆盖同名文件 · 大小仅受磁盘空间限制</div><div class="upload-controls"><button class="btn primary" onclick="this.parentElement.querySelector('[data-files]').click()">选择文件</button><button class="btn" onclick="this.parentElement.querySelector('[data-folder]').click()">选择文件夹</button><input data-files type="file" multiple hidden><input data-folder type="file" webkitdirectory multiple hidden></div><div class="queue"></div></div>'''
        label = item.name if not relative.parts else f"{item.name}/{relative.as_posix()}"
        toolbar = '<div class="toolbar"><input class="search" placeholder="搜索当前目录" oninput="filterRows(this.value)"><select class="sort" onchange="sortRows(this.value)"><option value="name">名称排序</option><option value="time">最近修改</option><option value="size">文件大小</option></select></div>'
        body = f'''<section class="card"><div class="hero"><div class="crumbs"><a href="/">全部共享</a><span>/</span><span>{html.escape(label)}</span></div><div class="headline"><div><h2>{html.escape(directory.name or item.name)}</h2><div class="meta">{len(children)} 个项目</div></div><a class="btn primary" href="{base}__download">打包文件夹</a></div>{upload}</div>{toolbar}{self.list_html(rows)}</section>{chat_html(item.item_id)}'''
        self.send_bytes(200, page(label, body), "text/html; charset=utf-8", send_body)

    def file_row(self, name: str, href: str, kind: str, size: Optional[int], download: str, modified: float, thumbnail: str = "", delete_path: str = "", item_id: int = 0, parent: bool = False) -> str:
        icon = "📁" if "目录" in kind or kind == "文件夹" else "📄"
        visual = f'<img class="thumb" src="{html.escape(thumbnail)}" alt="" loading="lazy">' if thumbnail else f'<span class="ico">{icon}</span>'
        actions = f'<a href="{html.escape(download)}" download>下载</a>' if download else ""
        if delete_path:
            actions += f'<button data-delete-path="{html.escape(delete_path)}" data-endpoint="/items/{item_id}/__delete" onclick="deleteUpload(this)">删除</button>'
        kind_order = 0 if "目录" in kind or kind == "文件夹" else 1
        return f'''<tr data-file-row data-parent="{int(parent)}" data-kind="{kind_order}" data-name="{html.escape(name.lower())}" data-size="{size or 0}" data-time="{modified}"><td><div class="name">{visual}<a href="{html.escape(href)}">{html.escape(name)}</a></div></td><td>{html.escape(kind)}</td><td>{human_size(size) if size is not None else "—"}</td><td>{modified_text(modified) if modified else "—"}</td><td><div class="file-actions">{actions}</div></td></tr>'''

    @staticmethod
    def list_html(rows: list[str]) -> str:
        if not rows:
            return '<div class="empty">这里还没有文件</div>'
        return '<table class="list"><thead><tr><th>名称</th><th>类型</th><th>大小</th><th>更新时间</th><th></th></tr></thead><tbody>' + "".join(rows) + "</tbody></table>"

    def send_file_page(self, item: ShareItem, file_path: Path, relative: Path | str, send_body: bool) -> None:
        relative_path = Path(relative) if relative else Path(file_path.name) if item.path.is_dir() else Path()
        raw = f"/items/{item.item_id}/__raw" + ("/" + quote_path(relative_path) if relative_path.parts else "")
        content_type = file_content_type(file_path)
        image_file = is_image_file(file_path)
        preview_url = f"/items/{item.item_id}/__preview" + ("/" + quote_path(relative_path) if relative_path.parts else "") if image_file else raw
        navigation = self.image_navigation(item, file_path) if image_file else None
        preview = self.preview_html(file_path, preview_url, content_type, navigation)
        open_action = "" if image_file else f'<a class="btn" href="{html.escape(preview_url)}" target="_blank">查看</a>'
        body = f'''<section class="card"><div class="hero"><div class="crumbs"><a href="/">全部共享</a><span>/</span><span>{html.escape(file_path.name)}</span></div><div class="headline"><div><h2>{html.escape(file_path.name)}</h2><div class="meta">{html.escape(content_type)} · {human_size(file_path.stat().st_size)}</div></div><div class="actions">{open_action}<a class="btn primary" href="{raw}?download=1" download="{html.escape(file_path.name)}">下载原文件</a></div></div></div>{preview}</section>{chat_html(item.item_id)}'''
        self.send_bytes(200, page(file_path.name, body), "text/html; charset=utf-8", send_body)

    def image_navigation(self, item: ShareItem, file_path: Path) -> tuple[str, str, int, int]:
        images = [file_path]
        if item.path.is_dir():
            try:
                images = sorted(
                    (child for child in file_path.parent.iterdir() if child.is_file() and safe_child(child, item.path) and is_image_file(child)),
                    key=lambda child: child.name.casefold(),
                )
            except OSError:
                images = [file_path]
        current = file_path.resolve()
        index = next((position for position, image in enumerate(images) if image.resolve() == current), 0)

        def href(position: int) -> str:
            if not 0 <= position < len(images) or item.path.is_file():
                return ""
            return f"/items/{item.item_id}/{quote_path(images[position].relative_to(item.path))}"

        return href(index - 1), href(index + 1), index + 1, len(images)

    def preview_html(self, file_path: Path, preview_url: str, content_type: str, navigation: Optional[tuple[str, str, int, int]] = None) -> str:
        if content_type.startswith("image/"):
            previous, following, index, total = navigation or ("", "", 1, 1)
            previous_button = f'<a class="btn" href="{html.escape(previous)}">← 上一张</a>' if previous else '<span class="btn disabled">← 上一张</span>'
            following_button = f'<a class="btn" href="{html.escape(following)}">下一张 →</a>' if following else '<span class="btn disabled">下一张 →</span>'
            return f'''<div class="preview image-viewer" data-image-viewer data-prev="{html.escape(previous)}" data-next="{html.escape(following)}"><div class="image-tools"><button class="btn" type="button" data-image-zoom-out aria-label="缩小图片">－ 缩小</button><span class="image-zoom-value" data-image-zoom-value>100%</span><button class="btn" type="button" data-image-zoom-in aria-label="放大图片">放大 ＋</button></div><div class="image-stage"><div class="image-canvas"><img src="{html.escape(preview_url)}" alt="{html.escape(file_path.name)}"></div></div><div class="image-pager">{previous_button}<span class="image-count">{index} / {total} · 键盘 ← → 翻阅</span>{following_button}</div></div>'''
        if content_type.startswith("video/"): return f'<div class="preview"><video controls preload="metadata" src="{preview_url}"></video></div>'
        if content_type.startswith("audio/"): return f'<div class="preview"><audio controls preload="metadata" src="{preview_url}"></audio></div>'
        if content_type == "application/pdf": return f'<div class="preview"><iframe src="{preview_url}" width="100%" height="680"></iframe></div>'
        if (content_type.startswith("text/") or file_path.suffix.lower() in TEXT_FILE_EXTENSIONS) and file_path.stat().st_size <= PREVIEW_MAX_BYTES:
            return f'<div class="preview"><pre>{html.escape(file_path.read_text(encoding="utf-8", errors="replace"))}</pre></div>'
        return '<div class="empty">此类型不在页面内预读，避免大文件占用浏览器内存。</div>'

    def send_image_preview(self, file_path: Path, parsed: urllib.parse.SplitResult, send_body: bool) -> None:
        if file_path.suffix.lower() not in HEIF_FILE_EXTENSIONS:
            self.send_file(file_path, send_body)
            return
        size = (urllib.parse.parse_qs(parsed.query).get("size") or [""])[0]
        max_dimension = IMAGE_THUMBNAIL_MAX_DIMENSION if size == "thumb" else IMAGE_PREVIEW_MAX_DIMENSION
        try:
            body = render_heif_preview(file_path, max_dimension)
        except (OSError, RuntimeError, ValueError) as error:
            self.send_error(500, str(error))
            return
        self.send_bytes(200, body, "image/jpeg", send_body)

    def send_file(self, file_path: Path, send_body: bool, query: str = "") -> None:
        size = file_path.stat().st_size
        selected = parse_range(self.headers.get("Range", ""), size)
        start, end = selected or (0, max(size - 1, 0))
        length = end - start + 1 if size else 0
        self.send_response(206 if selected else 200)
        self.send_header("Content-Type", file_content_type(file_path))
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        if selected: self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        disposition = "attachment" if urllib.parse.parse_qs(query).get("download") == ["1"] else "inline"
        self.send_header("Content-Disposition", content_disposition(disposition, file_path.name))
        self.end_headers()
        if not send_body or not size: return
        with file_path.open("rb") as source:
            source.seek(start); remaining = length
            while remaining:
                chunk = source.read(min(UPLOAD_CHUNK_SIZE, remaining))
                if not chunk: break
                self.wfile.write(chunk); remaining -= len(chunk)

    def send_archive(self, source: Path, send_body: bool) -> None:
        archive: Optional[Path] = None
        try:
            archive = build_path_archive(source)
            self.send_file(archive, send_body, "download=1")
        except Exception as error:
            self.send_error(500, str(error))
        finally:
            if archive: archive.unlink(missing_ok=True)

    def handle_upload(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        match = re.fullmatch(r"/items/(\d+)/__upload", parsed.path)
        manager = getattr(self.server, "manager", None)
        item = manager.items_by_id.get(int(match.group(1))) if match and manager else None
        relative = sanitize_upload_path((urllib.parse.parse_qs(parsed.query).get("path") or [""])[0])
        if not item or not item_allows_upload(item):
            self.send_json(403, {"ok": False, "message": "这个项目没有开启上传。"}); return
        length_text = self.headers.get("Content-Length", "")
        if not length_text.isdigit() or int(length_text) <= 0:
            self.send_json(411, {"ok": False, "message": "缺少有效的 Content-Length。"}); return
        length = int(length_text)
        upload_root = item.path / UPLOAD_DIR_NAME
        if upload_root.is_symlink():
            self.send_json(403, {"ok": False, "message": "Uploads 不能使用符号链接。"}); return
        target_dir = upload_root / relative.parent
        target_dir.mkdir(parents=True, exist_ok=True)
        if not safe_child(target_dir, upload_root):
            self.send_json(403, {"ok": False, "message": "上传路径越界。"}); return
        free = shutil.disk_usage(target_dir).free
        if length + UPLOAD_FREE_SPACE_RESERVE > free:
            self.send_json(507, {"ok": False, "message": f"磁盘空间不足，需要 {human_size(length)}，可用 {human_size(free)}。"}); return
        target = unique_upload_path(target_dir / relative.name)
        temp = tempfile.NamedTemporaryFile("wb", delete=False, dir=target_dir, prefix=f".{target.name}.", suffix=".uploading")
        temp_path = Path(temp.name)
        remaining = length
        try:
            with temp:
                while remaining:
                    chunk = self.rfile.read(min(UPLOAD_CHUNK_SIZE, remaining))
                    if not chunk: raise RuntimeError("连接中断，上传未完成。")
                    temp.write(chunk); remaining -= len(chunk)
                temp.flush(); os.fsync(temp.fileno())
            temp_path.replace(target)
            self.send_json(201, {"ok": True, "name": str(target.relative_to(upload_root)), "size": length})
            manager.record_upload(self, "201", item, str(target.relative_to(upload_root)), str(length), str(target))
        except Exception as error:
            temp_path.unlink(missing_ok=True)
            self.send_json(500, {"ok": False, "message": str(error)})

    def handle_chat_post(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        match = re.fullmatch(r"/items/(\d+)/__chat", parsed.path)
        manager = getattr(self.server, "manager", None)
        item = manager.items_by_id.get(int(match.group(1))) if match and manager else None
        length_text = self.headers.get("Content-Length", "")
        if not item:
            self.send_json(404, {"ok": False, "message": "共享项目不存在。"}); return
        if not length_text.isdigit() or not 0 < int(length_text) <= CHAT_MAX_BODY_BYTES:
            self.send_json(413, {"ok": False, "message": "消息内容过大或为空。"}); return
        try:
            payload = json.loads(self.rfile.read(int(length_text)).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_json(400, {"ok": False, "message": "消息格式不正确。"}); return
        nickname = str(payload.get("nickname", "")).strip()[:20] or "匿名用户"
        message = str(payload.get("message", "")).strip()[:2000]
        if not message:
            self.send_json(400, {"ok": False, "message": "消息不能为空。"}); return
        entry = manager.add_chat(item.item_id, nickname, message, self.client_address[0])
        self.send_json(201, {"ok": True, "id": entry["id"]})

    def handle_delete(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        match = re.fullmatch(r"/items/(\d+)/__delete", parsed.path)
        manager = getattr(self.server, "manager", None)
        item = manager.items_by_id.get(int(match.group(1))) if match and manager else None
        if not item or not item_allows_upload(item):
            self.send_json(403, {"ok": False, "message": "这个项目没有开启上传文件管理。"}); return
        value = (urllib.parse.parse_qs(parsed.query).get("path") or [""])[0].replace("\\", "/")
        relative = Path(value)
        if not value or relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
            self.send_json(400, {"ok": False, "message": "删除路径无效。"}); return
        upload_root = item.path / UPLOAD_DIR_NAME
        if upload_root.is_symlink():
            self.send_json(403, {"ok": False, "message": "Uploads 不能使用符号链接。"}); return
        target = upload_root.joinpath(*relative.parts)
        if not safe_child(target, upload_root) or target.is_symlink() or not target.is_file():
            self.send_json(404, {"ok": False, "message": "只能删除 Uploads 目录内的普通文件。"}); return
        try:
            target.unlink()
            self.send_json(200, {"ok": True})
            manager.record_upload(self, "200", item, target.name, "0", f"删除：{target}")
        except OSError as error:
            self.send_json(500, {"ok": False, "message": str(error)})
