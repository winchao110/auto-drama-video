# -*- coding: utf-8 -*-
"""ComfyUI 直连调用层（只打官方 HTTP 接口，不做任何客户端封装）。

用到的接口：
  GET  /system_stats          探活
  POST /upload/image          上传参考图 / 参考音到 ComfyUI input 目录（该接口不校验扩展名）
  POST /prompt                提交 API 格式工作流，返回 prompt_id
  GET  /history/{prompt_id}   查询执行结果
  GET  /view?filename=...     下载产出文件

只依赖 Python 标准库，任何环境（含虚拟环境/裸机 Python）都能直接跑。

【硬约束 · 不要改】
1) 本模块**刻意不实现 `/free`（unload_models / free_memory）和 `/interrupt`**。
   MiniMax H3 一次加载要几十秒到几分钟，模型常驻显存后第二条起就没有加载开销。
   任何"跑完清一下显存""每条前重置一下"的改动都是负优化。
2) **视频一律先整批 POST 进队列，再统一收结果**（见 queue_many）。ComfyUI 会把
   队列里的任务连续执行，模型全程驻留，不会出现"每条都重新加载一次"的空档。
   不要退回"提交一条→等一条→再提交下一条"的串行写法。
"""
import json
import mimetypes
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


class ApiError(RuntimeError):
    pass


def normalize(addr):
    addr = (addr or "http://127.0.0.1:8188").strip().rstrip("/")
    if not addr.startswith("http"):
        addr = "http://" + addr
    return addr


def _call(addr, path, data=None, headers=None, method=None, timeout=60, raw=False):
    req = urllib.request.Request(normalize(addr) + path, data=data, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    # 本地/内网地址必须绕过系统代理，否则会被 HTTP_PROXY 拦成 502
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=timeout) as resp:
            body = resp.read()
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")
        except Exception:
            pass
        raise ApiError("HTTP %s %s -> %s\n%s" % (e.code, path, e.reason, detail[:4000]))
    except urllib.error.URLError as e:
        raise ApiError("连不上 ComfyUI（%s）：%s" % (normalize(addr), e.reason))
    if raw:
        return body
    return json.loads(body.decode("utf-8", "replace")) if body else None


def ping(addr):
    """返回 (是否在线, 详情)。"""
    try:
        d = _call(addr, "/system_stats", timeout=8)
        sysinfo = (d or {}).get("system") or {}
        return True, "ComfyUI 在线：%s / Comfy %s" % (
            sysinfo.get("os", "?"),
            ((d or {}).get("system") or {}).get("comfyui_version", "?"),
        )
    except Exception as e:
        return False, str(e)


def object_info(addr, class_type=None):
    """读节点定义（用来自查参考图槽位/输出口数量）。"""
    path = "/object_info" + ("/" + urllib.parse.quote(class_type) if class_type else "")
    return _call(addr, path, timeout=30) or {}


def upload_file(addr, filepath, subfolder="drama"):
    """上传任意文件到 ComfyUI input 目录。

    ComfyUI 的 /upload/image 接口不校验扩展名（server.py 里直接写文件），
    因此参考图、参考音都用它上传。
    """
    filepath = os.path.abspath(filepath)
    if not os.path.isfile(filepath):
        raise ApiError("文件不存在：%s" % filepath)
    filename = os.path.basename(filepath)
    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    boundary = "----dramaapi" + uuid.uuid4().hex
    with open(filepath, "rb") as f:
        blob = f.read()

    def part(name, value):
        return ('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n' % (boundary, name, value)).encode("utf-8")

    body = b"".join(
        [
            part("subfolder", subfolder or ""),
            part("type", "input"),
            part("overwrite", "true"),
            ('--%s\r\nContent-Disposition: form-data; name="image"; filename="%s"\r\nContent-Type: %s\r\n\r\n'
             % (boundary, filename, mime)).encode("utf-8"),
            blob,
            ("\r\n--%s--\r\n" % boundary).encode("utf-8"),
        ]
    )
    res = _call(
        addr,
        "/upload/image",
        data=body,
        headers={"Content-Type": "multipart/form-data; boundary=" + boundary},
        timeout=300,
    ) or {}
    name = res.get("name") or filename
    sub = res.get("subfolder") or ""
    return (sub + "/" + name) if sub else name


def upload_image(addr, filepath, subfolder="drama"):
    return upload_file(addr, filepath, subfolder)


def upload_audio(addr, filepath):
    """参考音放 input 根目录：LoadAudio 只按 input 目录里的相对名读取。"""
    return upload_file(addr, filepath, subfolder="")


def queue(addr, graph, client_id=None):
    payload = {"prompt": graph, "client_id": client_id or uuid.uuid4().hex}
    res = _call(
        addr,
        "/prompt",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        timeout=180,
    ) or {}
    if res.get("node_errors"):
        raise ApiError("工作流校验失败：%s" % json.dumps(res["node_errors"], ensure_ascii=False)[:3000])
    if not res.get("prompt_id"):
        raise ApiError("提交被拒绝：%s" % json.dumps(res, ensure_ascii=False)[:2000])
    return res["prompt_id"]


def history(addr, prompt_id):
    """返回某个 prompt 的执行记录（None 表示还没执行完）。"""
    return (_call(addr, "/history/" + prompt_id, timeout=60) or {}).get(prompt_id)


def queue_many(addr, graphs):
    """一次性把整批工作流 POST 进 ComfyUI 队列。

    ComfyUI 会按队列顺序连续执行，模型加载一次后常驻显存，
    这是避免"每条都重新加载模型"的关键。
    """
    ids = []
    for g in graphs:
        ids.append(queue(addr, g))
    return ids


def wait_one(addr, prompt_id, timeout=7200, poll=2.0, label=""):
    start = time.time()
    tick = 0
    while True:
        entry = history(addr, prompt_id)
        if entry:
            status = entry.get("status") or {}
            if status.get("status_str") == "error":
                raise ApiError("生成失败%s：%s" % (
                    "（%s）" % label if label else "",
                    json.dumps(status.get("messages") or [], ensure_ascii=False)[:3000],
                ))
            outputs = entry.get("outputs") or {}
            if outputs:
                return outputs
            if status.get("completed"):
                raise ApiError("执行完成但无输出%s" % ("（%s）" % label if label else ""))
        waited = time.time() - start
        if waited > timeout:
            raise ApiError("等待超时：%s（%.0f 秒）" % (label, waited))
        if waited - tick >= 20:
            tick = waited
            print("      仍在生成 %s %.0fs" % (label, waited), flush=True)
        time.sleep(poll)


def wait(addr, prompt_id, timeout=7200, poll=2.0, label="", verbose=True):
    return wait_one(addr, prompt_id, timeout=timeout, poll=poll, label=label)


def download(addr, item, dest):
    query = urllib.parse.urlencode({
        "filename": item.get("filename", ""),
        "subfolder": item.get("subfolder", ""),
        "type": item.get("type", "output"),
    })
    blob = _call(addr, "/view?" + query, timeout=1800, raw=True)
    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    with open(dest, "wb") as f:
        f.write(blob)
    return dest


def pick_image(outputs):
    for node_out in (outputs or {}).values():
        for key in ("images", "gifs"):
            for item in node_out.get(key) or []:
                if os.path.splitext(item.get("filename", ""))[1].lower() in (".png", ".jpg", ".jpeg", ".webp"):
                    return item
    return None


VIDEO_EXT = (".mp4", ".webm", ".mkv", ".mov")


def _first_video(node_out):
    for key in ("gifs", "videos", "images"):
        for item in node_out.get(key) or []:
            if os.path.splitext(item.get("filename", ""))[1].lower() in VIDEO_EXT:
                return item
    return None


def pick_video(outputs, prefer=None):
    """history.outputs 里挑一个视频文件。prefer 传保存节点 id 时以它为准，
    避免工作流里同时有别的导出节点时抓错文件。"""
    outputs = outputs or {}
    if prefer:
        item = _first_video(outputs.get(str(prefer)) or {})
        if item:
            return item
    for node_out in outputs.values():
        item = _first_video(node_out)
        if item:
            return item
    return None
