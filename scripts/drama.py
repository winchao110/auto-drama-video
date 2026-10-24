# -*- coding: utf-8 -*-
"""短剧工作台 CLI：drama.json 是唯一事实源，workbench.html 是人机桥梁。

流程只有三段（不再有"剧本"环节，读小说直接出提示词）：
  1) 提示词   读完小说 → 分段 H3 提示词（英文正文 + 中文对照）+ 资产提示词 + 视频简介
  2) 资产图   Qwen-Image 2.1 出人物 / 场景 / 道具设定图
  3) 视频     MiniMax H3 Ref2VA 全参考模式，整批入队生成 → 拼接成片

子命令
  init    新建项目（drama.json + workbench.html + assets/ + videos/ + voices/）
  build   从 drama.json 重建 workbench.html
  serve   起本地桥接服务（浏览器里改完点保存 → 直接写回 drama.json）
  images  逐个生成资产图
  videos  整批入队生成视频（默认一次性 POST 全部任务，模型常驻显存）
  voices  参考音库：列出 / 导入 / 删除
  status  查看进度 / ComfyUI 是否在线
  check   交付前自检

H3 时长口径：提示词里写 sec 秒，真正传给 API 的是 round(sec * 5 / 6)（恒定少 1/6）。
生成全部走 ComfyUI 官方 HTTP 接口（见 comfy_api.py），不依赖任何第三方库。
"""
import argparse
import base64
import copy
import glob
import hashlib
import json
import math
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import comfy_api

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WF_DIR = os.path.join(SKILL_DIR, "references", "workflows")
TPL_PATH = os.path.join(SKILL_DIR, "assets", "workbench.template.html")
CAMERA_PATH = os.path.join(SKILL_DIR, "references", "camera-moves.json")


def load_camera_moves():
    """运镜目录（44 条）：id → {zh, en, cat, size, need, lora, when, sentence, fallback}。

    数据源是 references/camera-moves.json，脚本和文档共用一份，改运镜只改那个文件。
    size = near / mid（原来的 wide 已并入 mid，不再单列全景）；
    need = native 表示不用 LoRA，lora 表示有专用运镜 LoRA（lora 里按顺序找本机存在的那个）。
    档位（四档，见 06-camera-moves.md）：T0 导演钦点 / T1 近景 / T2 中景 / T3 本机缺文件。
    """
    try:
        with open(CAMERA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        print("[!] 运镜目录读不出来（%s）：%s" % (CAMERA_PATH, e), flush=True)
        return {}
    return {str(m.get("id")): m for m in data if isinstance(m, dict) and m.get("id")}


CAMERA_MOVES = load_camera_moves()


def _lora_base(name):
    """LoRA 比对只看文件名：ComfyUI 回的是 MiniMaxH3\\xxx.safetensors 这种带子目录的路径，
    而运镜目录里只写文件名，子目录大小写在不同机器上也不一致——所以一律按 basename 小写比。"""
    return str(name or "").replace("/", "\\").split("\\")[-1].strip().lower()


def camera_lora_for(move_id, avail=None, catalog=None):
    """给一个运镜挑 LoRA：返回 (真实 lora_name, 强度, 触发词, 档位) 或 None。

    规则（用户钦定）：
      · 运镜本身不需要 LoRA → None（走原生；档位只看景别：近景 T1 / 中景 T2）
      · 需要 LoRA：按候选顺序找本机**真实存在**的那个 → 用它（近景 T1 / 中景 T2）
      · 一个都不存在 → None，档位 T3（不挂 LoRA，用降级提示词写）
    这里返回的 tier 只是「按景别的基准档」，导演钦点（camera.lead）由 camera_tier 补成 T0。

    avail = 本机 LoRA 名字列表（可带子目录，来自 ComfyUI）；None = 不检查（干跑，默认当有）。
    主名按 basename 精确匹配；aliases 里的写的是**同功能替代品**（例如 orb360 顶替 flf2v_lora），
    按 basename 包含匹配，别名可以写成 "文件名.token|触发词"。
    返回值用的是 avail 里的真实路径，否则 ComfyUI 会找不到文件。
    """
    cat = catalog if catalog is not None else CAMERA_MOVES
    mv = cat.get(str(move_id or ""))
    if not mv or mv.get("need") != "lora":
        return None
    tier = "T1" if mv.get("size") == "near" else "T2"
    real = {_lora_base(x): x for x in (avail or [])}
    bases = sorted(real)
    for cand in mv.get("lora") or []:
        strength = float(cand.get("strength") or 1.0)
        prim = cand.get("name") or ""
        if prim:
            if avail is None:
                return (prim, strength, (cand.get("trigger") or "").strip(), tier)
            hit = real.get(_lora_base(prim))
            if hit:
                return (hit, strength, (cand.get("trigger") or "").strip(), tier)
        for alias in cand.get("aliases") or []:
            an, _, at = str(alias).partition("|")
            tok = _lora_base(an)
            if not tok:
                continue
            trig = at.strip() or (cand.get("trigger") or "").strip()
            if avail is None:
                return (an, strength, trig, tier)
            for b in bases:
                if tok in b:
                    return (real[b], strength, trig, tier)
    return None


def camera_tier(move_id, avail=None, catalog=None, lead=False):
    """运镜档位（2026-10-24 用户口径，四档，从高到低）：

      T0 导演钦点   —— 模型按「戏眼→站位→能量走向」判定这场戏必须靠这个运镜，`camera.lead = true`；
                       与景别无关，近景中景都可能是 T0；本机有 LoRA 必挂。
      T1 近景       —— size == near；本机有 LoRA 必挂。
      T2 中景       —— size == mid（原来的全景已并入）；不需要 LoRA 的不挂，需要且本机有的挂。
      T3 本机缺文件 —— 需要 LoRA 但本机没有：不挂、不写触发词，改用目录里的 fallback 降级句。

    T3 优先于 T0/T1/T2：钦点了但本机没文件，照样按 T3 处理（check 会提示换等价原生运镜）。
    """
    cat = catalog if catalog is not None else CAMERA_MOVES
    mv = cat.get(str(move_id or ""))
    if not mv:
        return ""
    if mv.get("need") == "lora" and not camera_lora_for(move_id, avail, cat):
        return "T3"
    if lead:
        return "T0"
    return "T1" if mv.get("size") == "near" else "T2"


def camera_of(seg):
    """取本段的运镜设定。老项目没有这个字段 → 返回空 dict（= 不设计运镜，按原来的写法走）。"""
    c = seg.get("camera")
    if isinstance(c, dict):
        return c
    if isinstance(c, str):          # 手写成一个 id 也认
        return {"move": c}
    return {}


def camera_lead(seg):
    """这一段的运镜是不是「导演钦点」（T0）。人也能在页面上勾。"""
    c = camera_of(seg)
    v = c.get("lead")
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "y", "t0")
    return bool(v)


def motion_trigger_text(move_id, lora_name, catalog=None):
    """本段运镜 LoRA 要加在提示词最前面的触发词；没挂 LoRA 或这个 LoRA 没触发词 → 空串。"""
    if not lora_name:
        return ""
    pick = camera_lora_for(move_id, [lora_name], catalog)
    return pick[2] if pick else ""

# ---- 工作流模板里需要改动的节点（改模板时同步这里）----
# 生图只剩一条工作流：Qwen-Image 2.1（turbo 6 步版已删除）；采样步数由 settings.imgSteps 覆盖
Q_WF = {"quality25": "qwen-image21.quality25.api.json"}
Q_NODE = {"prompt": "517", "latent": "514", "seed": "524", "save": "508",
          "unet": "523", "clip": "518", "vae": "519", "steps": "515"}
# H3 工作流：MiniMax-H3 原生 Ref2VA（2026-10-23 换用户导出的「API 专用」版，19:23 那一版含 LowVRAMAttention）。
# 全部是 ComfyUI 本体自带的 H3 节点：没有二采高清、没有 VEDA、没有分块解码 / 人脸精修。
# 采样链 192 → 53 → 400 →[490 可选]→ 333 →[332 可选]→ 331 → 401 → 403 → 329 →{261,408}；宽高由 252 ResolutionSelector 算。
# 53 / 400 / 490 就是页面上的三个 LoRA 位置，空着的那格整颗摘掉，链条自动接回去。
H3_WF = "minimax-h3.ref2va.api.json"
H3_WF_TAG = "native-ref2va-20261023b"   # 换工作流时改这个，老项目会自动对齐一次
H3_NODE = {"prompt": "424", "promptKey": "value",
           "core": "413", "res": "252", "duration": "259", "steps": "261", "seed": "407", "save": "417",
           "refs": "421", "audios": "414",
           "unet": "192", "lora": "53", "lora2": "400", "lora3": "490", "motionLora": "491",
           "clip": "38", "videoVae": "36", "audioVae": "37",
           "sparse": "332", "attn": "331", "chunkff": "401", "lowvram": "403"}
# 三个 LoRA 位置的节点 id，顺序即串联顺序。前两个在模板里（53 / 400），
# 第三个（490）模板里没有，由 video_graph() 按 400 复制一颗出来，只在该格挂了 LoRA 时才留在图上。
H3_LORA_NODES = (H3_NODE["lora"], H3_NODE["lora2"], H3_NODE["lora3"])
# 宽高比 → ResolutionSelector 的 aspect_ratio 枚举（值必须与 ComfyUI 节点定义逐字一致）
H3_RATIO_OPTS = {
    "1:1": "1:1 (Square)",
    "2:3": "2:3 (Portrait Photo)",
    "3:2": "3:2 (Photo)",
    "3:4": "3:4 (Portrait Standard)",
    "4:3": "4:3 (Standard)",
    "9:16": "9:16 (Portrait Widescreen)",
    "16:9": "16:9 (Widescreen)",
    "21:9": "21:9 (Ultrawide)",
}
# 参考图 / 参考音挂到 Ref2VA 节点上的槽位上限（节点定义：ref_image 0–9，ref_audio 0–3）
REF_IMAGE_SLOTS = 9
# 参考音：TaiYangMultiAudioLoader(414) 多路输出，接到 MiniMaxH3ReferenceToVideo 的 ref_audio_0..2
AUDIO_NODE = []
AUDIO_SLOTS = 3
# ModelAttentionBackend(331) 的注意力后端：只这两档，值必须与节点定义逐字一致
H3_ATTN_OPTS = ["comfy kitchen attention", "pytorch attention"]
DEFAULT_H3_ATTN = "comfy kitchen attention"
H3_ATTN_NOTE = {
    "comfy kitchen attention": "Comfy Kitchen 量化 INT8 注意力（快、省显存，N 卡/A 卡可用，默认）",
    "pytorch attention": "PyTorch 原生注意力（最稳、最兼容，慢一些）",
}
# MiniMaxChunkFeedForward(401)：把前馈层切成 chunks 份算，序列超过 seq_threshold 才分块
DEFAULT_H3_CHUNKS = 2
DEFAULT_H3_SEQ_THRESHOLD = 4096
# MiniMaxLowVRAMAttention(403)：注意力按头分成 head_chunks 份算，降显存峰值
DEFAULT_H3_HEAD_CHUNKS = 4
# 块稀疏注意力 BlockSparseAttention(332)：页面只给一个开关，节点内部参数（sol-attn / τ=1.3 等）保持模板原值
DEFAULT_H3_SPARSE = True
DEFAULT_H3_MODEL = "MiniMaxH3\\minimax_h3_hybrid_fl2va_ref2va_b25-49-int8.safetensors"
DEFAULT_H3_LORA = "MiniMaxH3\\minimax_h3_dmad_full_dareties_v4_step600_comfy_fro.safetensors"
# 视频 LoRA 做成三个独立位置：1 号位默认挂主 LoRA（dmad_v4），2、3 号位默认「不挂」，页面上由人自选。
# 三条按 1 → 2 → 3 顺序串联在 unet 与 SigmaShift 之间；哪一格空着就把那颗节点整颗从链上摘掉。
H3_LORA_SLOTS = 3
DEFAULT_H3_LORA_STRENGTH = 0.8          # 1 号位强度默认（dmad_v4 step600 蒸馏 LoRA）
DEFAULT_H3_LORA_SLOT_STRENGTH = 0.75    # 2、3 号位强度默认：选上 LoRA 但没填强度时用它
DEFAULT_H3_CLIP = "MinimaxH3\\qwen3vl_32b_minimax_h3_int8_convrot.safetensors"
DEFAULT_H3_VIDEO_VAE = "minimax_h3_video_vae_int8_convrot.safetensors"
DEFAULT_H3_AUDIO_VAE = "minimax_h3_audio_vae_fp32.safetensors"

# 生图（Qwen-Image 2.1）默认三件套 + 默认采样步数
DEFAULT_IMG_UNET = "Qwen-Image\\qwen_image_2.1_int8_convrot.safetensors"
DEFAULT_IMG_CLIP = "Qwen-Image\\qwen3vl_8b_int8_convrot.safetensors"
DEFAULT_IMG_VAE = "Qwen-Image\\qwen_image_2.1_vae_bf16.safetensors"
DEFAULT_IMG_STEPS = 25          # 生图采样步数，工作台「生图参数 → 步数」可改（整数）
# 上一代工作流的默认值：老项目里仍是这些值时，随新工作流自动对齐一次
LEGACY_H3_LORA = "MiniMaxH3\\minimax_h3_dmad_full_dareties_v4_step600_comfy_fro.safetensors"
LEGACY_H3_LORAS = (
    "MiniMaxH3\\minimax_h3_turbo_v4_step600_ema_pruned_comfyui.safetensors",
    "MiniMaxH3\\minimax_h3_turbo_v4_step600_comfyui_lar-convert.safetensors",
)
LEGACY_H3_STEPS = 4
DEFAULT_H3_STEPS = 5
# 新工作流里已经不存在的设置项：老项目里残留的话，加载时统一清掉，页面不再显示
# （h3Attn 这一项保留：新版变成了 ModelAttentionBackend 的注意力后端下拉，枚举与旧版完全不同）
H3_RETIRED_KEYS = ("h3Hd", "h3HdMegapixels", "h3Veda")
SEED_MODES = ("fixed", "increment", "decrement", "randomize")

# 音色只有两条路，二者互斥，都由 sync_voice_tags() 写进对应 <Subject K> 段末尾：
#   ① 用了参考音频 → 写 <Audio N> 句（H3 里 ref_audio_0..2 对应 <Audio 1>..<Audio 3>，1 起数）
#   ② 没用参考音频 → 写"固定音色提示词"句（来自 assets[].voicePrompt，整部剧同一句）
# 两句都是"机器管理的句子"：换音色 / 换参考音 / 撤掉 时先按原文删掉再插新的，不会叠加。
AUDIO_TAG_EN = (
    "<Audio {n}> is the voice-timbre reference for <Subject {s}> (S{s}), containing a spoken Chinese "
    "vocal layer; inherit its timbre alone — vocal texture, pitch and speaking pace — and never its "
    "recorded words, dialogue or content. This same voice is used for <Subject {s}> in every shot "
    "of the whole drama."
)
AUDIO_TAG_ZH = (
    "<Audio {n}> 是 <Subject {s}> 的音色参考：仅继承其音色（音质、音高、语速），"
    "不继承、不参考这段参考音里的台词与内容；整部剧的每一个镜头，<Subject {s}> 都用这一种音色。"
)

VOICE_PROMPT_EN = (
    "<Subject {s}> keeps one fixed voice for the whole drama: {v} "
    "This same voice is used in every shot of the drama and never changes."
)
VOICE_PROMPT_ZH = (
    "<Subject {s}> 在整部剧里只使用一种固定音色：{v}"
    "这个音色在任何镜头、任何场景中都不改变。"
)

# 旧版模板里写在 <Subject K> 段内的两句机器句：新版一律不要，build 时自动清掉。
#   EN: "<Subject1>, S1 is always the speaker. S1 always uses one fixed voice: ..."
#   ZH: "<Subject1>，S1 永远是说话人。S1 始终使用一种固定的声音：..."
RE_SPEAKER_LEGACY = re.compile(r"[，,]\s*S(\d+)\s*(?:永远是说话人|is always the speaker)[。.]?[ \t]*")
RE_VOICE_LEGACY_EN = re.compile(r"S(\d+)\s+always uses one fixed voice\s*[:：]\s*(.+)", re.S)
RE_VOICE_LEGACY_ZH = re.compile(r"S(\d+)\s*始终使用一种固定的声音\s*[:：]\s*(.+)", re.S)

ASPECTS = ["16:9", "9:16", "4:3", "3:4", "1:1", "21:9"]
TYPE_MP = {"character": 2.0, "scene": 2.0, "prop": 2.0}
TYPE_RATIO = {"character": "4:3", "scene": "16:9", "prop": "1:1"}
AUDIO_EXT = (".wav", ".mp3", ".flac", ".m4a", ".ogg", ".aac", ".opus")

# 人物定设图模板：默认值。项目里可在工作台「生图参数」页改（存 settings.charSheet），
# 改过之后每个项目各自保留自己的版本，不受这里影响。
CHAR_BLOCK = (
    "A 4:3 professional studio realistic portrait against a clean pale grey-white solid background, composed as "
    "one joined composite. On the left of the frame, a large close-up of the face. In the middle, a headless "
    "full-body view of the same person, cut off flat at the neck, no head, upper body and lower body and the feet "
    "all visible. On the right, a rear view of the same person with the head, head and upper body and lower body, "
    "the shoulder line sitting level with the left view. Lighting and colour grading are completely unified across "
    "the whole composite. Ultra high definition, 8K, sharp focus, realistic portrait photography, clean background."
)
CHAR_BLOCK_ZH = (
    "画面比例 4：3，专业影棚写实肖像，干净浅灰白色纯色背景，拼接构图：画面左侧是大幅脸部特写，"
    "中间是同一个人物的无头全身像，颈部平整截断，无头，有上身，有下身，有脚。"
    "画面右侧是同一人物的有头背面照，有头，有上身，有下身，肩膀与左侧视图齐平。"
    "光影色调完全统一。超高清，8K，锐利对焦，写实人像摄影，干净背景。"
)
SCENE_BLOCK = (
    "The frame is a wide empty establishing view of this space from eye level, the whole room readable in one shot, "
    "the lower third kept clear of furniture so figures can be placed there later, and nothing important cropped at the "
    "edges. The lighting is even and readable across the whole room, with no blown highlights and no crushed blacks."
)
PROP_BLOCK = (
    "The frame is a single-object product view centred on a seamless pure white background, the object complete and "
    "fully inside the frame with even margins around it, nothing else in the shot, no person and no hands. The lighting "
    "is even product-table light from above and from both sides, showing material and wear without hard shadows."
)

# 参考音空库时的默认槽位：不绑音频也能选，只是暂时不会被当成声音参考
DEFAULT_VOICES = [
    {"id": "v1", "name": "低沉男中音 · 压抑克制", "gender": "男", "age": "30-40", "desc": "胸腔共鸣重，语速偏慢，句尾下压", "file": ""},
    {"id": "v2", "name": "冷硬男声 · 中年权威", "gender": "男", "age": "45-55", "desc": "颗粒感强，音量不大但穿透力强", "file": ""},
    {"id": "v3", "name": "清冷女声 · 倔强", "gender": "女", "age": "22-30", "desc": "偏冷偏薄，咬字干脆，情绪压着", "file": ""},
    {"id": "v4", "name": "沙哑男声 · 老年", "gender": "男", "age": "55+", "desc": "气声多，尾音发虚，带喘", "file": ""},
    {"id": "v5", "name": "粗豪男声 · 壮年", "gender": "男", "age": "30-40", "desc": "大嗓门，直给，带方言尾调", "file": ""},
    {"id": "v6", "name": "温润女声 · 青年", "gender": "女", "age": "20-28", "desc": "音色偏软，语速中等，气息轻", "file": ""},
]


# ---------------------------------------------------------------- 基础
def now_str():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def die(msg, code=1):
    print("\n[×] " + msg, flush=True)
    sys.exit(code)


def safe_id(s):
    return re.sub(r"[^0-9A-Za-z_\-]+", "_", str(s or "item"))


def paths(proj):
    proj = os.path.abspath(proj)
    return {
        "proj": proj,
        "json": os.path.join(proj, "drama.json"),
        "html": os.path.join(proj, "workbench.html"),
        "assets": os.path.join(proj, "assets"),
        "videos": os.path.join(proj, "videos"),
        "voices": os.path.join(proj, "voices"),
        "log": os.path.join(proj, ".run.log"),
    }


def sanitize_name(name):
    """剧名 → 文件夹名：去掉 Windows 非法字符，保留中文。"""
    t = re.sub(r'[\\/:*?"<>|\r\n\t]+', "", str(name or "")).strip().strip(".")
    return t or "未命名短剧"


def _detect_comfy_roots():
    """从正在跑的 ComfyUI 进程里反推安装目录（Windows）。"""
    if os.name != "nt":
        return []
    try:
        ps = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*main.py*' } | "
              "Select-Object -ExpandProperty CommandLine")
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                             capture_output=True, text=True, timeout=25).stdout or ""
    except Exception:
        return []
    roots = []
    for m in re.findall(r"([A-Za-z]:\\[^\s\"]*?main\.py)", out):
        d = os.path.dirname(m.rstrip("\\"))
        if d and d not in roots:
            roots.append(d)
    return roots


def comfy_output_root():
    """找 ComfyUI 的 output 目录：环境变量 → 技能 config.json → 扫进程。"""
    for k in ("DRAMA_COMFY_OUTPUT", "COMFYUI_OUTPUT"):
        v = os.environ.get(k)
        if v and os.path.isdir(v):
            return os.path.abspath(v)
    cfg = os.path.join(SKILL_DIR, "config.json")
    if os.path.isfile(cfg):
        try:
            d = json.load(open(cfg, encoding="utf-8"))
            v = (d.get("comfyOutput") or "").strip()
            if v and os.path.isdir(v):
                return os.path.abspath(v)
        except Exception:
            pass
    for root in _detect_comfy_roots():
        cand = os.path.join(root, "output")
        if os.path.isdir(cand):
            return cand
    return ""


# 模型列表不再做服务端缓存：工作台每次打开 / 切页 / 点刷新都向 ComfyUI 现读，
# 这样下拉里不会出现已经被删掉的模型（旧值由前端 alignModels 自动切到可用项）。


def comfy_models(addr, force=True):
    """从已连接的 ComfyUI 现读可选模型，全部按它自己的 models 目录给选项：
       unet  = models/diffusion_models（H3 主模型 + 生图 UNet 同一目录，两处合并去重）
       lora  = models/loras
       clip  = models/text_encoders（CLIPLoader 的 clip_name）
       vae   = models/vae（VAELoader 的 vae_name，视频 VAE / 音频 VAE / 生图 VAE 都取自这里）
    不缓存：每次打开页面 / 切页 / 点刷新都重新读一遍，避免下拉里出现已经删掉的模型。
    force 参数只为兼容老调用保留，行为上永远现读。
    """
    data = {"unet": [], "lora": [], "clip": [], "vae": [], "error": "",
            "ts": time.strftime("%H:%M:%S")}

    def combo(node, key):
        info = comfy_api.object_info(addr, node) or {}
        spec = (((info.get(node) or {}).get("input") or {}).get("required") or {}).get(key) or []
        opts = spec[0] if spec and isinstance(spec[0], list) else []
        return [str(x) for x in opts]

    try:
        data["unet"] = combo("UNETLoader", "unet_name")
        data["lora"] = combo("LoraLoaderModelOnly", "lora_name")
        data["clip"] = combo("CLIPLoader", "clip_name")
        data["vae"] = combo("VAELoader", "vae_name")
    except Exception as e:
        data["error"] = str(e)[:200]
    return data


def downloads_dir():
    """系统「下载」目录。优先序：环境变量 → 技能 config.json → 注册表 → ~/Downloads → 家目录。"""
    for k in ("DRAMA_PROJECT_ROOT", "DRAMA_DOWNLOAD_DIR"):
        v = os.environ.get(k)
        if v and os.path.isdir(v):
            return os.path.abspath(v)
    cfg = os.path.join(SKILL_DIR, "config.json")
    if os.path.isfile(cfg):
        try:
            d = json.load(open(cfg, encoding="utf-8"))
            v = (d.get("projectRoot") or "").strip()
            if v and os.path.isdir(v):
                return os.path.abspath(v)
        except Exception:
            pass
    if os.name == "nt":
        # 真实的下载目录可能被用户改到别的盘，注册表里才是准的
        try:
            import winreg
            key = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
                v, _ = winreg.QueryValueEx(k, "{374DE290-123F-4565-9164-39C4925E467B}")
            v = os.path.expandvars(v)
            if v and os.path.isdir(v):
                return os.path.abspath(v)
        except Exception:
            pass
    for name in ("Downloads", "下载"):
        d = os.path.join(os.path.expanduser("~"), name)
        if os.path.isdir(d):
            return os.path.abspath(d)
    return os.path.abspath(os.path.expanduser("~"))


def default_project_dir(title):
    """项目默认落在系统「下载」目录/<剧名>-<日期>/，html、图、视频全在里面。"""
    root = downloads_dir()
    if not root:
        return "", ""
    folder = "%s-%s" % (sanitize_name(title), time.strftime("%Y%m%d"))
    return os.path.join(root, folder), root


def open_in_explorer(path):
    """用系统的文件管理器打开一个目录（Windows = 资源管理器）。"""
    path = os.path.abspath(path)
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)
    if os.name == "nt":
        os.startfile(path)  # noqa: S606 —— Windows 专用，直接交给 shell
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])
    return path


def h3_frames(sec):
    """复刻工作流里的 ComfyMathExpression：max(5, round(a*24)) + (5 - (n % 17)) % 17。"""
    n = max(5, int(math.floor(float(sec) * 24 + 0.5)))
    return n + (5 - (n % 17)) % 17


def gen_sec(sec):
    """H3 实传时长：提示词写 sec 秒，API 恒定少 1/6，四舍五入取整，下限 5 秒。"""
    try:
        v = float(sec or 8)
    except Exception:
        v = 8.0
    return int(max(5, min(15, math.floor(v * 5.0 / 6.0 + 0.5))))


def pick_seeds(base, n, mode):
    """按"生成后控制"给一批任务算种子，并返回下一轮的基础种子。base<=0 视为随机。"""
    import random
    mode = mode if mode in SEED_MODES else "fixed"
    try:
        b = int(base)
    except Exception:
        b = 0
    if mode == "randomize" or b <= 0:
        seeds = [random.randrange(1, 2 ** 31 - 1) for _ in range(max(1, n))]
        return seeds[:n], (random.randrange(1, 2 ** 31 - 1) if mode == "randomize" else seeds[0])
    if mode == "increment":
        return [b + i for i in range(n)], b + n
    if mode == "decrement":
        return [max(1, b - i) for i in range(n)], max(1, b - n)
    return [b] * n, b


def _norm_text(s):
    """指纹用的文本归一化：只吃"排版噪音"，不吃内容。

    工作台的「保存」是从 DOM 重新拼回中文的，行尾空格、多余空行、CRLF 都会被重排；
    这种人什么都没改的保存不应该让审核指纹失效（否则"呈现 → 用户看一眼点保存 → 闸门挂"会无限循环）。
    真正的文字改动（哪怕一个词）依然会让指纹变。
    """
    s = (s or "").replace("\r\n", "\n").replace("\r", "\n")
    s = "\n".join(ln.rstrip() for ln in s.split("\n"))
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def state_hash(st, with_images=False):
    """指纹：默认只覆盖"人要看要改的内容"（简介/资产提示词/分段提示词）。

    with_images=True 时把资产图也算进去 —— 出完图必须再呈现一次，人才好拍板，
    这一版指纹一变，`videos` 就会被闸门挡住。
    """
    payload = {
        "meta": {k: _norm_text((st.get("meta") or {}).get(k))
                 for k in ("title", "hook", "synopsis", "styleLock")},
        # 人物视图模板改了也算"内容变了"：换模板等于换定设图，必须先呈现再出图
        "charSheet": _norm_text(char_block(st)),
        "assets": [
            {"id": a.get("id"), "type": a.get("type"), "prompt": _norm_text(a.get("prompt")),
             "ratio": a.get("ratio"), "megapixels": a.get("megapixels"), "voice": a.get("voice"),
             "image": (a.get("image") or "") if with_images else "",
             "imageVer": (a.get("imageVer") or 0) if with_images else 0}
            for a in (st.get("assets") or [])
        ],
        "segments": [
            {"id": sg.get("id"), "sec": sg.get("sec"), "cast": sg.get("cast"),
             "refs": [r.get("asset") if isinstance(r, dict) else r for r in (sg.get("refs") or [])],
             "promptSegs": [[_norm_text(x), _norm_text(y)]
                            for x, y in norm_seg_pairs(sg, (st.get("meta") or {}).get("globalBlock"))]}
            for sg in (st.get("segments") or [])
        ],
    }
    return hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def review_gate(st, skip, what, with_images=False):
    """生成前的闸门：改过但没重新呈现给用户，就不许往下跑。

    第 2 阶段（出图）比的是提示词指纹；
    第 3 阶段（出视频）还要把资产图算进去 —— 图出完必须再呈现一次给人拍板。
    """
    if skip:
        print("[!] --skip-review：跳过\"必须先呈现 HTML\"的闸门", flush=True)
        return
    cur = state_hash(st, with_images=with_images)
    ok_hash = (st.get("meta") or {}).get("reviewedAssetsHash" if with_images else "reviewedHash")
    if ok_hash == cur:
        print("提示词版本已呈现（%s），继续。" % (st["meta"].get("reviewedAt") or "已登记"), flush=True)
        return
    die(
        "当前提示词版本还没呈现给用户，不能直接%s。\n"
        "  正确顺序：build → 把页面真打开给人看 → present 登记 → 再%s。\n"
        "  如果提示词改过、人改过中文还没同步英文、或资产图刚生成/换过，都必须重新 build 并再呈现一次。\n"
        "  确认要跳过：加 --skip-review。" % (what, what),
        code=3,
    )


# ---- 用户参数记忆 ------------------------------------------------------------
# 工作台里「生图参数 / 视频参数」那些项，一保存就写进技能目录的 settings.user.json，
# 下一个项目 init 时直接沿用，不用每次重设。只记参数，剧情 / 资产 / 台词 / 提示词一律不记。
USER_SETTINGS_PATH = os.path.join(SKILL_DIR, "settings.user.json")
REMEMBER_KEYS = (
    "imgUnet", "imgClip", "imgVae", "imgSteps", "ratio", "megapixels",
    "steps", "comfy", "h3Model",
    "h3Lora", "h3LoraStrength", "h3Lora2", "h3Lora2Strength", "h3Lora3", "h3Lora3Strength",
    "h3Clip", "h3VideoVae", "h3AudioVae",
    "h3Sparse", "h3Attn", "h3Chunks", "h3SeqThreshold", "h3HeadChunks",
    "seed", "afterGenerate", "charSheet",
)


def builtin_settings():
    """技能内置默认值：记忆文件不存在或坏掉时用它兜底。"""
    return {
        "imgUnet": DEFAULT_IMG_UNET,
        "imgClip": DEFAULT_IMG_CLIP,
        "imgVae": DEFAULT_IMG_VAE,
        "imgSteps": DEFAULT_IMG_STEPS,
        "ratio": "9:16",
        "megapixels": 0.9,
        "steps": DEFAULT_H3_STEPS,
        "comfy": "http://127.0.0.1:8188",
        "h3Model": DEFAULT_H3_MODEL,
        "h3Lora": DEFAULT_H3_LORA,
        "h3LoraStrength": DEFAULT_H3_LORA_STRENGTH,
        # 2、3 号位默认留空：页面上显示「（不挂 LoRA）」，要用自己选
        "h3Lora2": "",
        "h3Lora2Strength": DEFAULT_H3_LORA_SLOT_STRENGTH,
        "h3Lora3": "",
        "h3Lora3Strength": DEFAULT_H3_LORA_SLOT_STRENGTH,
        "h3Clip": DEFAULT_H3_CLIP,
        "h3VideoVae": DEFAULT_H3_VIDEO_VAE,
        "h3AudioVae": DEFAULT_H3_AUDIO_VAE,
        "h3Sparse": DEFAULT_H3_SPARSE,
        "h3Attn": DEFAULT_H3_ATTN,
        "h3Chunks": DEFAULT_H3_CHUNKS,
        "h3SeqThreshold": DEFAULT_H3_SEQ_THRESHOLD,
        "h3HeadChunks": DEFAULT_H3_HEAD_CHUNKS,
        "seed": 0,
        "afterGenerate": "fixed",
        "charSheet": {"en": CHAR_BLOCK, "zh": CHAR_BLOCK_ZH, "edited": False},
    }


def load_user_settings():
    """读技能里记住的参数。只认 REMEMBER_KEYS，文件里多写的字段直接忽略。"""
    base = builtin_settings()
    try:
        with open(USER_SETTINGS_PATH, "r", encoding="utf-8") as f:
            doc = json.load(f)
    except Exception:
        return base
    src = doc.get("settings") if isinstance(doc, dict) and isinstance(doc.get("settings"), dict) else doc
    if not isinstance(src, dict):
        return base
    for k in REMEMBER_KEYS:
        v = src.get(k)
        if v is None:
            continue
        if k == "charSheet":
            if not isinstance(v, dict):
                continue
            cs = base["charSheet"]
            for kk in ("en", "zh"):
                if isinstance(v.get(kk), str) and v[kk].strip():
                    cs[kk] = v[kk]
            cs["edited"] = bool(v.get("edited"))
            continue
        # 上一代工作流的 turbo LoRA 不再作为默认：记忆里还是它的话，按新工作流的 dmad_v4 走
        if k == "h3Lora" and str(v).strip() in LEGACY_H3_LORAS:
            continue
        # 注意力后端只剩两档：记忆里还是旧版的 comfy_kitchen_int8 / sla_* 就别带进来
        if k == "h3Attn" and str(v).strip() not in H3_ATTN_OPTS:
            continue
        base[k] = copy.deepcopy(v)
    return base


def remember_settings(st, proj=""):
    """把当前项目的参数项写回技能目录（只写 REMEMBER_KEYS，别的一概不碰）。"""
    s = (st or {}).get("settings") or {}
    keep = {}
    for k in REMEMBER_KEYS:
        if k in s and s[k] is not None:
            keep[k] = copy.deepcopy(s[k])
    if not keep:
        return None
    cs = keep.get("charSheet")
    if isinstance(cs, dict) and not (cs.get("zh") or "").strip() and not (cs.get("en") or "").strip():
        keep.pop("charSheet", None)          # 空模板不落记忆，留给内置默认
    doc = {
        "version": 1,
        "updatedAt": now_str(),
        "from": os.path.basename(str(proj).rstrip("/\\")) if proj else "",
        "note": "工作台「生图参数 / 视频参数」保存下来的项，新建的剧自动沿用；只记参数，不记剧情、资产与提示词。删掉本文件即回到内置默认。",
        "settings": keep,
    }
    tmp = USER_SETTINGS_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        os.replace(tmp, USER_SETTINGS_PATH)
    except Exception as e:
        print("[!] 参数记忆写入失败：%s" % e, flush=True)
        return None
    return doc


def new_state(title="未命名短剧", source=""):
    mem = load_user_settings()
    return {
        "meta": {
            "title": title,
            "source": source,
            "hook": "",
            "synopsis": "",
            "styleLock": "",
            "globalBlock": {},
            "stage": 1,
            "reviewedHash": "",
            "reviewedAssetsHash": "",
            "reviewedAt": "",
            "createdAt": now_str(),
            "updatedAt": now_str(),
        },
        "settings": {
            "imgUnet": mem["imgUnet"],
            "imgClip": mem["imgClip"],
            "imgVae": mem["imgVae"],
            "imgSteps": mem["imgSteps"],
            "ratio": mem["ratio"],
            "megapixels": mem["megapixels"],
            "steps": mem["steps"],
            "comfy": mem["comfy"],
            "h3Model": mem["h3Model"],
            "h3Lora": mem["h3Lora"],
            "h3LoraStrength": mem["h3LoraStrength"],
            "h3Lora2": mem.get("h3Lora2") or "",
            "h3Lora2Strength": mem.get("h3Lora2Strength", DEFAULT_H3_LORA_SLOT_STRENGTH),
            "h3Lora3": mem.get("h3Lora3") or "",
            "h3Lora3Strength": mem.get("h3Lora3Strength", DEFAULT_H3_LORA_SLOT_STRENGTH),
            "h3Clip": mem["h3Clip"],
            "h3VideoVae": mem["h3VideoVae"],
            "h3AudioVae": mem["h3AudioVae"],
            "h3Sparse": bool(mem.get("h3Sparse", DEFAULT_H3_SPARSE)),
            "h3Attn": mem.get("h3Attn") or DEFAULT_H3_ATTN,
            "h3Chunks": int(mem.get("h3Chunks") or DEFAULT_H3_CHUNKS),
            "h3SeqThreshold": int(mem.get("h3SeqThreshold") or DEFAULT_H3_SEQ_THRESHOLD),
            "h3HeadChunks": int(mem.get("h3HeadChunks") or DEFAULT_H3_HEAD_CHUNKS),
            "h3Wf": H3_WF_TAG,
            "seed": mem["seed"],
            "afterGenerate": mem["afterGenerate"],
            "charSheet": copy.deepcopy(mem["charSheet"]),
        },
        "voices": [dict(v) for v in DEFAULT_VOICES],
        "assets": [],
        "segments": [],
    }


def _pairs_from_legacy(text):
    """旧版单语提示词 → 一段 promptSegs（en 直接就是可生成内容）。"""
    t = (text or "").strip()
    if not t:
        return []
    return [{"en": t, "zh": "", "edited": False}]


def migrate(st):
    """把 v1（episodes/shots/中文单语）迁到 v2（segments/双语）。就地修改并返回。"""
    st.setdefault("meta", {})
    st.setdefault("settings", {})
    st.setdefault("assets", [])
    st.setdefault("voices", [dict(v) for v in DEFAULT_VOICES])
    st["meta"].setdefault("globalBlock", {})

    s = st["settings"]
    # 缺项用「技能里记住的参数」补，而不是硬编码默认：老项目没写的字段也能吃到用户上次的设置
    mem = load_user_settings()
    for k in ("imgUnet", "imgClip", "imgVae", "imgSteps", "ratio", "megapixels", "steps", "comfy",
              "h3Model", "h3Lora", "h3LoraStrength", "h3Lora2", "h3Lora2Strength",
              "h3Lora3", "h3Lora3Strength", "h3Clip", "h3VideoVae", "h3AudioVae",
              "h3Sparse", "h3Attn", "h3Chunks", "h3SeqThreshold", "h3HeadChunks",
              "seed", "afterGenerate"):
        s.setdefault(k, mem[k])
    # 三个 LoRA 位置：名字必须是字符串（空 = 不挂），强度必须是数字
    for i, sfx in ((1, ""), (2, "2"), (3, "3")):
        nm = s.get("h3Lora" + sfx)
        s["h3Lora" + sfx] = "" if nm in (None, "") else str(nm).strip()
        k = "h3LoraStrength" + sfx
        try:
            sv = float(s.get(k))
        except (TypeError, ValueError):
            sv = DEFAULT_H3_LORA_SLOT_STRENGTH if i > 1 else DEFAULT_H3_LORA_STRENGTH
        s[k] = min(2.0, max(-2.0, sv))
    # 新工作流里没有二采高清 / VEDA：老项目残留的一律清掉，页面也不再显示
    for k in H3_RETIRED_KEYS:
        s.pop(k, None)
    # 注意力后端：旧版存的是 comfy_kitchen_int8 / sla_* 那一套枚举，新节点只认两档——不认识就回默认
    if s.get("h3Attn") not in H3_ATTN_OPTS:
        s["h3Attn"] = DEFAULT_H3_ATTN
    s["h3Sparse"] = bool(s.get("h3Sparse"))
    # 三个分块参数都必须是正整数，越界/乱填回落到默认
    for k, dflt, lo, hi in (("h3Chunks", DEFAULT_H3_CHUNKS, 1, 16),
                            ("h3SeqThreshold", DEFAULT_H3_SEQ_THRESHOLD, 256, 65536),
                            ("h3HeadChunks", DEFAULT_H3_HEAD_CHUNKS, 1, 16)):
        try:
            iv = int(float(s.get(k)))
        except (TypeError, ValueError):
            iv = dflt
        s[k] = min(hi, max(lo, iv))
    # 生图步数必须是可以直接填进 KSampler 的整数：空值 / 乱填一律回落到默认 25
    try:
        iv = int(float(s.get("imgSteps")))
        s["imgSteps"] = iv if 1 <= iv <= 200 else DEFAULT_IMG_STEPS
    except (TypeError, ValueError):
        s["imgSteps"] = DEFAULT_IMG_STEPS
    # 生图模型选择（turbo6 / quality25）已取消：turbo 工作流整个删掉，统一走 25 步 + 三件套模型
    s.pop("imageModel", None)
    # 人物定设图模板：项目里有就用项目的，没有就用记忆里的，再没有才用内置版
    cs = s.get("charSheet")
    if not isinstance(cs, dict):
        cs = {}
    mcs = mem.get("charSheet") or {}
    if not (cs.get("en") or "").strip():
        cs["en"] = (mcs.get("en") or "").strip() or CHAR_BLOCK
    if not (cs.get("zh") or "").strip():
        cs["zh"] = (mcs.get("zh") or "").strip() or CHAR_BLOCK_ZH
    cs.setdefault("edited", bool(mcs.get("edited")))
    s["charSheet"] = cs

    # 工作流换代（分块链 → H3 原生 Ref2VA，主 LoRA 换成 dmad_v4 step600）：
    # 只有项目里还留着"上一代默认值"时才自动对齐一次，用户自己改过的模型/LoRA/步数一律不动。
    if s.get("h3Wf") != H3_WF_TAG:
        print("[i] H3 工作流已换成 %s：老项目按上一代默认值对齐一次（LoRA/步数）" % H3_WF_TAG, flush=True)
        cur_lora = (s.get("h3Lora") or "").strip()
        if not cur_lora or cur_lora in LEGACY_H3_LORAS:
            s["h3Lora"] = DEFAULT_H3_LORA
        if s.get("steps") in (None, "", LEGACY_H3_STEPS):
            s["steps"] = DEFAULT_H3_STEPS
        s["h3Wf"] = H3_WF_TAG

    if "segments" not in st:
        segs = []
        for i, sh in enumerate(st.get("shots") or [], 1):
            refs = sh.get("refs") or []
            cast = []
            for r in refs:
                aid = r.get("asset") if isinstance(r, dict) else r
                if aid and aid not in cast:
                    cast.append(aid)
            segs.append({
                "id": sh.get("id") or ("P%02d" % i),
                "title": (sh.get("visual") or sh.get("id") or "")[:24],
                "chapter": sh.get("ep") or "",
                "sec": float(sh.get("sec") or 8),
                "genSec": gen_sec(sh.get("sec") or 8),
                "logline": sh.get("line") or "",
                "cast": cast,
                "refs": refs,
                "promptSegs": _pairs_from_legacy(sh.get("prompt") or ""),
                "legacy": True,
                "video": sh.get("video") or "",
                "status": sh.get("status") or "pending",
                "error": sh.get("error") or "",
            })
        st["segments"] = segs
    st.pop("episodes", None)
    st.pop("shots", None)

    for seg in st["segments"]:
        seg.setdefault("cast", [])
        seg.setdefault("refs", [])
        seg.setdefault("promptSegs", [])
        seg.setdefault("status", "pending")
        seg.setdefault("video", "")
        seg["sec"] = float(seg.get("sec") or 8)
        seg["genSec"] = gen_sec(seg["sec"])
        for p in seg["promptSegs"]:
            p.setdefault("en", "")
            p.setdefault("zh", "")
            p.setdefault("edited", False)
    for a in st["assets"]:
        a.setdefault("voice", "")
        if a.get("type") == "character":
            a.setdefault("voicePrompt", "")
            a.setdefault("voicePromptZh", "")
    return st


def load_state(proj):
    p = paths(proj)
    if not os.path.isfile(p["json"]):
        die("找不到 %s\n先运行：python drama.py init --project \"%s\" --title \"剧名\"" % (p["json"], p["proj"]))
    with open(p["json"], "r", encoding="utf-8") as f:
        st = json.load(f)
    return decorate_versions(migrate(st), proj)


def decorate_versions(st, proj):
    """把图片/视频的 mtime 写进 state，前端用它做 ?v= 破缓存。"""
    for a in st.get("assets") or []:
        img = a.get("image") or ""
        ver = 0
        if img:
            try:
                ver = int(os.path.getmtime(os.path.join(proj, img)))
            except Exception:
                ver = 0
        a["imageVer"] = ver
    for sg in st.get("segments") or []:
        vid = sg.get("video") or ""
        ver = 0
        if vid:
            try:
                ver = int(os.path.getmtime(os.path.join(proj, vid)))
            except Exception:
                ver = 0
        sg["videoVer"] = ver
    return st


def preserve_server_fields(st, cur):
    """保存时的冲突保护：浏览器里的页面是「某一刻的快照」，它一保存就会把整份 state 写回磁盘。

    旧快照会顺手把审核登记（reviewed*）冲掉，导致 `videos` 闸门突然拦人；
    也会把刚上传的资产图、刚生成的视频整段清空。这里把服务端独占的字段全部从磁盘覆盖回去：

    - meta 的审核登记 / 创建时间 / 阶段
    - 资产的图片路径、版本戳、图片来源（由 /api/upload 与生成器独占）
    - 分镜已产出的视频（页面不提供"删视频"入口，缺了就说明是旧快照）
    """
    cm, sm = cur.get("meta") or {}, st.setdefault("meta", {})
    for k in ("reviewedHash", "reviewedAssetsHash", "reviewedAt", "createdAt"):
        if cm.get(k) not in (None, ""):
            sm[k] = cm[k]
    try:
        sm["stage"] = max(int(cm.get("stage") or 0), int(sm.get("stage") or 0))
    except Exception:
        sm["stage"] = cm.get("stage") or sm.get("stage") or 0

    byid = {a.get("id"): a for a in (cur.get("assets") or []) if a.get("id")}
    for a in st.get("assets") or []:
        old = byid.get(a.get("id"))
        if not old:
            continue
        for k in ("image", "imageVer", "imageSource"):
            if old.get(k):
                a[k] = old[k]
        if old.get("status") == "done" and a.get("status") in (None, "", "pending"):
            a["status"] = "done"

    segbyid = {s.get("id"): s for s in (cur.get("segments") or []) if s.get("id")}
    for s in st.get("segments") or []:
        old = segbyid.get(s.get("id"))
        if not old:
            continue
        if old.get("video") and not s.get("video"):
            s["video"] = old["video"]
            s["videoVer"] = old.get("videoVer") or 0
            s["status"] = old.get("status") or "done"
            if old.get("error") and not s.get("error"):
                s["error"] = old["error"]
    return st


def save_state(proj, st):
    p = paths(proj)
    st.pop("_proj", None)   # 运行时临时字段，不落盘
    st.setdefault("meta", {})["updatedAt"] = now_str()
    tmp = p["json"] + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p["json"])
    # 留一个技能目录指针：把「启动工作台.bat」单独复制进项目文件夹时，启动器靠它找回本技能
    try:
        with open(os.path.join(proj, ".drama-skill"), "w", encoding="utf-8") as f:
            f.write(SKILL_DIR + "\n")
    except Exception:
        pass


def load_wf(name):
    with open(os.path.join(WF_DIR, name), "r", encoding="utf-8") as f:
        return json.load(f)


def build_html(proj, st=None):
    p = paths(proj)
    st = st or load_state(proj)
    with open(TPL_PATH, "r", encoding="utf-8") as f:
        tpl = f.read()
    blob = json.dumps(st, ensure_ascii=False).replace("</", "<\\/")
    title = (st["meta"].get("title") or "短剧工作台").replace("<", "&lt;")
    proj_js = json.dumps(os.path.abspath(proj), ensure_ascii=False).replace("</", "<\\/")
    # 模型默认值随页面下发：前端发现保存的模型不在 ComfyUI 里时，优先切回这些默认名
    model_defaults = json.dumps({
        "imgUnet": DEFAULT_IMG_UNET, "imgClip": DEFAULT_IMG_CLIP, "imgVae": DEFAULT_IMG_VAE,
        "h3Model": DEFAULT_H3_MODEL, "h3Lora": DEFAULT_H3_LORA, "h3Clip": DEFAULT_H3_CLIP,
        "h3Lora2": "", "h3Lora3": "",
        "h3VideoVae": DEFAULT_H3_VIDEO_VAE, "h3AudioVae": DEFAULT_H3_AUDIO_VAE,
    }, ensure_ascii=False).replace("</", "<\\/")
    # 运镜目录随页面下发：下拉选项 + 每条运镜的戏用说明 + 是否要 LoRA（前端算徽标用）
    cam = json.dumps([
        {"id": m.get("id"), "zh": m.get("zh"), "en": m.get("en"), "cat": m.get("cat"),
         "size": m.get("size"), "need": m.get("need"), "when": m.get("when"),
         "lora": [x for c in (m.get("lora") or [])
                  for x in [c.get("name")] + [str(a).split("|")[0] for a in (c.get("aliases") or [])]
                  if x]}
        for m in CAMERA_MOVES.values()], ensure_ascii=False).replace("</", "<\\/")
    html = (tpl.replace("__TITLE__", title)
               .replace("__PROJECT_DIR__", proj_js)
               .replace("__MODEL_DEFAULTS__", model_defaults)
               .replace("__CAMERA_MOVES__", cam)
               .replace("__DRAMA_STATE__", blob))
    tmp = p["html"] + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(html)
    os.replace(tmp, p["html"])
    return p["html"]


# ---------------------------------------------------------------- 提示词
GLOBAL_EN_MARK = "【GLOBAL"
GLOBAL_ZH_MARK = "【全局"


def seg_prompt(seg, gb=None):
    """真正送进 H3 的提示词：本段英文段落按顺序拼接。

    六段式段（以 `subject_definitions:` 开头）自带全局风格句，不再前置旧版全局块；
    旧格式段仍然前置 `meta.globalBlock`，保证老项目能原样重跑。
    """
    pairs = [p for p in (seg.get("promptSegs") or []) if (p.get("en") or "").strip()]
    g = ((gb or {}).get("en") or "").strip() if isinstance(gb, dict) else ""
    if pairs:
        body = "\n\n".join(p["en"].strip() for p in pairs)
        if g and not body.startswith(GLOBAL_EN_MARK) and not body.lstrip().lower().startswith("subject_definitions:"):
            body = g + "\n\n" + body
        return body
    body = (seg.get("prompt") or "").strip()
    if g and body and not body.startswith(GLOBAL_EN_MARK):
        body = g + "\n\n" + body
    return body


def extract_global_block(st):
    """把各段开头重复的「全局画质与摄影前置」抽到 meta.globalBlock，段内不再重复。"""
    meta = st.setdefault("meta", {})
    gb = meta.get("globalBlock")
    gb = dict(gb) if isinstance(gb, dict) else {}
    moved = []
    for seg in st.get("segments") or []:
        ps = seg.get("promptSegs") or []
        if not ps:
            continue
        en0 = (ps[0].get("en") or "").strip()
        zh0 = (ps[0].get("zh") or "").strip()
        if not (en0.startswith(GLOBAL_EN_MARK) or zh0.startswith(GLOBAL_ZH_MARK)):
            continue
        cur = (gb.get("en") or "").strip()
        if not cur and en0:
            gb = {"en": en0, "zh": zh0, "edited": bool(gb.get("edited"))}
        elif cur and en0 and en0 != cur:
            print("[!] %s 的全局段与已抽出的全局块不一致，以全局块为准" % (seg.get("id") or "?"), flush=True)
        seg["promptSegs"] = ps[1:]
        moved.append(seg.get("id") or "?")
    if gb:
        meta["globalBlock"] = gb
    elif "globalBlock" not in meta:
        meta["globalBlock"] = {}
    return moved


def norm_seg_pairs(seg, gb=None):
    """指纹归一化：不论全局块在段内还是已抽到 meta，都拼成同一份文本，保证指纹稳定。"""
    en = [(x.get("en") or "") for x in (seg.get("promptSegs") or [])]
    zh = [(x.get("zh") or "") for x in (seg.get("promptSegs") or [])]
    g = (gb or {}).get("en") if isinstance(gb, dict) else ""
    gz = (gb or {}).get("zh") if isinstance(gb, dict) else ""
    if (g or "").strip():
        if not (en and en[0].lstrip().startswith(GLOBAL_EN_MARK)):
            en = [g.strip()] + en
            zh = [(gz or "").strip()] + zh
    if not en and not zh:
        body = seg_prompt(seg, gb)
        return [[body, seg.get("zh") or ""]] if body else []
    n = max(len(en), len(zh))
    return [[en[i] if i < len(en) else "", zh[i] if i < len(zh) else ""] for i in range(n)]



def seg_edited(seg):
    return [i for i, p in enumerate(seg.get("promptSegs") or []) if p.get("edited")]


def voice_binding(st, seg):
    """本段每个出场人物走哪条音色路线（参考音频 / 固定音色提示词）。

    返回 [{subject, cast_index, kind, audio_no, voice, name, file, asset, voicePrompt, voicePromptZh}]：
      kind = "audio"  → 挂了参考音频，写 <Audio N> 句，N = 第几路（1 起数）
      kind = "prompt" → 没挂参考音频，写"整部剧固定音色"句（来自 assets[].voicePrompt）
      kind = "none"   → 两条都没有，不写句子（check 会报成硬问题）

    Subject 编号 = cast 下标 + 1（人物在前、场景道具在后，和 <Picture N> 同序）。
    每段最多挂 AUDIO_SLOTS 路参考音；超出的人物自动退回"固定音色提示词"，
    这样每个人物都一定有音色依据，不会有人物没声音设定。
    """
    amap = {a.get("id"): a for a in st.get("assets") or []}
    vmap = {v.get("id"): v for v in st.get("voices") or []}
    p = paths(st.get("_proj") or ".")
    out, used_files, audio_no = [], set(), 0
    for idx, aid in enumerate(seg.get("cast") or []):
        a = amap.get(aid)
        if not a or a.get("type") != "character":
            continue
        subject = idx + 1
        vid = a.get("voice") or ""
        v = vmap.get(vid)
        fp = ""
        if v and (v.get("file") or "").strip() and audio_no < AUDIO_SLOTS:
            cand = os.path.join(p["proj"], v["file"])
            if os.path.isfile(cand) and cand not in used_files:
                fp = cand
        if fp:
            audio_no += 1
            used_files.add(fp)
            kind = "audio"
        else:
            has_text = bool((a.get("voicePrompt") or "").strip() or (a.get("voicePromptZh") or "").strip())
            kind = "prompt" if has_text else "none"
        out.append({
            "subject": subject,
            "cast_index": idx,
            "kind": kind,
            "audio_no": audio_no if kind == "audio" else 0,
            "voice": vid,
            "name": (v.get("name") if v else "") or a.get("name") or aid,
            "file": fp,
            "asset": aid,
            "voicePrompt": (a.get("voicePrompt") or "").strip(),
            "voicePromptZh": (a.get("voicePromptZh") or "").strip(),
        })
    return out


def audio_binding(st, seg):
    """本段真正挂进 ref_audio_0/1 的那几路（兼容旧调用）。"""
    return [b for b in voice_binding(st, seg) if b["kind"] == "audio"]


def seg_audio(st, seg):
    """本段要挂的声音参考文件（绝对路径），顺序即 ref_audio_0/1 的顺序。"""
    return [b["file"] for b in audio_binding(st, seg)]


def _subject_blocks(seg, key, subject):
    """找出含 `<Subject K>` 行的段落（K = subject），返回 [(下标, 段落)]。

    六段式里第一个人物/场景那条前面还顶着 `subject_definitions:` 块名，
    所以按「行首」匹配，而不是整段开头匹配。
    """
    pat = re.compile(r"(?m)^[ \t]*<Subject\s*%d>" % subject)
    hits = []
    for i, p in enumerate(seg.get("promptSegs") or []):
        if pat.search(p.get(key) or ""):
            hits.append((i, p))
    return hits


def _drop_orphan_subject(txt):
    """删句后可能留下孤零零的 <Subject1> 一行，整行去掉。"""
    keep = []
    for ln in (txt or "").split("\n"):
        if re.fullmatch(r"<Subject\s*\d+>\s*[，,、]?", ln.strip()):
            continue
        keep.append(ln.rstrip())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(keep)).strip()


def adopt_legacy_voice(st):
    """把旧模板写在 <Subject K> 段里的两句机器句搬出去（幂等）。

    - `<Subject1>, S1 is always the speaker.` / `，S1 永远是说话人。` → 直接删掉（新规范不要这句话）；
    - `S1 always uses one fixed voice: …` / `S1 始终使用一种固定的声音：…` → 抽成 `assets[].voicePrompt`，
      从此由资产统一持有，整部剧同一个人物共用同一条描述。

    返回被抽到音色描述的 ["c1.voicePrompt", ...]。
    """
    taken = []
    amap = {a.get("id"): a for a in st.get("assets") or []}
    for seg in st.get("segments") or []:
        cast = seg.get("cast") or []
        for p in seg.get("promptSegs") or []:
            for key in ("en", "zh"):
                txt = p.get(key) or ""
                if not txt:
                    continue
                txt = RE_SPEAKER_LEGACY.sub("", txt)
                rx = RE_VOICE_LEGACY_EN if key == "en" else RE_VOICE_LEGACY_ZH
                m = rx.search(txt)
                if m:
                    k = int(m.group(1))
                    desc = m.group(2).strip().rstrip("。.").strip()
                    aid = cast[k - 1] if 0 < k <= len(cast) else ""
                    a = amap.get(aid)
                    if a and a.get("type") == "character" and desc:
                        fld = "voicePrompt" if key == "en" else "voicePromptZh"
                        if not (a.get(fld) or "").strip():
                            a[fld] = desc
                            taken.append("%s.%s" % (a.get("id"), fld))
                    txt = txt[:m.start()].rstrip()
                p[key] = _drop_orphan_subject(txt)
    return taken


def _end_punct(v, zh=False):
    """音色描述本身可能没有句末标点，补一个，避免和后面的固定句黏在一起。"""
    s = (v or "").strip()
    if not s:
        return ""
    if s[-1] in "。.！!？?；;":
        return s
    return s + ("。" if zh else ".")


def voice_sentence(b, key):
    """按绑定生成"该人物在当前语言下的音色句"。参考音频优先，其次固定音色提示词。

    sync_voice_tags() 写句、check 校验、网页预览都用这一个函数，保证三处永远一致。
    """
    if b.get("kind") == "audio":
        return (AUDIO_TAG_EN if key == "en" else AUDIO_TAG_ZH).format(
            n=b["audio_no"], s=b["subject"])
    if b.get("kind") == "prompt":
        if key == "en":
            v = _end_punct(b.get("voicePrompt"), zh=False)
            return VOICE_PROMPT_EN.format(s=b["subject"], v=v) if v else ""
        v = _end_punct(b.get("voicePromptZh") or b.get("voicePrompt"), zh=True)
        return VOICE_PROMPT_ZH.format(s=b["subject"], v=v) if v else ""
    return ""


def sync_voice_tags(st):
    """把每个人物的音色句同步进对应 <Subject K> 段（参考音频优先，其次固定音色提示词）。

    音色只有两条互斥的路线：
      ① 资产挂了参考音频（`voice` → 音频文件真实存在，且没超 2 路）→ `<Audio N>` 参考句；
      ② 没挂参考音频 → 用 `assets[].voicePrompt` 拼"整部剧固定音色"句。
    同一个人物在整部剧里永远用同一条描述，所以音色天然一致。

    做法：**先按 seg.voiceTags 里记下的原句精确删除，再按最新绑定插入**，换音色 / 换参考音 /
    撤销都不会叠成一堆重复句，也不会误删人写的其它内容。返回改动清单。
    """
    changed = []
    taken = adopt_legacy_voice(st)
    for seg in st.get("segments") or []:
        sid = seg.get("id") or "?"
        old = seg.get("voiceTags") or seg.get("audioTags") or []
        before = json.dumps([[p.get("en"), p.get("zh")] for p in (seg.get("promptSegs") or [])],
                            ensure_ascii=False)

        # 1) 撤掉上一轮写入的句子
        for t in old:
            for key in ("en", "zh"):
                s = (t.get(key) or "").strip()
                if not s:
                    continue
                for p in seg.get("promptSegs") or []:
                    cur = p.get(key) or ""
                    if s in cur:
                        p[key] = re.sub(r"[ \t]{2,}", " ", cur.replace(s, "")).rstrip()

        # 2) 按最新绑定生成新句子
        want = []
        for b in voice_binding(st, seg):
            rec = {"subject": b["subject"], "kind": b["kind"], "audio_no": b["audio_no"],
                   "voice": b.get("voice") or "",
                   "en": voice_sentence(b, "en"), "zh": voice_sentence(b, "zh")}
            if b["kind"] == "none":
                print("[!] %s 的 %s 既没有参考音频也没有音色提示词，这段没有音色依据" % (
                    sid, b.get("asset")), flush=True)
                continue
            if b["kind"] == "prompt" and not rec["en"]:
                print("[!] %s 的 %s 只有中文音色描述、没有英文，英文块写不进去" % (
                    sid, b.get("asset")), flush=True)
            want.append(rec)

        # 3) 插到 <Subject K> 段的末尾（同段已有同样的句子就跳过）
        for w in want:
            found = False
            for key in ("en", "zh"):
                if not (w.get(key) or "").strip():
                    continue
                for _, p in _subject_blocks(seg, key, w["subject"]):
                    found = True
                    cur = (p.get(key) or "").rstrip()
                    if w[key] in cur:
                        continue
                    # 英文用空格接句，中文直接接（中文句间不加空格）
                    p[key] = (cur + (" " if key == "en" else "") + w[key]).strip()
                    break
            if not found:
                print("[!] %s 找不到 <Subject%d> 段，音色句没写进去（检查 cast 顺序）" % (
                    sid, w["subject"]), flush=True)

        after = json.dumps([[p.get("en"), p.get("zh")] for p in (seg.get("promptSegs") or [])],
                           ensure_ascii=False)
        if after != before:
            for w in want:
                tag = ("Audio%d" % w["audio_no"]) if w["kind"] == "audio" else "固定音色"
                changed.append("%s Subject%d <- %s" % (sid, w["subject"], tag))

        seg.pop("audioTags", None)
        if want:
            seg["voiceTags"] = want
        else:
            seg.pop("voiceTags", None)
    return taken + changed


# 兼容旧名字
def sync_audio_tags(st):
    return sync_voice_tags(st)



# ---------------------------------------------------------------- 参数换算
def dims(ratio, megapixels, multiple=32):
    try:
        rw, rh = [float(x) for x in str(ratio).replace("：", ":").split(":")]
    except Exception:
        rw, rh = 16.0, 9.0
    r = rw / rh
    h = math.sqrt(max(0.05, float(megapixels or 0.9)) * 1_000_000 / r)
    h = max(multiple, int(round(h / multiple)) * multiple)
    w = max(multiple, int(round(h * r / multiple)) * multiple)
    return int(w), int(h)


def char_block(st):
    """人物定设图的拼接构图块：优先用项目 settings.charSheet，空则用内置默认。

    工作台上只给人一个中文框，所以这里的口径是：
    - 人改过中文（`edited=true` 且中文非空）→ **直接把中文送进模型**（Qwen-Image 2.1 认中文，
      改完点保存立刻生效，不需要等谁去翻英文）；
    - 没改过 → 用随模板一起维护的英文版（`en`）；
    - 两个都空 → 回落到本文件的内置默认。
    """
    cs = ((st.get("settings") or {}).get("charSheet") or {}) if isinstance(st, dict) else {}
    if not isinstance(cs, dict):
        return CHAR_BLOCK
    zh = (cs.get("zh") or "").strip()
    en = (cs.get("en") or "").strip()
    if cs.get("edited") and zh:
        return zh
    return en or zh or CHAR_BLOCK


def asset_prompt(st, a):
    body = (a.get("prompt") or "").strip()
    parts = []
    if body:
        parts.append(body)
    elif (a.get("desc") or "").strip():
        parts.append(a["desc"].strip())
    t = a.get("type")
    if t == "character" and "拼接构图" not in body and "three-panel" not in body:
        parts.append(char_block(st))
    elif t == "scene" and "全景场景资产" not in body and "UE5" not in body:
        parts.append(SCENE_BLOCK)
    elif t == "prop" and "纯白" not in body and "白色纯色" not in body:
        parts.append(PROP_BLOCK)
    lock = (st["meta"].get("styleLock") or "").strip()
    if lock:
        parts.append(lock)
    # Qwen-Image-2.1 要一整段连续英文描述，块与块之间只留一个空格
    return " ".join(" ".join(x.split()) for x in parts if x.strip())


# ---------------------------------------------------------------- 工作流填参
def image_graph(tpl, prompt, w, h, seed, prefix, unet="", clip="", vae="", steps=DEFAULT_IMG_STEPS):
    g = copy.deepcopy(tpl)
    g[Q_NODE["prompt"]]["inputs"]["value"] = prompt
    g[Q_NODE["latent"]]["inputs"] = {"width": w, "height": h, "batch_size": 1}
    g[Q_NODE["seed"]]["inputs"]["seed"] = int(seed)
    g[Q_NODE["save"]]["inputs"]["filename_prefix"] = prefix
    # 采样步数：填的是整数，直接覆盖 KSampler 的 steps；不合法就按 25 走
    try:
        n_steps = int(steps)
    except (TypeError, ValueError):
        n_steps = DEFAULT_IMG_STEPS
    if n_steps < 1:
        n_steps = DEFAULT_IMG_STEPS
    if Q_NODE.get("steps") in g:
        g[Q_NODE["steps"]]["inputs"]["steps"] = n_steps
    # 三件套模型：留空则沿用工作流里的默认值
    if unet and Q_NODE.get("unet") in g:
        g[Q_NODE["unet"]]["inputs"]["unet_name"] = unet
    if clip and Q_NODE.get("clip") in g:
        g[Q_NODE["clip"]]["inputs"]["clip_name"] = clip
    if vae and Q_NODE.get("vae") in g:
        g[Q_NODE["vae"]]["inputs"]["vae_name"] = vae
    return g


def loader_outputs(addr):
    """TaiYangMultiImageLoader 有几个输出口（决定能不能一次挂多张参考图）。"""
    try:
        info = comfy_api.object_info(addr, "TaiYangMultiImageLoader") or {}
        node = info.get("TaiYangMultiImageLoader") or {}
        return max(1, len(node.get("output") or []))
    except Exception:
        return 1


def video_graph(tpl, prompt, w, h, sec, steps, seed, prefix, ref_files, outputs_avail=1,
                audio_files=(), unet="", loras=None, motion_lora=None,
                clip="", video_vae="", audio_vae="",
                ratio="9:16", megapixels=0.8,
                sparse=True, attn="", chunks=None, seq_threshold=None, head_chunks=None):
    """按 H3 原生 Ref2VA 填参。sec 这里已经是"实际传给 API"的秒数（gen_sec 算过）。

    loras：三个 LoRA 位置，形如 [("xxx.safetensors", 0.8), ("", None), ("", None)]，最多 3 条、
    顺序即串联顺序；名字为空表示这一格不挂，对应的节点会被整颗摘掉、链条自动接回去。

    motion_lora：本段运镜 LoRA，形如 ("dolly_zoom_minimaxh3_v1.safetensors", 1.0)，最多 1 条，
    串在三个位置之后（节点 491，按 400 复制）。None / 空串 = 本段不挂运镜 LoRA。

    宽高不再写死在条件节点上：新工作流由 ResolutionSelector(252) 按「宽高比 + 像素」算好，
    再连线进 MiniMaxH3ReferenceToVideo(413) 的 width/height。w/h 只用于日志与帧数换算。
    """
    g = copy.deepcopy(tpl)
    core = g[H3_NODE["core"]]["inputs"]
    g[H3_NODE["prompt"]]["inputs"][H3_NODE.get("promptKey") or "value"] = prompt

    # 宽高比 + 分辨率：写到 ResolutionSelector 上（枚举值必须与节点定义逐字一致）
    rn = H3_NODE.get("res")
    if rn and rn in g:
        g[rn]["inputs"]["aspect_ratio"] = H3_RATIO_OPTS.get(str(ratio), H3_RATIO_OPTS["9:16"])
        try:
            g[rn]["inputs"]["megapixels"] = float(megapixels)
        except (TypeError, ValueError):
            g[rn]["inputs"]["megapixels"] = 0.8
    elif isinstance(core.get("width"), int):
        # 兜底：模板里万一是直接写死的整数
        core["width"], core["height"] = int(w), int(h)

    g[H3_NODE["duration"]]["inputs"]["value"] = float(sec)
    g[H3_NODE["steps"]]["inputs"]["steps"] = int(steps)
    g[H3_NODE["seed"]]["inputs"]["noise_seed"] = int(seed)
    g[H3_NODE["save"]]["inputs"]["filename_prefix"] = prefix
    g[H3_NODE["refs"]]["inputs"]["image_files"] = json.dumps(ref_files, ensure_ascii=False)

    # 主模型（H3 unet）
    if unet and H3_NODE["unet"] in g:
        g[H3_NODE["unet"]]["inputs"]["unet_name"] = unet

    # CLIP / 视频 VAE / 音频 VAE：只改加载节点；条件节点(413)与解码节点(253/254)是连线引用，
    # 改一处两处一起生效。
    cn = H3_NODE.get("clip")
    if clip and cn and cn in g:
        g[cn]["inputs"]["clip_name"] = clip
    for key, name in (("videoVae", video_vae), ("audioVae", audio_vae)):
        nid = H3_NODE.get(key)
        if name and nid and nid in g:
            g[nid]["inputs"]["vae_name"] = name

    def _drop_node(nid):
        """把一个节点从 model 链上摘掉，让它的下游直接接回它的上游。"""
        if nid not in g:
            return
        upstream = g[nid]["inputs"].get("model")
        for _nid, node in list(g.items()):
            ins = node.get("inputs") or {}
            if ins.get("model") == [nid, 0]:
                ins["model"] = upstream
        g.pop(nid, None)

    # LoRA 串联：53（1 号位）→ 400（2 号位）→ 490（3 号位）→[491 运镜 LoRA]→ 注意力后端(331)。
    # 空的格子整颗摘掉；摘完重新从 unet 一路接回去，保证下游拿到的永远是链条最后一个。
    def _norm_slot(p, dflt=DEFAULT_H3_LORA_STRENGTH):
        """把 (名字, 强度) 规整成字符串 + 浮点；名字空 = 这一格不挂。"""
        if isinstance(p, (list, tuple)):
            name = (p[0] or "").strip() if len(p) > 0 else ""
            raw = p[1] if len(p) > 1 else None
        else:
            name, raw = (p or "").strip(), None
        try:
            strength = float(raw) if raw not in (None, "") else dflt
        except (TypeError, ValueError):
            strength = dflt
        return name, strength

    slots = [_norm_slot(p) for p in (loras or [])][:H3_LORA_SLOTS]
    while len(slots) < H3_LORA_SLOTS:
        slots.append(("", DEFAULT_H3_LORA_SLOT_STRENGTH))

    # 运镜 LoRA 单独一格（491），每段最多一条：它跟人选的三个位置互不抢占
    chain = list(H3_LORA_NODES)
    motion = _norm_slot(motion_lora) if motion_lora else ("", 0.0)
    mn = H3_NODE.get("motionLora")
    if mn and motion[0]:
        chain.append(mn)

    # 490 / 491 模板里都没有：真要用时，按第 2 格（400）的样子复制一颗，连线下面统一重排
    if slots[2][0] and H3_LORA_NODES[1] in g and H3_LORA_NODES[2] not in g:
        g[H3_LORA_NODES[2]] = copy.deepcopy(g[H3_LORA_NODES[1]])
    if mn and motion[0] and H3_LORA_NODES[1] in g and mn not in g:
        g[mn] = copy.deepcopy(g[H3_LORA_NODES[1]])

    plan = [(nid, slots[i]) for i, nid in enumerate(H3_LORA_NODES)]
    if mn in chain:
        plan.append((mn, motion))

    active = []
    for nid, (name, strength) in plan:
        if nid not in g:
            continue
        if not name:
            g.pop(nid, None)
            continue
        g[nid]["inputs"]["lora_name"] = name
        g[nid]["inputs"]["strength_model"] = strength
        active.append(nid)

    prev = [H3_NODE["unet"], 0]
    for nid in active:
        g[nid]["inputs"]["model"] = prev
        prev = [nid, 0]
    # 原来指向 LoRA 链的节点（331 注意力后端）改指链条末端；一条都没挂就直连 unet
    for _nid, node in g.items():
        if _nid in chain:
            continue
        ins = node.get("inputs") or {}
        m = ins.get("model")
        if isinstance(m, list) and len(m) == 2 and m[0] in chain:
            ins["model"] = prev

    # 块稀疏注意力(332)：页面只有一个开关。关掉就把整颗节点从图上摘掉，333 直接接回 331；
    # 节点内部的 sol-attn / tau / min_tokens 这些参数保持在模板里的原值，不往页面暴露。
    sn = H3_NODE.get("sparse")
    if sn and sn in g and not sparse:
        _drop_node(sn)

    # 注意力后端(331)：枚举两档（comfy kitchen attention / pytorch attention）
    an = H3_NODE.get("attn")
    if attn and an and an in g:
        g[an]["inputs"]["attention"] = str(attn)

    # 分块前馈(401)：前馈层切几份算；序列超过阈值才分块
    fn = H3_NODE.get("chunkff")
    if fn and fn in g:
        if chunks not in (None, ""):
            g[fn]["inputs"]["chunks"] = int(chunks)
        if seq_threshold not in (None, ""):
            g[fn]["inputs"]["seq_threshold"] = int(seq_threshold)

    # 低显存注意力(403)：注意力按头分成几份算，压低显存峰值
    vn4 = H3_NODE.get("lowvram")
    if vn4 and vn4 in g and head_chunks not in (None, ""):
        g[vn4]["inputs"]["head_chunks"] = int(head_chunks)

    # 参考图：清掉模板里残留的槽位，只挂本段实际用到的
    for k in [k for k in list(core.keys()) if k.startswith("ref_images.")]:
        core.pop(k)
    used = 0
    for i in range(len(ref_files)):
        if i >= min(outputs_avail, REF_IMAGE_SLOTS):
            break
        core["ref_images.ref_image_%d" % i] = [H3_NODE["refs"], i]
        used += 1

    # 参考音：有就挂 ref_audio_N；没有就把多音轨加载节点整个摘掉（少加载一个节点）
    for k in [k for k in list(core.keys()) if k.startswith("ref_audio_")]:
        core.pop(k)
    anode = H3_NODE["audios"]
    audios = [x for x in (audio_files or []) if x][:AUDIO_SLOTS]
    if audios and anode in g:
        g[anode]["inputs"]["audio_files"] = json.dumps(audios, ensure_ascii=False)
        for i in range(len(audios)):
            core["ref_audio_%d" % i] = [anode, i]
    else:
        g.pop(anode, None)
    return g, used


def verify_graph(g, ref_files=None, audio_files=None, ratio=None, megapixels=None,
                 sparse=None, attn=None, chunks=None, seq_threshold=None, head_chunks=None,
                 loras=None, motion_lora=None):
    """提交前自检：节点映射对不对、引用的节点还在不在、关键值写没写进去。
    返回问题列表（空 = 可以入队）。模板一换就靠这个第一时间发现对不上。"""
    problems = []
    ids = set(g.keys())
    # 1) 所有 ["节点id", 输出口] 形式的连线，必须指向仍存在的节点
    for nid, node in g.items():
        for k, v in (node.get("inputs") or {}).items():
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str) and v[0] not in ids:
                problems.append("节点 %s 的输入 %s 指向已删除的节点 %s" % (nid, k, v[0]))
    # 2) H3_NODE 里点名的节点都得在模板里
    for key in ("prompt", "core", "res", "duration", "steps", "seed", "save", "refs",
                "unet", "clip", "videoVae", "audioVae"):
        nid = H3_NODE.get(key)
        if not nid or nid not in g:
            problems.append("模板里缺少 %s 节点（H3_NODE[%r] = %r）" % (key, key, nid))
    # 3) 关键值确实写进去了
    try:
        pk = H3_NODE.get("promptKey") or "value"
        if not str(g[H3_NODE["prompt"]]["inputs"].get(pk) or "").strip():
            problems.append("提示词没写进节点 %s.%s" % (H3_NODE["prompt"], pk))
        core = g[H3_NODE["core"]]["inputs"]
        # 新工作流的 width/height 是连线（ResolutionSelector 算出来的），老模板才是整数
        for name in ("width", "height"):
            v = core.get(name)
            if isinstance(v, list):
                if v[0] not in ids:
                    problems.append("条件节点的 %s 指向不存在的节点 %s" % (name, v[0]))
            elif not isinstance(v, int):
                problems.append("条件节点的 %s 既不是整数也不是连线（%r）" % (name, v))
        rn = H3_NODE.get("res")
        if rn and rn in g:
            ri = g[rn]["inputs"]
            if ri.get("aspect_ratio") not in H3_RATIO_OPTS.values():
                problems.append("宽高比 %r 不在 ResolutionSelector 的可选值里（节点 %s）"
                                % (ri.get("aspect_ratio"), rn))
            try:
                if float(ri.get("megapixels")) <= 0:
                    problems.append("分辨率像素必须大于 0（节点 %s，当前 %r）" % (rn, ri.get("megapixels")))
            except (TypeError, ValueError):
                problems.append("分辨率像素不是数字（节点 %s，当前 %r）" % (rn, ri.get("megapixels")))
            if ratio and ri.get("aspect_ratio") != H3_RATIO_OPTS.get(ratio):
                problems.append("宽高比没写进节点 %s（期望 %r，实际 %r）"
                                % (rn, H3_RATIO_OPTS.get(ratio), ri.get("aspect_ratio")))
            if megapixels not in (None, ""):
                try:
                    if abs(float(ri.get("megapixels")) - float(megapixels)) > 1e-6:
                        problems.append("分辨率像素没写进节点 %s（期望 %r，实际 %r）"
                                        % (rn, megapixels, ri.get("megapixels")))
                except (TypeError, ValueError):
                    pass
        if not isinstance(g[H3_NODE["steps"]]["inputs"].get("steps"), int):
            problems.append("步数没写进节点 %s" % H3_NODE["steps"])
        if not isinstance(g[H3_NODE["seed"]]["inputs"].get("noise_seed"), int):
            problems.append("种子没写进节点 %s" % H3_NODE["seed"])
        if not str(g[H3_NODE["save"]]["inputs"].get("filename_prefix") or ""):
            problems.append("保存前缀没写进节点 %s" % H3_NODE["save"])
        for key, ik in (("unet", "unet_name"), ("clip", "clip_name"),
                        ("videoVae", "vae_name"), ("audioVae", "vae_name")):
            nid = H3_NODE.get(key)
            if nid in g and not str(g[nid]["inputs"].get(ik) or "").strip():
                problems.append("%s 节点没填模型名（节点 %s）" % (key, nid))
        # 注意力后端：必须是节点认的两档之一
        an = H3_NODE.get("attn")
        if an and an in g:
            got_attn = g[an]["inputs"].get("attention")
            if got_attn not in H3_ATTN_OPTS:
                problems.append("注意力后端 %r 不在可选值里（节点 %s）" % (got_attn, an))
            if attn and got_attn != attn:
                problems.append("注意力后端没写进节点 %s（期望 %r，实际 %r）" % (an, attn, got_attn))
        # 块稀疏注意力：勾了必须留在图上，没勾必须已经摘干净
        sn = H3_NODE.get("sparse")
        if sn and sparse is not None:
            if sparse and sn not in g:
                problems.append("勾了块稀疏注意力，但节点 %s 不在图上（模板与 H3_NODE 对不上）" % sn)
            if not sparse and sn in g:
                problems.append("没勾块稀疏注意力，节点 %s 却还在图上（摘除逻辑没生效）" % sn)
        # 分块前馈 / 低显存注意力：节点要在，值要对
        fn = H3_NODE.get("chunkff")
        if fn and fn not in g:
            problems.append("模板里缺少分块前馈节点（H3_NODE['chunkff'] = %r）" % fn)
        elif fn:
            for key, want in (("chunks", chunks), ("seq_threshold", seq_threshold)):
                if want in (None, ""):
                    continue
                if g[fn]["inputs"].get(key) != int(want):
                    problems.append("分块前馈的 %s 没写进节点 %s（期望 %r，实际 %r）"
                                    % (key, fn, int(want), g[fn]["inputs"].get(key)))
        vn4 = H3_NODE.get("lowvram")
        if vn4 and vn4 not in g:
            problems.append("模板里缺少低显存注意力节点（H3_NODE['lowvram'] = %r）" % vn4)
        elif vn4 and head_chunks not in (None, ""):
            if g[vn4]["inputs"].get("head_chunks") != int(head_chunks):
                problems.append("低显存注意力的 head_chunks 没写进节点 %s（期望 %r，实际 %r）"
                                % (vn4, int(head_chunks), g[vn4]["inputs"].get("head_chunks")))
        # 运镜 LoRA：本段该挂就必须挂在 491 上，不该挂就不能留在图上（一段最多一条）
        mn = H3_NODE.get("motionLora")
        want_m = ""
        if isinstance(motion_lora, (list, tuple)) and motion_lora:
            want_m = (motion_lora[0] or "").strip()
        elif isinstance(motion_lora, str):
            want_m = motion_lora.strip()
        if mn:
            if want_m:
                if mn not in g:
                    problems.append("本段该挂运镜 LoRA（%s），但节点 %s 不在图上" % (want_m, mn))
                elif str(g[mn]["inputs"].get("lora_name") or "") != want_m:
                    problems.append("运镜 LoRA 没写进节点 %s（期望 %r，实际 %r）"
                                    % (mn, want_m, g[mn]["inputs"].get("lora_name")))
            elif mn in g:
                problems.append("本段没设计需要 LoRA 的运镜，节点 %s 却还在图上" % mn)
        # 三个 LoRA 位置：图上挂了几条、顺序对不对、名字是不是页面上选的那几个
        if loras is not None:
            want = []
            for p in list(loras)[:H3_LORA_SLOTS]:
                nm = ((p[0] if isinstance(p, (list, tuple)) else p) or "")
                nm = str(nm).strip()
                if nm:
                    want.append(nm)
            got = [g[nid]["inputs"]["lora_name"] for nid in H3_LORA_NODES
                   if nid in g and "lora_name" in (g[nid].get("inputs") or {})]
            if len(got) != len(want):
                problems.append("LoRA 节点挂了 %d 条（%s），页面设了 %d 条"
                                % (len(got), " → ".join(got) or "无", len(want)))
            elif got != want:
                problems.append("LoRA 链顺序对不上：图上 %s，页面 %s" % (got, want))
        files = json.loads(g[H3_NODE["refs"]]["inputs"].get("image_files") or "[]")
        if ref_files and files != list(ref_files):
            problems.append("参考图列表与预期不一致（节点 %s）" % H3_NODE["refs"])
        have = [k for k in core if k.startswith("ref_images.")]
        if len(have) != len(files):
            problems.append("参考图槽位 %d 个，参考图 %d 张，对不上" % (len(have), len(files)))
        want_audio = [x for x in (audio_files or []) if x][:AUDIO_SLOTS]
        got_audio = [k for k in core if k.startswith("ref_audio_")]
        if len(got_audio) != len(want_audio):
            problems.append("参考音槽位 %d 个，参考音 %d 条，对不上" % (len(got_audio), len(want_audio)))
        # 挂了参考音就必须有加载节点，且节点里真的是这些文件
        if want_audio:
            anode = H3_NODE.get("audios")
            if not anode or anode not in g:
                problems.append("挂了 %d 条参考音，但多音轨加载节点不在图上" % len(want_audio))
            else:
                saved = json.loads(g[anode]["inputs"].get("audio_files") or "[]")
                if saved != list(want_audio):
                    problems.append("参考音列表与预期不一致（节点 %s）" % anode)
    except (KeyError, TypeError, ValueError) as e:
        problems.append("关键值校验时出错：%s" % e)
    return problems


class Reporter:
    def __init__(self):
        self.ok = 0
        self.fail = 0
        self.failed = []

    def good(self, msg):
        self.ok += 1
        print("  [✓] " + msg, flush=True)

    def bad(self, msg):
        self.fail += 1
        self.failed.append(msg)
        print("  [×] " + msg, flush=True)

    def summary(self):
        print("\n—— 完成：成功 %d，失败 %d ——" % (self.ok, self.fail), flush=True)
        for f in self.failed:
            print("   失败：" + f, flush=True)
        return 0 if self.fail == 0 else 1


def need_comfy(addr, dry, hint="已完成的资产/视频不会重复生成。"):
    """生成前的门禁：ComfyUI 没起来就明确提示用户启动，而不是抛一堆栈。"""
    ok, detail = comfy_api.ping(addr)
    if ok:
        print("ComfyUI 在线：%s" % comfy_api.normalize(addr), flush=True)
        return True
    if dry:
        print("[!] ComfyUI 未连接（dry-run 跳过）：%s" % detail, flush=True)
        return False
    die(
        "本地 ComfyUI 没连上：%s\n"
        "请先启动 ComfyUI（桌面版或 run_nvidia_gpu.bat），确认端口默认 8188；"
        "地址不同就加 --addr http://127.0.0.1:端口。\n%s" % (detail, hint),
        code=2,
    )


# ---------------------------------------------------------------- 生图
def cmd_images(args):
    proj = os.path.abspath(args.project)
    st = load_state(proj)
    s = st["settings"]
    addr = args.addr or s["comfy"]
    # 生图只有一条工作流：Qwen-Image 2.1；模型三件套与采样步数跟随「生图参数」里的选择
    wf_name = Q_WF["quality25"]
    tpl = load_wf(wf_name)
    img_unet = (getattr(args, "unet", "") or s.get("imgUnet") or "").strip()
    img_clip = (getattr(args, "clip", "") or s.get("imgClip") or "").strip()
    img_vae = (getattr(args, "vae", "") or s.get("imgVae") or "").strip()
    img_steps = getattr(args, "img_steps", None)
    if img_steps in (None, ""):
        img_steps = s.get("imgSteps") or DEFAULT_IMG_STEPS
    try:
        img_steps = int(img_steps)
    except (TypeError, ValueError):
        img_steps = DEFAULT_IMG_STEPS
    p = paths(proj)
    os.makedirs(p["assets"], exist_ok=True)

    need_comfy(addr, args.dry, hint="启动好再重跑同一条命令，已生成的资产不会重复跑。")
    review_gate(st, getattr(args, "skip_review", False), "生成资产图（第 2 阶段）")

    only = [x.strip() for x in (args.only or "").split(",") if x.strip()]
    targets = []
    for a in st["assets"]:
        if only and a.get("id") not in only:
            continue
        if not args.force and a.get("status") == "done" and a.get("image"):
            continue
        targets.append(a)

    print("生图工作流：Qwen-Image 2.1（%s）｜%d 步｜待生成 %d 项" % (wf_name, img_steps, len(targets)), flush=True)
    print("UNet：%s" % (img_unet or "（按工作流默认）"), flush=True)
    print("CLIP：%s" % (img_clip or "（按工作流默认）"), flush=True)
    print("VAE：%s" % (img_vae or "（按工作流默认）"), flush=True)
    if not targets:
        print("没有需要生成的资产（加 --force 可全部重跑）。", flush=True)
        return 0

    rep = Reporter()
    jobs = []
    seeds, next_seed = pick_seeds(s.get("seed"), len(targets), s.get("afterGenerate"))
    print("随机种：基础 %s｜生成后控制 %s｜本次 %s" % (
        s.get("seed") or "随机", s.get("afterGenerate") or "fixed",
        ",".join(str(x) for x in seeds[:6]) + ("…" if len(seeds) > 6 else "")), flush=True)
    for i, a in enumerate(targets, 1):
        aid = a.get("id") or ("asset%d" % i)
        ratio = a.get("ratio") or TYPE_RATIO.get(a.get("type"), "16:9")
        mp = a.get("megapixels") or TYPE_MP.get(a.get("type"), 1.5)
        w, h = dims(ratio, mp)
        prompt = asset_prompt(st, a)
        if not prompt.strip():
            rep.bad("%s 没有提示词，跳过" % aid)
            continue
        print("\n[%d/%d] %s｜%s｜%s｜%dx%d" % (i, len(targets), aid, a.get("type"), ratio, w, h), flush=True)
        if args.dry:
            print("      提示词：" + prompt[:180].replace("\n", " ") + "…", flush=True)
            rep.good("%s dry-run" % aid)
            continue
        try:
            graph = image_graph(tpl, prompt, w, h, seeds[i - 1], "drama/" + safe_id(aid),
                                unet=img_unet, clip=img_clip, vae=img_vae, steps=img_steps)
            jobs.append({"a": a, "aid": aid, "graph": graph, "prompt": prompt, "pid": None, "t0": 0.0})
        except Exception as e:
            a["error"] = str(e)[:800]
            save_state(proj, st)
            rep.bad("%s：%s" % (aid, str(e)[:300]))
            if args.stop_on_error:
                break

    if args.dry or not jobs:
        return rep.summary()

    def _submit(j):
        try:
            j["pid"] = comfy_api.queue(addr, j["graph"])
            j["t0"] = time.time()
            print("      已入队 %s（prompt_id %s）" % (j["aid"], j["pid"][:8]), flush=True)
            return True
        except Exception as e:
            j["a"]["error"] = str(e)[:800]
            j["a"]["status"] = "error"
            save_state(proj, st)
            rep.bad("%s 入队失败：%s" % (j["aid"], str(e)[:300]))
            return False

    def _collect(j, pid):
        aid = j["aid"]
        try:
            outs = comfy_api.history(addr, pid)
            if not outs:
                return False
            status = outs.get("status") or {}
            if status.get("status_str") == "error":
                raise comfy_api.ApiError(json.dumps(status.get("messages") or [], ensure_ascii=False)[:1500])
            item = comfy_api.pick_image(outs.get("outputs") or {})
            if not item:
                return False
            ext = os.path.splitext(item["filename"])[1] or ".png"
            dest = os.path.join(p["assets"], safe_id(aid) + ext)
            comfy_api.download(addr, item, dest)
            a = j["a"]
            a["image"] = "assets/" + os.path.basename(dest)
            a["status"] = "done"
            a["promptUsed"] = j["prompt"]
            a.pop("error", None)
            save_state(proj, st)
            build_html(proj, st)
            rep.good("%s -> %s（%.1f 分钟）" % (aid, a["image"], (time.time() - j["t0"]) / 60.0))
            return True
        except Exception as e:
            j["a"]["error"] = str(e)[:800]
            j["a"]["status"] = "error"
            save_state(proj, st)
            rep.bad("%s：%s" % (aid, str(e)[:300]))
            return True

    waiting = list(jobs)
    running = {}
    total = len(jobs)
    if args.serial:
        print("\n[串行模式] 提交一张等一张（仅排查问题时用，每张都会重新加载模型）。", flush=True)
    else:
        print("\n[整批入队] 一次性把 %d 张图 POST 进队列，ComfyUI 连续执行，"
              "生图模型只加载一次。" % total, flush=True)
        while waiting:
            j = waiting.pop(0)
            if _submit(j):
                running[j["pid"]] = j
            elif args.stop_on_error:
                break
        if not running:
            return rep.summary()

    tick = 0
    started = time.time()
    while running or (args.serial and waiting):
        if args.serial and not running and waiting:
            j = waiting.pop(0)
            if _submit(j):
                running[j["pid"]] = j
                started = time.time()
                tick = 0
            else:
                continue
        for pid in list(running.keys()):
            if _collect(running[pid], pid):
                running.pop(pid)
        if not running and not (args.serial and waiting):
            break
        waited = time.time() - started
        if waited > args.timeout:
            for pid, j in list(running.items()):
                j["a"]["error"] = "等待超时"
                rep.bad("%s 等待超时" % j["aid"])
            running.clear()
            save_state(proj, st)
            break
        if waited - tick >= 60:
            tick = waited
            print("      队列剩余 %d 张｜已完成 %d/%d｜已用 %.0f 分钟" % (
                len(running), total - len(running) - len(waiting), total, waited / 60.0), flush=True)
        time.sleep(3)

    s["seed"] = next_seed
    save_state(proj, st)
    build_html(proj, st)
    return rep.summary()


# ---------------------------------------------------------------- 合并成片
FINAL_NAME = "成片.mp4"
_FFMPEG_CACHE = []
_FINAL_ARG = None          # 供 _win_argv 用：ffmpeg 在 Windows 下要加 -hide_banner


def find_ffmpeg(st=None):
    """找一个可用的 ffmpeg。优先环境变量 / 项目设置，其次 PATH、剪映自带、常见安装路径。"""
    if _FFMPEG_CACHE:
        return _FFMPEG_CACHE[0]
    cands = []
    env = (os.environ.get("DRAMA_FFMPEG") or "").strip()
    if env:
        cands.append(env)
    if isinstance(st, dict):
        c = str((st.get("settings") or {}).get("ffmpeg") or "").strip()
        if c:
            cands.append(c)
    w = shutil.which("ffmpeg")
    if w:
        cands.append(w)
    if os.name == "nt":
        for base in (os.environ.get("LOCALAPPDATA") or "",
                     os.environ.get("PROGRAMFILES") or "",
                     os.environ.get("PROGRAMFILES(X86)") or ""):
            if not base or not os.path.isdir(base):
                continue
            for pat in ("JianyingPro\\Apps\\*\\ffmpeg.exe", "JianyingPro\\*\\ffmpeg.exe",
                        "ffmpeg\\bin\\ffmpeg.exe", "ffmpeg\\ffmpeg.exe"):
                cands += sorted(glob.glob(os.path.join(base, pat)), reverse=True)
    cands += ["/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/opt/homebrew/bin/ffmpeg", r"C:\ffmpeg\bin\ffmpeg.exe"]
    for c in cands:
        if c and os.path.isfile(c):
            _FFMPEG_CACHE.append(c)
            return c
    return ""


def _run_ff(cmd, timeout=1800):
    """跑 ffmpeg，返回 (returncode, stderr 尾部)。统一吞掉编码问题。"""
    try:
        pr = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        out = (pr.stdout or b"").decode("utf-8", "replace")
        if "Duration:" not in out and "video:" not in out:
            out = (pr.stdout or b"").decode("mbcs", "replace") if os.name == "nt" else out
        return pr.returncode, out
    except Exception as e:
        return -1, str(e)


_ENC_CACHE = {}


def h264_encoders(ff):
    """本机 ffmpeg 能用的 H.264 编码器（剪映自带的精简版没有 libx264，只有硬件编码）。"""
    if ff in _ENC_CACHE:
        return _ENC_CACHE[ff]
    rc, out = _run_ff([ff, "-hide_banner", "-encoders"], timeout=60)
    have = set(re.findall(r"^\s*V[\.\w]*\s+(\S+)", out, re.M))
    order = [e for e in ("libx264", "h264_nvenc", "h264_qsv", "h264_amf", "h264_mf") if e in have]
    if not order:
        order = ["mpeg4"]
    _ENC_CACHE[ff] = order
    return order


def _enc_args(enc):
    """各编码器的等价质量参数（约等于 crf 18–20）。"""
    if enc == "libx264":
        return ["-c:v", "libx264", "-crf", "18", "-preset", "veryfast"]
    if enc == "h264_nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "20", "-b:v", "0"]
    if enc == "h264_qsv":
        return ["-c:v", "h264_qsv", "-global_quality", "20"]
    if enc == "h264_amf":
        return ["-c:v", "h264_amf", "-quality", "balanced", "-rc", "cqp", "-qp_i", "20", "-qp_p", "20"]
    if enc == "h264_mf":
        return ["-c:v", "h264_mf", "-rate_control", "quality"]
    return ["-c:v", "mpeg4", "-q:v", "3"]


def probe_media(ff, path):
    """用 ffmpeg -i 探时长与分辨率（不依赖 ffprobe）。"""
    rc, out = _run_ff([ff, "-hide_banner", "-i", path], timeout=120)
    info = {"sec": 0.0, "w": 0, "h": 0, "audio": False}
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", out)
    if m:
        info["sec"] = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    m = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", out)
    if m:
        info["w"], info["h"] = int(m.group(1)), int(m.group(2))
    info["audio"] = "Audio:" in out
    return info


def merge_videos(proj, st=None, out_name=None, only=None, partial=False, quiet=False):
    """把各段成片按段落顺序拼成一个文件。先尝试无损 `-c copy`，失败再重编码。

    返回 dict：ok / rel / abs / sec / method / reason
    """
    st = st or load_state(proj)
    p = paths(proj)
    ff = find_ffmpeg(st)
    if not ff:
        return {"ok": False, "reason": "没有找到 ffmpeg（装一个，或把路径写进 settings.ffmpeg / 环境变量 DRAMA_FFMPEG）"}
    segs = [s for s in st["segments"] if s.get("video")]
    if only:
        segs = [s for s in segs if s.get("id") in only]
    parts = []
    for s in segs:
        f = os.path.join(proj, s["video"])
        if os.path.isfile(f):
            parts.append((s.get("id") or "", f))
    if not parts:
        return {"ok": False, "reason": "还没有可合并的成片"}
    if not partial and not only and len(parts) != len(st["segments"]):
        return {"ok": False, "reason": "还有 %d 段没生成，等全部完成再合并（或用 --partial）" % (
            len(st["segments"]) - len(parts))}

    out_name = out_name or FINAL_NAME
    if not out_name.lower().endswith(".mp4"):
        out_name += ".mp4"
    out = os.path.join(proj, out_name)
    tmp = os.path.join(p["videos"], "_merge_tmp.mp4")
    infos = [probe_media(ff, path) for _, path in parts]
    info0 = infos[0]
    need = sum(i["sec"] for i in infos)
    # 分段之间分辨率/有无音轨必须一致，否则 concat -c copy 会静默拼出错帧
    uniform = len({(i["w"], i["h"]) for i in infos}) == 1 and len({i["audio"] for i in infos}) == 1

    # 1) 无损拼接：同一套 H3 参数出来的片子编码一致，copy 最快且不掉画质
    lst = os.path.join(p["videos"], "_concat.txt")
    ok = False
    log = ""
    method = "copy"
    if uniform:
        with open(lst, "w", encoding="utf-8", newline="\n") as f:
            for _, path in parts:
                f.write("file '%s'\n" % path.replace("\\", "/").replace("'", "'\\''"))
        rc, log = _run_ff([ff, "-hide_banner", "-y", "-f", "concat", "-safe", "0",
                           "-i", lst, "-c", "copy", "-movflags", "+faststart", tmp])
        ok = rc == 0 and os.path.isfile(tmp) and os.path.getsize(tmp) > 1024
        out_info = probe_media(ff, tmp) if ok else {"sec": 0, "w": 0, "h": 0}
        # copy 成功但时长明显对不上（容器/参数不完全一致），也要重编码
        if ok and need and abs(out_info["sec"] - need) > max(1.5, need * 0.03):
            ok = False
    else:
        print("      分段参数不一致（分辨率或音轨不同），跳过无损拼接，直接重编码", flush=True)

    # 2) 回退：重编码，顺带统一分辨率与帧率
    if not ok:
        method = "reencode"
        w, h = (info0["w"] or 0), (info0["h"] or 0)
        base = [ff, "-hide_banner", "-y"]
        for _, path in parts:
            base += ["-i", path]
        chains = []
        for i, ((_, path), mi) in enumerate(zip(parts, infos)):
            if w and h:
                chains.append("[%d:v]scale=%d:%d:force_original_aspect_ratio=decrease,"
                              "pad=%d:%d:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=25[v%d]" % (i, w, h, w, h, i))
            else:
                chains.append("[%d:v]setsar=1,fps=25[v%d]" % (i, i))
            if mi["audio"]:
                chains.append("[%d:a]aformat=sample_rates=44100:channel_layouts=stereo[a%d]" % (i, i))
            else:
                base += ["-f", "lavfi", "-t", "%.3f" % max(mi["sec"], 0.5),
                         "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
                chains.append("[%d:a]aformat=sample_rates=44100:channel_layouts=stereo[a%d]"
                              % (len(parts) + i, i))
        joined = "".join("[v%d][a%d]" % (i, i) for i in range(len(parts)))
        fc = ";".join(chains) + ";%sconcat=n=%d:v=1:a=1[v][a]" % (joined, len(parts))
        # 剪映自带的 ffmpeg 没有 libx264，只有硬件编码 → 按可用项逐个试
        for enc in h264_encoders(ff):
            cmd = base + ["-filter_complex", fc, "-map", "[v]", "-map", "[a]"] + _enc_args(enc) + [
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart", tmp]
            print("      重编码尝试编码器 %s …" % enc, flush=True)
            rc, log = _run_ff(cmd, timeout=3600)
            ok = rc == 0 and os.path.isfile(tmp) and os.path.getsize(tmp) > 1024
            if ok:
                method = "reencode:" + enc
                break
            print("      该编码器不可用，换下一个", flush=True)

    if not ok:
        tail = "\n".join([x for x in log.strip().splitlines() if x.strip()][-6:])
        return {"ok": False, "reason": "ffmpeg 合并失败（末行：%s）" % tail[-400:]}

    os.replace(tmp, out)
    try:
        os.remove(lst)
    except OSError:
        pass
    fin = probe_media(ff, out)
    rel = os.path.relpath(out, proj).replace("\\", "/")
    # 只有「全段齐、整片」才登记成正式成片；--only / --partial 只是预览，不改 meta
    full = (not only) and (not partial) and len(parts) == len(st["segments"])
    if full:
        st["meta"]["finalVideo"] = rel
        st["meta"]["finalVideoAt"] = now_str()
        st["meta"]["finalVideoSec"] = round(fin["sec"] or need or 0, 2)
        st["meta"]["finalVideoParts"] = [sid for sid, _ in parts]
        save_state(proj, st)
    if not quiet:
        print("  [✓] %s：%s（%d 段｜%.1f 秒｜%s）" % (
            "成片已合并" if full else "预览片段已合并（未登记为成片）",
            rel, len(parts), fin["sec"], method), flush=True)
    return {"ok": True, "rel": rel, "abs": out, "sec": round(fin["sec"], 2),
            "method": method, "parts": len(parts), "full": full}


def cmd_merge(args):
    proj = os.path.abspath(args.project)
    st = load_state(proj)
    only = [x.strip() for x in (args.only or "").split(",") if x.strip()] or None
    r = merge_videos(proj, st, out_name=args.out, only=only, partial=args.partial)
    if not r.get("ok"):
        print("[×] " + r.get("reason", "合并失败"), flush=True)
        return 1
    build_html(proj, st)
    return 0


def _maybe_merge(args, proj, st, rep):
    """全部段都有成片时自动合并；已经是最新的成片就跳过，不重复劳动。"""
    if getattr(args, "no_merge", False) or not st.get("segments"):
        return None
    if not all(x.get("video") and x.get("status") == "done" for x in st["segments"]):
        return None
    fin = st["meta"].get("finalVideo")
    if fin:
        fp = os.path.join(proj, fin)
        try:
            if os.path.isfile(fp):
                newest = max(os.path.getmtime(os.path.join(proj, x["video"])) for x in st["segments"])
                if os.path.getmtime(fp) >= newest:
                    print("成片已是最新：%s（%.1f 秒，%d 段）" % (
                        fin, float(st["meta"].get("finalVideoSec") or 0), len(st["segments"])), flush=True)
                    return {"ok": True, "rel": fin, "sec": st["meta"].get("finalVideoSec") or 0,
                            "parts": len(st["segments"]), "skipped": True}
        except OSError:
            pass
    r = merge_videos(proj, st, quiet=True)
    if r.get("ok"):
        rep.good("成片已合并：%s（%d 段｜%.1f 秒）" % (r["rel"], r["parts"], r["sec"]))
    else:
        rep.bad("合并成片失败：%s" % r.get("reason", ""))
    return r


# ---------------------------------------------------------------- 生视频
def cmd_videos(args):
    proj = os.path.abspath(args.project)
    st = load_state(proj)
    st["_proj"] = proj
    moved = extract_global_block(st)
    tags = sync_audio_tags(st)
    if tags or moved:
        save_state(proj, st)
        if moved:
            print("全局画质与摄影前置已从各段抽到参数区：%s" % "、".join(moved), flush=True)
        if tags:
            print("音色已同步进提示词：%s" % "、".join(tags), flush=True)
    gb = st["meta"].get("globalBlock") or {}
    addr = args.addr or st["settings"]["comfy"]
    s = st["settings"]
    tpl = load_wf(H3_WF)
    p = paths(proj)
    os.makedirs(p["videos"], exist_ok=True)

    need_comfy(addr, args.dry, hint="启动好再重跑同一条命令，已生成的视频不会重复跑。")
    review_gate(st, getattr(args, "skip_review", False), "生成视频（第 3 阶段）", with_images=True)

    outputs_avail = 1 if args.dry else loader_outputs(addr)
    if outputs_avail <= 1:
        print("[!] 参考图加载器只有 1 个输出口：多张参考图将按批处理送入，若串脸请检查 ComfyUI 里的 TaiYangMultiImageLoader。", flush=True)

    assets = {a.get("id"): a for a in st["assets"]}
    only = [x.strip() for x in (args.only or "").split(",") if x.strip()]
    targets = []
    for seg in st["segments"]:
        if only and seg.get("id") not in only:
            continue
        if not args.force and seg.get("status") == "done" and seg.get("video"):
            continue
        targets.append(seg)

    ratio = args.ratio or s["ratio"]
    mp = args.megapixels if args.megapixels is not None else s["megapixels"]
    steps = args.steps if args.steps is not None else s["steps"]
    # 三个 LoRA 位置（页面上三行下拉 + 三行强度）：1 号位默认挂主 LoRA，2、3 号位默认不挂
    lora_slots = []
    for i, sfx in ((1, ""), (2, "2"), (3, "3")):
        nm = (s.get("h3Lora" + sfx) or "").strip()
        sv = s.get("h3LoraStrength" + sfx)
        sv = (DEFAULT_H3_LORA_SLOT_STRENGTH if i > 1 else DEFAULT_H3_LORA_STRENGTH) \
            if sv in (None, "") else float(sv)
        lora_slots.append((nm, sv))
    # 加速 / 显存相关的四个节点参数（页面上是中文四项 + 一个勾选）
    sparse = bool(s.get("h3Sparse", DEFAULT_H3_SPARSE))
    attn = (s.get("h3Attn") or DEFAULT_H3_ATTN).strip()
    if attn not in H3_ATTN_OPTS:
        attn = DEFAULT_H3_ATTN
    chunks = int(s.get("h3Chunks") or DEFAULT_H3_CHUNKS)
    seq_thr = int(s.get("h3SeqThreshold") or DEFAULT_H3_SEQ_THRESHOLD)
    head_chunks = int(s.get("h3HeadChunks") or DEFAULT_H3_HEAD_CHUNKS)
    unet = (s.get("h3Model") or "").strip()
    clip_m = (s.get("h3Clip") or "").strip()
    vvae = (s.get("h3VideoVae") or "").strip()
    avae = (s.get("h3AudioVae") or "").strip()
    w, h = dims(ratio, mp)
    print("H3 参数：%s｜%s MP｜%d 步｜%dx%d｜待生成 %d 段" % (ratio, mp, steps, w, h, len(targets)), flush=True)
    print("注意力后端：%s｜块稀疏注意力：%s" % (attn, "开" if sparse else "关"), flush=True)
    print("分块前馈：%d 块（序列阈值 %d）｜低显存注意力：%d 头/块" % (chunks, seq_thr, head_chunks), flush=True)
    print("主模型：%s" % (unet or "（按工作流默认）"), flush=True)
    print("LoRA：%s" % "｜".join(
        "%d号位 %s" % (i, ("%s（强度 %s）" % (nm, sv)) if nm else "不挂")
        for i, (nm, sv) in enumerate(lora_slots, 1)), flush=True)
    print("CLIP：%s" % (clip_m or "（按工作流默认）"), flush=True)
    # 维度不匹配是这个工作流最容易踩的坑：H3 的 20G 主模型要 32B（5120 维），8B（4096 维）只适合生图。
    if clip_m and re.search(r"(?i)qwen3vl?[_\-]?8b", clip_m) and "h3" in (unet or "").lower():
        print("[!] 这个 CLIP 是 8B（4096 维），H3 主模型要 32B（5120 维）；接上去会在采样器报 "
              "mat1 and mat2 shapes cannot be multiplied。视频请选 MinimaxH3\\qwen3vl_32b_minimax_h3_int8_convrot 或 32B heretic。",
              flush=True)
    print("视频 VAE：%s｜音频 VAE：%s" % (vvae or "（默认）", avae or "（默认）"), flush=True)
    # 运镜 LoRA 只在「本机真有这个文件」时才挂：干跑不查，真跑现读 ComfyUI 的 loras 目录
    avail_lora = None
    if not args.dry:
        try:
            md = comfy_models(addr, force=True)
            avail_lora = md["lora"] if (md.get("lora") and not md.get("error")) else []
            if not avail_lora:
                print("[!] 读不到本机 LoRA 列表（%s）：运镜 LoRA 一律不挂，按原提示词生成"
                      % (md.get("error") or "空列表"), flush=True)
        except Exception as e:
            print("[!] 读不到本机 LoRA 列表（%s）：运镜 LoRA 一律不挂，按原提示词生成"
                  % str(e)[:120], flush=True)
            avail_lora = []
    if not targets:
        print("没有需要生成的视频段（加 --force 可全部重跑）。", flush=True)
        rep0 = Reporter()
        _maybe_merge(args, proj, st, rep0)
        build_html(proj, st)
        return rep0.summary()

    # ---- 1) 先把所有段的参考图 / 参考音上传，工作流全部建好 ----
    rep = Reporter()
    jobs = []
    seeds, next_seed = pick_seeds(s.get("seed"), len(targets), s.get("afterGenerate"))
    print("随机种：基础 %s｜生成后控制 %s" % (s.get("seed") or "随机", s.get("afterGenerate") or "fixed"), flush=True)
    for i, seg in enumerate(targets, 1):
        sid = seg.get("id") or ("seg%d" % i)
        prompt = seg_prompt(seg, gb)
        if not prompt:
            rep.bad("%s 没有 H3 提示词，跳过" % sid)
            continue
        # ---- 运镜：本段声明的运镜 → 决定挂不挂 LoRA、要不要在提示词最前面加触发词 ----
        cmv = camera_of(seg)
        cmid = str(cmv.get("move") or "").strip()
        cmeta = CAMERA_MOVES.get(cmid) or {}
        clead = camera_lead(seg)
        cpick = camera_lora_for(cmid, avail_lora) if cmid else None
        ctier = camera_tier(cmid, avail_lora, lead=clead) if cmid else ""
        motion = (cpick[0], cpick[1]) if cpick else None
        mtrig = motion_trigger_text(cmid, cpick[0]) if cpick else ""
        if mtrig:
            prompt = mtrig + "\n\n" + prompt
        if cmid and not cmeta:
            rep.bad("%s 的运镜 id %r 不在运镜目录里，按普通镜头生成" % (sid, cmid))
        if cmid:
            if cpick:
                _how = "LoRA %s @ %s" % (cpick[0], cpick[1])
                if mtrig:
                    _how += "｜触发词 " + mtrig[:32] + ("…" if len(mtrig) > 32 else "")
                if avail_lora is None:
                    _how += "（干跑：没核对本机是否有这个文件）"
            elif cmeta.get("need") == "lora":
                _how = "本机没有这个 LoRA → 降 T2，纯提示词"
            else:
                _how = "原生不挂 LoRA"
            print("      运镜：%s %s（%s%s）｜%s" % (cmid, cmeta.get("zh") or "", ctier or "-",
                                                   "·导演钦点" if clead else "", _how), flush=True)
        files, missing = [], []
        for r in seg.get("refs") or []:
            aid = r.get("asset") if isinstance(r, dict) else r
            a = assets.get(aid)
            if not a or not a.get("image"):
                missing.append(aid)
                continue
            files.append(os.path.join(p["proj"], a["image"]))
        if missing:
            rep.bad("%s 参考图缺失：%s（先跑 images）" % (sid, ", ".join(str(x) for x in missing)))
            continue
        audios = seg_audio(st, seg)
        gsec = gen_sec(seg.get("sec"))
        print("\n[%d/%d] %s｜提示词 %gs → 实传 %gs｜参考图 %d｜参考音 %d" % (
            i, len(targets), sid, float(seg.get("sec") or 0), gsec, len(files), len(audios)), flush=True)
        if args.dry:
            print("      参考音：" + (", ".join(os.path.basename(x) for x in audios) or "无（模型原生生成）"), flush=True)
            # dry-run 也把图建出来核对一遍，省得跑起来才发现模板对不上
            names = [os.path.basename(x) for x in files]
            anames = [os.path.basename(x) for x in audios]
            try:
                probe, _ = video_graph(
                    tpl, prompt, w, h, gsec, steps, seeds[i - 1], "drama/" + safe_id(sid),
                    names, max(1, len(names)), anames,
                    unet=unet, loras=lora_slots, motion_lora=motion,
                    clip=clip_m, video_vae=vvae, audio_vae=avae,
                    ratio=ratio, megapixels=mp,
                )
                probs = verify_graph(probe, names, anames, ratio=ratio, megapixels=mp,
                                     sparse=sparse, attn=attn, chunks=chunks,
                                     seq_threshold=seq_thr, head_chunks=head_chunks,
                                     loras=lora_slots, motion_lora=motion)
                for pr in probs:
                    rep.bad("%s 工作流自检：%s" % (sid, pr))
                if not probs:
                    rep.good("%s dry-run（工作流自检通过，%d 个节点）" % (sid, len(probe)))
            except Exception as e:
                rep.bad("%s 工作流自检出错：%s" % (sid, str(e)[:300]))
            continue

        try:
            uploaded = [comfy_api.upload_image(addr, f) for f in files]
            audio_names = [comfy_api.upload_audio(addr, f) for f in audios]
            graph, used = video_graph(
                tpl, prompt, w, h, gsec, steps, seeds[i - 1],
                "drama/" + safe_id(sid), uploaded, outputs_avail, audio_names,
                unet=unet, loras=lora_slots, motion_lora=motion,
                clip=clip_m, video_vae=vvae, audio_vae=avae,
                ratio=ratio, megapixels=mp,
                sparse=sparse, attn=attn, chunks=chunks,
                seq_threshold=seq_thr, head_chunks=head_chunks,
            )
            if used < len(uploaded):
                print("      注意：本段上传 %d 张参考图，实际挂载 %d 张（Picture 编号需与实际挂载一致）" % (len(uploaded), used), flush=True)
            jobs.append({"seg": seg, "sid": sid, "graph": graph, "pid": None, "t0": 0.0,
                         "_refs": uploaded, "_audios": audio_names, "_motion": motion})
        except Exception as e:
            seg["error"] = str(e)[:800]
            save_state(proj, st)
            rep.bad("%s 预处理失败：%s" % (sid, str(e)[:300]))
            if args.stop_on_error:
                break

    # ---- 工作流自检：拿第一条任务核对一遍，对不上就别往队列里塞 ----
    if jobs:
        bad = verify_graph(jobs[0]["graph"], jobs[0].get("_refs"), jobs[0].get("_audios"),
                           ratio=ratio, megapixels=mp, sparse=sparse, attn=attn,
                           chunks=chunks, seq_threshold=seq_thr, head_chunks=head_chunks,
                           loras=lora_slots, motion_lora=(jobs[0].get("_motion") if jobs else None))
        if bad:
            for b in bad:
                print("  [×] " + b, flush=True)
            die("H3 工作流模板与脚本对不上（%s）。上面几条就是具体是哪个节点的问题。" % H3_WF)

    if args.dry or not jobs:
        if not args.dry:
            _maybe_merge(args, proj, st, rep)
            build_html(proj, st)
        return rep.summary()

    # ---- 2) 入队：默认一次性全部塞进队列，ComfyUI 连续执行、模型全程驻留显存 ----
    def _submit(j):
        try:
            j["pid"] = comfy_api.queue(addr, j["graph"])
            j["t0"] = time.time()
            print("      已入队 %s（prompt_id %s）" % (j["sid"], j["pid"][:8]), flush=True)
            return True
        except Exception as e:
            j["seg"]["error"] = str(e)[:800]
            j["seg"]["status"] = "error"
            save_state(proj, st)
            rep.bad("%s 入队失败：%s" % (j["sid"], str(e)[:300]))
            return False

    def _collect(j, pid):
        """收一条结果。返回 True 表示这条已结束（成功或失败都算结束）。"""
        sid = j["sid"]
        try:
            entry = comfy_api.history(addr, pid)
            if not entry:
                return False
            status = entry.get("status") or {}
            if status.get("status_str") == "error":
                raise comfy_api.ApiError(json.dumps(status.get("messages") or [], ensure_ascii=False)[:1500])
            outputs = entry.get("outputs") or {}
            if not outputs:
                return False
            item = comfy_api.pick_video(outputs, H3_NODE.get("save"))
            if not item:
                raise comfy_api.ApiError("没有返回视频")
            ext = os.path.splitext(item["filename"])[1] or ".mp4"
            dest = os.path.join(p["videos"], safe_id(sid) + ext)
            comfy_api.download(addr, item, dest)
            j["seg"]["video"] = "videos/" + os.path.basename(dest)
            j["seg"]["status"] = "done"
            j["seg"]["genSecUsed"] = gen_sec(j["seg"].get("sec"))
            j["seg"].pop("error", None)
            save_state(proj, st)
            build_html(proj, st)
            rep.good("%s -> %s（%.1f 分钟）" % (sid, j["seg"]["video"], (time.time() - j["t0"]) / 60.0))
            return True
        except Exception as e:
            j["seg"]["error"] = str(e)[:800]
            j["seg"]["status"] = "error"
            save_state(proj, st)
            rep.bad("%s：%s" % (sid, str(e)[:300]))
            return True

    waiting = list(jobs)      # 还没提交的
    running = {}              # pid -> job
    total = len(jobs)

    if args.serial:
        print("\n[串行模式] 提交一条等一条（仅排查问题时用，每条都会重新加载模型）。", flush=True)
    else:
        print("\n[整批入队] 一次性把 %d 条 H3 任务 POST 进队列，ComfyUI 连续执行，"
              "模型只加载一次，不会每条重载。" % total, flush=True)
        while waiting:
            j = waiting.pop(0)
            if _submit(j):
                running[j["pid"]] = j
            elif args.stop_on_error:
                break
        if not running:
            return rep.summary()

    # ---- 3) 统一收结果：谁先完成先收谁 ----
    tick = 0
    started = time.time()
    while running or (args.serial and waiting):
        if args.serial and not running and waiting:
            j = waiting.pop(0)
            if _submit(j):
                running[j["pid"]] = j
                started = time.time()
                tick = 0
            else:
                continue
        for pid in list(running.keys()):
            if _collect(running[pid], pid):
                running.pop(pid)
        if not running and not (args.serial and waiting):
            break
        waited = time.time() - started
        if waited > args.timeout:
            for pid, j in list(running.items()):
                j["seg"]["error"] = "等待超时"
                j["seg"]["status"] = "error"
                rep.bad("%s 等待超时" % j["sid"])
            running.clear()
            save_state(proj, st)
            break
        if waited - tick >= 60:
            tick = waited
            print("      队列剩余 %d 条｜已完成 %d/%d｜已用 %.0f 分钟" % (
                len(running), total - len(running) - len(waiting), total, waited / 60.0), flush=True)
        time.sleep(3)

    s["seed"] = next_seed
    save_state(proj, st)
    # 全部段落都有成片了，自动拼一个整片出来（给用户审核用）
    _maybe_merge(args, proj, st, rep)
    build_html(proj, st)
    return rep.summary()


# ---------------------------------------------------------------- 参考音库
def cmd_voices(args):
    proj = os.path.abspath(args.project)
    st = load_state(proj)
    p = paths(proj)
    os.makedirs(p["voices"], exist_ok=True)

    if args.delete:
        vid = args.delete
        st["voices"] = [v for v in st["voices"] if v.get("id") != vid]
        for a in st["assets"]:
            if a.get("voice") == vid:
                a["voice"] = ""
        save_state(proj, st)
        print("已删除参考音 %s" % vid, flush=True)
        return 0

    if args.import_path:
        src = os.path.abspath(args.import_path)
        items = []
        if os.path.isdir(src):
            for name in sorted(os.listdir(src)):
                if name.lower().endswith(AUDIO_EXT):
                    items.append(os.path.join(src, name))
        elif os.path.isfile(src):
            items.append(src)
        if not items:
            die("没有找到音频文件（支持 %s）" % " / ".join(AUDIO_EXT))
        added = []
        for fp in items:
            base = os.path.splitext(os.path.basename(fp))[0]
            vid = "v" + str(len(st["voices"]) + 1)
            while any(v.get("id") == vid for v in st["voices"]):
                vid = "v" + str(int(vid[1:]) + 1)
            dest = os.path.join(p["voices"], safe_id(vid) + os.path.splitext(fp)[1].lower())
            shutil.copyfile(fp, dest)
            st["voices"].append({
                "id": vid,
                "name": args.name or base,
                "gender": args.gender or "",
                "age": args.age or "",
                "desc": args.desc or "",
                "file": "voices/" + os.path.basename(dest),
            })
            added.append(vid)
        save_state(proj, st)
        build_html(proj, st)
        print("已导入 %d 个参考音：%s" % (len(added), ", ".join(added)), flush=True)
        return 0

    print("参考音库（%d 个，%s）" % (len(st["voices"]), p["voices"]), flush=True)
    for v in st["voices"]:
        ok = v.get("file") and os.path.isfile(os.path.join(p["proj"], v["file"]))
        print("  %-4s %-24s %-4s %-8s %s" % (
            v.get("id"), (v.get("name") or "")[:24], v.get("gender") or "-",
            v.get("age") or "-", ("✓ " + v["file"]) if ok else "（未绑定音频）"), flush=True)
    return 0


# ---------------------------------------------------------------- 本地桥接服务
RUN = {"proc": None, "task": "", "started": 0.0}


def tail_log(p, n=3):
    try:
        with open(p["log"], "r", encoding="utf-8", errors="replace") as f:
            lines = [x.rstrip() for x in f if x.strip()]
        return " / ".join(lines[-n:])[-400:]
    except Exception:
        return ""


class _ExclusiveHTTPServer(ThreadingHTTPServer):
    """绑定端口时必须是独占的。

    Windows 的 SO_REUSEADDR 是「抢占式」语义：继承了 allow_reuse_address = 1 的
    ThreadingHTTPServer 在端口已被占用时**不会报错**，而是和旧进程同时 listen，
    浏览器的新连接会随机落到其中一个 —— 表现就是「打开的是上一个项目的工作台」。
    所以这里关掉 reuse，并额外加 SO_EXCLUSIVEADDRUSE 双保险。
    """
    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            try:
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            except OSError:
                pass
        ThreadingHTTPServer.server_bind(self)


def _port_taken(port):
    """127.0.0.1:<port> 是否已被占用（先试连接，再试独占绑定）。"""
    c = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    c.settimeout(0.25)
    try:
        if c.connect_ex(("127.0.0.1", int(port))) == 0:
            return True
    finally:
        c.close()
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            except OSError:
                pass
        s.bind(("127.0.0.1", int(port)))
        return False
    except OSError:
        return True
    finally:
        s.close()


def _pick_port(want, tries=24):
    """从 want 开始找一个真正空闲的端口。返回 (port, [被跳过的端口])。"""
    skipped = []
    for i in range(tries):
        cand = int(want) + i
        if not _port_taken(cand):
            return cand, skipped
        skipped.append(cand)
    return 0, skipped


def _serve_record_path(proj):
    return os.path.join(os.path.abspath(proj), ".serve.json")


def write_serve_record(proj, port, running=True):
    """把本项目当前的工作台地址落到项目目录，供 status / 后续步骤读真实端口。"""
    try:
        with open(_serve_record_path(proj), "w", encoding="utf-8") as f:
            json.dump({"port": int(port), "url": "http://127.0.0.1:%d/" % int(port),
                       "project": os.path.abspath(proj), "pid": os.getpid(),
                       "running": bool(running), "at": now_str()},
                      f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def fresh_url(port, tag=""):
    """给"呈现给人看"用的地址：每次带一个全新的 ?v= 版本串。

    为什么必须换地址：浏览器和预览面板都按 URL 判重，同一个地址第二次打开只做聚焦、
    不会重新加载 DOM。上一个阶段留下的页面还在那儿，人就一直在看旧数据（图片明明出好了却显示"未生成"）。
    所以每个阶段 / 每批图 / 每批视频呈现时，都必须拿一条**这个时刻才存在**的新地址。
    """
    return "http://127.0.0.1:%d/?v=%s" % (int(port), tag or time.strftime("%m%d%H%M%S"))


def _probe_title(port, timeout=1.2):
    """看这个端口上跑的是哪部剧（读 /api/state 的 meta.title）。

    本机地址必须绕开系统代理，否则会被 HTTP_PROXY 拦成 502。
    拿不到就返回空串 —— 调用方按"无法确认"处理，不要当成不匹配。
    """
    try:
        import urllib.request
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open("http://127.0.0.1:%d/api/state" % int(port), timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8"))
        return (((d or {}).get("state") or {}).get("meta") or {}).get("title") or ""
    except Exception:
        return ""


def read_serve_record(proj):
    """读本项目的 .serve.json。

    只有"端口有人听 + 那个端口上跑的确实是这部剧"才算在跑。
    否则就是端口被别的项目的工作台串台了，宁可当作没在跑。
    """
    fp = _serve_record_path(proj)
    if not os.path.isfile(fp):
        return None
    try:
        with open(fp, encoding="utf-8") as f:
            rec = json.load(f)
    except Exception:
        return None
    port = int(rec.get("port") or 0)
    if not port or not _port_taken(port):
        return None
    own = ""
    try:
        with open(os.path.join(os.path.abspath(proj), "drama.json"), encoding="utf-8") as f:
            own = ((json.load(f) or {}).get("meta") or {}).get("title") or ""
    except Exception:
        pass
    served = _probe_title(port)
    if served and own and served != own:
        print("[!] 端口 %d 上跑的其实是《%s》，不是本项目 —— 这个记录已作废。" % (port, served), flush=True)
        return None
    return rec


def make_handler(proj):
    p = paths(proj)

    class Handler(BaseHTTPRequestHandler):
        server_version = "DramaWorkbench/2.0"

        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json; charset=utf-8"):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, ensure_ascii=False).encode("utf-8")
            elif isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                self.wfile.write(body)
            except Exception:
                pass

        def _file(self, rel):
            ap = os.path.abspath(os.path.join(p["proj"], rel))
            if not ap.startswith(p["proj"]) or not os.path.isfile(ap):
                return self._send(404, {"ok": False, "error": "not found"})
            ctype = {
                ".html": "text/html; charset=utf-8",
                ".json": "application/json; charset=utf-8",
                ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
                ".mp4": "video/mp4", ".webm": "video/webm",
                ".wav": "audio/wav", ".mp3": "audio/mpeg", ".flac": "audio/flac",
                ".m4a": "audio/mp4", ".ogg": "audio/ogg", ".aac": "audio/aac", ".opus": "audio/ogg",
            }.get(os.path.splitext(ap)[1].lower(), "application/octet-stream")
            # 支持 Range：整片几十分钟、几十兆，用户要在播放器里拖动进度条
            size = os.path.getsize(ap)
            rng = self.headers.get("Range") or ""
            m = re.match(r"bytes=(\d*)-(\d*)", rng)
            if m and (m.group(1) or m.group(2)):
                start = int(m.group(1) or 0)
                end = int(m.group(2)) if m.group(2) else size - 1
                end = min(end, size - 1)
                if start > end:
                    start, end = 0, size - 1
                with open(ap, "rb") as f:
                    f.seek(start)
                    body = f.read(end - start + 1)
                self.send_response(206)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                try:
                    self.wfile.write(body)
                except Exception:
                    pass
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                with open(ap, "rb") as f:
                    shutil.copyfileobj(f, self.wfile)
            except Exception:
                pass

        def do_GET(self):
            path = unquote(urlparse(self.path).path)
            if path in ("/", "/index.html", "/workbench.html"):
                return self._file("workbench.html")
            if path == "/api/state":
                return self._send(200, {"ok": True, "state": load_state(p["proj"])})
            if path == "/api/models":
                # 每次都现读 ComfyUI 的 models 目录（不缓存），下拉里就不会留着已经删掉的模型
                addr2 = load_state(p["proj"])["settings"].get("comfy") or "http://127.0.0.1:8188"
                data = comfy_models(addr2, force=True)
                return self._send(200, {"ok": True, "unet": data["unet"], "lora": data["lora"],
                                        "clip": data["clip"], "vae": data["vae"],
                                        "ts": data["ts"], "error": data["error"]})
            if path == "/api/runstatus":
                running = bool(RUN["proc"] and RUN["proc"].poll() is None)
                return self._send(200, {"ok": True, "running": running, "tail": tail_log(p)})
            if path.startswith("/assets/") or path.startswith("/videos/") or path.startswith("/voices/"):
                return self._file(path.lstrip("/"))
            # 项目根目录的整片（成片.mp4）也要能播：只放行根级、常见媒体后缀，不给目录穿越留口子
            rel = path.lstrip("/")
            if rel and "/" not in rel and rel.lower().endswith(
                    (".mp4", ".mov", ".webm", ".png", ".jpg", ".jpeg", ".webp", ".mp3", ".wav", ".m4a")):
                return self._file(rel)
            return self._send(404, {"ok": False, "error": "not found"})

        def do_POST(self):
            path = unquote(urlparse(self.path).path)
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                return self._send(400, {"ok": False, "error": "body 不是合法 JSON"})

            if path == "/api/open-dir":
                try:
                    open_in_explorer(p["proj"])
                    return self._send(200, {"ok": True, "path": p["proj"]})
                except Exception as e:
                    return self._send(500, {"ok": False, "error": str(e)[:200], "path": p["proj"]})

            if path == "/api/save":
                st = data.get("state")
                if not isinstance(st, dict):
                    return self._send(400, {"ok": False, "error": "缺少 state"})
                cur = load_state(p["proj"])
                # 只补「页面没传」的字段：传了 false / 0 / 空串就照传。
                # 原来用 falsy 判断，开关类参数一旦取消勾选就会被磁盘里的 true 顶回去。
                merged = dict(cur.get("settings") or {})
                merged.update({k: v for k, v in (st.get("settings") or {}).items() if v is not None})
                st["settings"] = merged
                st = preserve_server_fields(st, cur)
                st = migrate(st)
                save_state(p["proj"], st)
                # 参数项顺手记进技能目录：下一部剧 init 自动沿用（剧情/资产不记）
                rdoc = remember_settings(st, p["proj"])
                build_html(p["proj"], st)
                stale = (data.get("diskStamp") or "") != ((cur.get("meta") or {}).get("updatedAt") or "")
                return self._send(200, {
                    "ok": True, "updatedAt": st["meta"]["updatedAt"], "stale": stale,
                    "remembered": bool(rdoc),
                    "rememberedAt": (rdoc or {}).get("updatedAt") or "",
                })

            if path == "/api/upload":
                aid = data.get("asset")
                blob = data.get("data") or ""
                if not aid or not blob:
                    return self._send(400, {"ok": False, "error": "缺少 asset 或 data"})
                if "," in blob[:80]:
                    blob = blob.split(",", 1)[1]
                st = load_state(p["proj"])
                target = next((a for a in st["assets"] if a.get("id") == aid), None)
                if not target:
                    return self._send(404, {"ok": False, "error": "没有这个资产：" + str(aid)})
                ext = os.path.splitext(data.get("filename") or "")[1].lower() or ".png"
                if ext not in (".png", ".jpg", ".jpeg", ".webp"):
                    ext = ".png"
                os.makedirs(p["assets"], exist_ok=True)
                dest = os.path.join(p["assets"], safe_id(aid) + ext)
                with open(dest, "wb") as f:
                    f.write(base64.b64decode(blob))
                target["image"] = "assets/" + os.path.basename(dest)
                target["status"] = "done"
                target["imageSource"] = "user-upload"
                target["imageVer"] = int(time.time())
                save_state(p["proj"], st)
                build_html(p["proj"], st)
                return self._send(200, {"ok": True, "image": target["image"]})

            if path == "/api/voice":
                blob = data.get("data") or ""
                if not blob:
                    return self._send(400, {"ok": False, "error": "缺少 data"})
                if "," in blob[:80]:
                    blob = blob.split(",", 1)[1]
                st = load_state(p["proj"])
                vid = str(data.get("voice") or "").strip()
                ext = os.path.splitext(data.get("filename") or "")[1].lower() or ".wav"
                if ext not in AUDIO_EXT:
                    ext = ".wav"
                os.makedirs(p["voices"], exist_ok=True)
                if not vid:
                    n = len(st["voices"]) + 1
                    vid = "v%d" % n
                    while any(v.get("id") == vid for v in st["voices"]):
                        n += 1
                        vid = "v%d" % n
                    st["voices"].append({
                        "id": vid, "name": data.get("name") or ("参考音 " + vid),
                        "gender": data.get("gender") or "", "age": data.get("age") or "",
                        "desc": data.get("desc") or "", "file": "",
                    })
                target = next(v for v in st["voices"] if v.get("id") == vid)
                dest = os.path.join(p["voices"], safe_id(vid) + ext)
                with open(dest, "wb") as f:
                    f.write(base64.b64decode(blob))
                target["file"] = "voices/" + os.path.basename(dest)
                if data.get("asset"):
                    a = next((x for x in st["assets"] if x.get("id") == data["asset"]), None)
                    if a:
                        a["voice"] = vid
                save_state(p["proj"], st)
                build_html(p["proj"], st)
                return self._send(200, {"ok": True, "voice": target})

            if path == "/api/run":
                task = data.get("task")
                only = data.get("only") or []
                if task not in ("images", "videos", "merge"):
                    return self._send(400, {"ok": False, "error": "task 只能是 images / videos / merge"})
                if RUN["proc"] and RUN["proc"].poll() is None:
                    return self._send(409, {"ok": False, "error": "已有生成任务在跑"})
                cmd = [sys.executable, os.path.abspath(__file__), task, "--project", p["proj"]]
                if only:
                    cmd += ["--only", ",".join(str(x) for x in only)]
                logf = open(p["log"], "ab")
                logf.write(("\n\n=== %s %s ===\n" % (now_str(), task)).encode("utf-8"))
                logf.flush()
                RUN["proc"] = subprocess.Popen(
                    cmd, stdout=logf, stderr=subprocess.STDOUT, cwd=p["proj"],
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                RUN["task"], RUN["started"] = task, time.time()
                return self._send(200, {"ok": True})

            return self._send(404, {"ok": False, "error": "not found"})

    return Handler


def cmd_serve(args):
    proj = os.path.abspath(args.project)
    p = paths(proj)
    if not os.path.isfile(p["json"]):
        die("没有 drama.json，先 init。")
    build_html(proj)

    want = int(args.port)
    port, skipped = _pick_port(want)

    # 探测与真正 bind 之间有竞态，这里再兜一层：绑不上就继续往后顺延
    httpd, err = None, ""
    for cand in range(port or want, (port or want) + 8):
        try:
            httpd = _ExclusiveHTTPServer(("127.0.0.1", cand), make_handler(proj))
            port = cand
            break
        except OSError as e:
            err = str(e)
            if cand not in skipped:
                skipped.append(cand)
    if httpd is None:
        die("端口 %d 起不来（%s）。先关掉占用 8765 的旧工作台，或换一个 --port。" % (want, err))
    if skipped:
        print("[!] 端口 %s 已被别的程序占用（多半是上一个项目的工作台还在跑）。"
              % "、".join(str(x) for x in skipped), flush=True)
        print("    已自动改用 %d —— 打开时请务必用下面这个地址，不要点旧书签/旧标签页。" % port, flush=True)

    write_serve_record(proj, port, True)
    url = "http://127.0.0.1:%d/" % port
    print("工作台根地址：%s" % url, flush=True)
    print("呈现给人看请用这条（带一次性版本串，每次 present 都要换新的）：%s"
          % fresh_url(port), flush=True)
    print("项目目录：%s" % proj, flush=True)
    print("关闭此窗口即停止服务（Ctrl+C）。", flush=True)
    if not args.no_open:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止。", flush=True)
    finally:
        write_serve_record(proj, port, False)
        httpd.server_close()
    return 0


# ---------------------------------------------------------------- init / build / status / check
def cmd_init(args):
    title = args.title or "未命名短剧"
    if args.project:
        proj = os.path.abspath(args.project)
    else:
        proj, root = default_project_dir(title)
        if not proj:
            die(
                "找不到系统「下载」目录，没法自动建项目。三点任选其一：\n"
                "   1) 设环境变量 DRAMA_PROJECT_ROOT 指向想放剧的目录\n"
                "   2) 技能目录建 config.json：{\"projectRoot\": \"D:/短剧\"}\n"
                "   3) 直接给 --project 指定目录",
                code=4,
            )
        print("项目根目录（系统下载）：%s" % root, flush=True)
    p = paths(proj)
    for k in ("assets", "videos", "voices"):
        os.makedirs(p[k], exist_ok=True)
    if os.path.isfile(p["json"]) and not args.force:
        st = load_state(proj)
        print("已存在 drama.json，保留原内容（--force 可重建）；仅重建 HTML。", flush=True)
    else:
        st = new_state(title, args.source or "")
        save_state(proj, st)
    html = build_html(proj, st)
    print("项目：%s" % proj, flush=True)
    print("数据：%s" % p["json"], flush=True)
    print("工作台：%s" % html, flush=True)
    print("\n下一步：", flush=True)
    print("  1) 把分段提示词 / 资产写进 drama.json（结构见 references/05-project-schema.md）", flush=True)
    print("  2) python drama.py build --project \"%s\"" % proj, flush=True)
    print("  3) python drama.py serve --project \"%s\"   # 然后必须把页面呈现给用户" % proj, flush=True)
    return 0


def cmd_present(args):
    """登记「这一版 HTML 已经给人看过了」。只有登记过才允许进第 2/3 阶段。"""
    proj = os.path.abspath(args.project)
    st = load_state(proj)
    h = state_hash(st)
    h2 = state_hash(st, with_images=True)
    st["meta"]["reviewedHash"] = h
    st["meta"]["reviewedAssetsHash"] = h2
    st["meta"]["reviewedAt"] = now_str()
    save_state(proj, st)
    print("已登记呈现：%s（提示词 %s｜含图 %s）" % (st["meta"]["reviewedAt"], h, h2), flush=True)
    print("现在可以进下一阶段；提示词再改一次就要重新 build + 呈现 + present。", flush=True)
    return 0


def cmd_build(args):
    proj = os.path.abspath(args.project)
    st = load_state(proj)
    st["_proj"] = proj
    for seg in st["segments"]:
        seg["genSec"] = gen_sec(seg.get("sec"))
    moved = extract_global_block(st)
    tags = [] if getattr(args, "no_audio_sync", False) else sync_audio_tags(st)
    save_state(proj, st)
    html = build_html(proj, st)
    pending_sync = sum(len(seg_edited(s)) for s in st["segments"])
    print("已生成 %s" % html, flush=True)
    print("分段 %d（合计 %.0f 秒 / 实传 %.0f 秒）｜资产 %d（已出图 %d）｜视频 %d｜待同步中文改动 %d 处" % (
        len(st["segments"]),
        sum(float(s.get("sec") or 0) for s in st["segments"]),
        sum(gen_sec(s.get("sec")) for s in st["segments"]),
        len(st["assets"]), len([a for a in st["assets"] if a.get("image")]),
        len([s for s in st["segments"] if s.get("video")]), pending_sync,
    ), flush=True)
    if getattr(args, "no_audio_sync", False):
        print("（--no-audio-sync）本次没有同步音色参考句，提示词内容与指纹保持不变", flush=True)
    if moved:
        print("全局画质与摄影前置已抽到参数区（原本重复在 %s 的段首）" % "、".join(moved), flush=True)
    if tags:
        print("音色已同步进提示词：%s" % "、".join(tags), flush=True)
    return 0


def cmd_status(args):
    proj = os.path.abspath(args.project)
    st = load_state(proj)
    addr = args.addr or st["settings"]["comfy"]
    ok, detail = comfy_api.ping(addr)
    print("项目：%s" % proj, flush=True)
    print("ComfyUI：%s" % ("在线 " + comfy_api.normalize(addr) if ok else "离线（" + detail + "）"), flush=True)
    print("生图：UNet %s｜CLIP %s｜VAE %s｜%s 步" % (
        st["settings"].get("imgUnet"), st["settings"].get("imgClip"), st["settings"].get("imgVae"),
        st["settings"].get("imgSteps")), flush=True)
    print("H3 参数：%s / %s MP / %s 步｜CLIP %s" % (
        st["settings"]["ratio"], st["settings"]["megapixels"], st["settings"]["steps"],
        st["settings"].get("h3Clip")), flush=True)
    print("", flush=True)
    print("分段 %d｜资产 %d｜参考音 %d" % (len(st["segments"]), len(st["assets"]), len(st["voices"])), flush=True)
    rec = read_serve_record(proj)
    if rec:
        print("工作台：%s（本项目的服务正在跑）" % rec.get("url"), flush=True)
        try:
            print("本次呈现请用这条新地址：%s" % fresh_url(rec.get("port") or 8765), flush=True)
        except Exception:
            pass
    else:
        print("工作台：未启动（用 serve 起，端口被占用会自动顺延，以打印的地址为准）", flush=True)
    if st["assets"]:
        print("\n资产：", flush=True)
        for a in st["assets"]:
            print("  %-6s %-9s %-14s %s" % (
                a.get("id"), a.get("type"), (a.get("name") or "")[:14],
                "✓ " + a["image"] if a.get("image") else "待生成"), flush=True)
    if st["segments"]:
        print("\n分段：", flush=True)
        for s in st["segments"]:
            print("  %-8s %4.0fs→%2ds 参考图%d 提示词%s 视频%s" % (
                s.get("id"), float(s.get("sec") or 0), gen_sec(s.get("sec")),
                len(s.get("refs") or []),
                "✓" if seg_prompt(s, st["meta"].get("globalBlock")) else "×",
                ("✓ " + s["video"]) if s.get("video") else "待生成"), flush=True)
    fin = st["meta"].get("finalVideo")
    if fin:
        print("\n成片：%s（%s 段｜%.1f 秒｜合并于 %s）" % (
            fin, len(st["meta"].get("finalVideoParts") or []),
            float(st["meta"].get("finalVideoSec") or 0), st["meta"].get("finalVideoAt") or "?"), flush=True)
    elif st["segments"] and all(x.get("video") for x in st["segments"]):
        print("\n成片：还没合并（跑 `merge` 一条命令就出）", flush=True)
    return 0


# ------------------------------------------------- H3 落地八条（可机检的部分）
H3_SHOT_RE = re.compile(r"^\[Shot\s*(\d+)\]", re.I)

# 2026-10-19 用户钦定：H3 提示词按官方长提示词格式输出，固定六块，顺序不许变
H3_BLOCKS = (
    ("subject_definitions:", "主体定义（Subject/Audio 对应哪张图、什么外观、本段开场站位）"),
    ("summary:", "本段剧情概括"),
    ("retention_analysis:", "逐 Subject 的保真说明"),
    ("detailed_description:", "全局风格/画幅/禁止项 + 每个 [Shot N]"),
    ("overall_soundscape:", "环境声"),
    ("non_diegetic_music:", "配乐（没有就写 N/A）"),
)
# Shot 里不许写死时长：At 00:03.000 / [0-3秒] / 前 2 秒
TIMECODE_RE = re.compile(
    r"\bAt\s+\d{1,2}:\d{2}(?::\d{2})?|\b\d{1,2}:\d{2}\.\d{2,3}\b|\[\d+\s*[-–~]\s*\d+\s*秒?\]"
    r"|前\s*\d+\s*秒|后\s*\d+\s*秒", re.I)

SCENE_GROUPS = {
    "客厅": ("living room", "sofa", "couch", "客厅", "沙发"),
    "卧室": ("bedroom", "卧室"),
    "厨房": ("kitchen", "厨房"),
    "浴室": ("bathroom", "浴室", "卫生间"),
    "餐厅": ("restaurant", "餐厅", "饭馆"),
    "街道": ("street", "sidewalk", "街道", "马路"),
    "车内": ("car interior", "车内"),
    "办公室": ("office", "办公室"),
    "阳台": ("balcony", "阳台"),
    "电梯": ("elevator", "电梯"),
}
# 2026-10-19 用户要求取消「每镜必须写背景落点」：场景只在场景段声明一次，Shot 不再复述背景
BACKDROP_RESTATE = ("wall behind", "sofa back", "backdrop", "身后的墙", "身后是", "背景是")
PSY_HARD = ("内心os", "内心独白", "心里想", "暗想", "心想", "意识到", "明白了", "决定要",
            "inner monologue", "voice-over", "realizes", "realises", "decides to",
            "thinks to himself", "thinks to herself", "inwardly", "mentally")
PSY_SOFT = ("若有所思", "意味深长", "尴尬", "紧张", "心虚", "得意", "生气", "难过", "开心",
            "nervous", "awkward", "embarrassed", "smug", "proud", "angry", "happy", "sad")
HAND_FINE = ("指尖", "精细", "拨弄", "捻", "搓", "解开", "系上", "扣上", "拧开", "熟练地",
             "deftly", "nimbly", "fingertips", "fiddles", "twirls", "unbuttons",
             "scrolls his thumb", "scrolls her thumb", "swipes her thumb", "swipes his thumb")
CINE_BAD = ("升格", "跟焦", "浅景深", "拉焦", "变焦", "荷兰角", "摇臂", "轨道车", "斯坦尼康",
            "slow motion", "rack focus", "shallow depth of field", "dutch angle",
            "dolly zoom", "crane shot", "steadicam")
CINE_OK = ("push", "pull", "pan", "tilt", "track", "dolly", "close-up", "close up",
           "medium shot", "full shot", "wide shot", "reverse", "over-the-shoulder",
           "over the shoulder", "over-the-waist", "over the waist",
           "推", "拉", "摇", "跟", "移",
           "近景", "中景", "全景", "特写", "正反打", "过肩", "过脸", "过腰")
EVENT = ("walks", "enters", "sits down", "stands up", "turns", "picks up", "puts down",
         "hands it", "pushes", "lies down", "crosses over",
         "走进", "走进来", "坐下", "坐到", "站起", "起身", "转身", "拿起", "放下", "递给",
         "推开", "跨过", "躺下")
POSE = ("seated", "sits", "sitting", "stands", "standing", "leaning", "lies", "lying",
        "sprawled", "slumped", "perched", "hunched", "settled low",
        "坐在", "坐着", "站着", "靠在", "躺着", "坐到", "瘫", "半躺", "斜靠")
POSE_MOVE = ("stands up", "rises", "gets up", "climbs", "站起", "起身", "站起来")
NEAR = ("beside", "next to", "against", "close to", "in his arms", "shoulder to shoulder",
        "same sofa", "face to face", "within arm", "并肩", "贴着", "靠在一起", "同一张沙发", "面对面")
FAR = ("across the room", "far side", "other end of the room", "at the door", "in the doorway",
       "房间另一端", "对面墙", "门口", "远处")
# 每段独立生成：这些词都是"拿上一段当上下文"，模型看不到，直接判硬问题
CONTEXT_REF = ("still sitting", "still seated", "still standing", "still leaning", "still sprawled",
               "still slumped", "still facing", "still holding", "still on the same",
               "still holding the same", "remains seated", "remains sitting", "remains standing",
               "continues to sit", "continues to stand", "as before", "as in the previous",
               "same as the previous", "from the last shot", "same sofa", "同一张沙发", "仍然", "依旧",
               "还是坐在", "仍坐在", "仍在原地", "继续坐在", "和上一段", "如前", "接着上")
# Shot 里不许出现的光影词（全局光影已在场景段声明；裸 "light" 会误伤 light grey，故不收）
LIGHT_WORDS = ("lighting", "key light", "warm key", "cool key", "key from", "rim light",
               "bright rim", "rim along", "rim on", "backlight", "back light", "side light",
               "top light", "fill light", "soft light", "hard light", "warm light", "cool light",
               "sunlight", "moonlight", "lamp light", "light from", "light falls", "light hits",
               "shadow", "shadows", "half a stop", "主光", "辅光", "轮廓光", "侧光", "逆光", "顶光",
               "打光", "补光", "光线", "灯光", "光斑", "亮边", "高光", "阴影", "色温")
# Shot 里的"画面构图位置"（人物没动就不该写）
FRAME_POS = ("frame left", "frame right", "left side of the frame", "right side of the frame",
             "left half of the frame", "right half of the frame", "center of the frame",
             "画面左", "画面右", "画面中心", "左半边", "右半边")
# 站位锚点：本段开场状态必须写清"人在哪儿"
POS_ANCHOR = ("sofa", "couch", "bed", "chair", "stool", "floor", "desk", "table", "counter",
              "door", "doorway", "window", "kitchen", "hallway", "stairs", "armchair",
              "left", "right", "side", "corner", "沙发", "床", "椅", "地板", "桌", "台面",
              "门口", "窗", "厨房", "走廊", "楼梯", "左", "右", "角落", "里侧", "外侧")
# 关系镜头（过脸 / 过肩 / 过腰 / 正反打）
OTS = ("over-the-shoulder", "over the shoulder", "over-the-face", "over the face",
       "past her cheek", "past his cheek", "over-the-waist", "over the waist",
       "past his waist", "past her waist", "reverse shot", "reverse angle",
       "过肩", "过脸", "过腰", "正反打")
PERF = ("expression", "eyebrow", "smirk", "grin", "frown", "jaw", "lip", "breath", "blink",
        "stare", "eyes", "face",
        "表情", "神色", "眼神", "嘴角", "眉", "呼吸", "下巴", "眨眼", "脸")
TONE_BAD = ("solemn", "somber", "tragic", "沉痛", "悲壮", "凝重", "肃穆")


def _seg_shots(seg, lang="en"):
    """取出该段的 [Shot N] 块（英文，模型实际吃的那份）。"""
    out = []
    for b in seg.get("promptSegs") or []:
        t = (b.get(lang) or "").strip()
        m = H3_SHOT_RE.match(t)
        if m:
            out.append((int(m.group(1)), t))
    return out


def _h3_block_text(seg, name):
    """取六段式里某一块的英文正文（块名行起，到下一个块名为止）。"""
    out, on = [], False
    for p in seg.get("promptSegs") or []:
        t = (p.get("en") or "").strip()
        if not t:
            continue
        m = re.match(r"^([a-z_]+):", t)
        if m:
            on = (m.group(1) + ":") == name
            if on:
                out.append(t)
            continue
        if on:
            out.append(t)
    return "\n".join(out)


def _hits(text, words):
    low = (text or "").lower()
    return [w for w in words if w and w in low]


def _split_words(s):
    return [w.lower() for w in re.split(r"[，,。;；/、\s]+", s or "") if len(w) >= 2]


def _ratio_wh(ratio):
    """把 16:9 / 9:16 这类字符串解析成 (w, h)，解析不了返回 None。"""
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*[:：]\s*(\d+(?:\.\d+)?)\s*$", str(ratio or ""))
    if not m:
        return None
    a, b = float(m.group(1)), float(m.group(2))
    return (a, b) if b else None


def check_h3_rules(st, issues, warns):
    """H3 落地规则 + 构图与连续性四铁律（画幅同框 / 关系镜头 / 每段独立 / Shot 不写光影与位置）。"""
    ratio = str((st.get("settings") or {}).get("ratio") or "")
    wh = _ratio_wh(ratio)
    aspect = (wh[0] / wh[1]) if wh else None
    narrow = ratio in ("9:16", "3:4", "2:3", "9:21", "1:2") or (aspect is not None and aspect < 1.0)
    wide = aspect is not None and aspect >= 1.3
    ots_used = 0

    # 画幅一致性：detailed_description 首句（或旧版全局块）写死的画幅必须与视频参数一致
    gb = (st.get("meta") or {}).get("globalBlock") or {}
    gb_text = " ".join(str(gb.get(k) or "") for k in ("en", "zh"))
    for _s in st.get("segments") or []:
        gb_text += "\n" + " ".join((p.get("en") or "") + " " + (p.get("zh") or "")
                                   for p in (_s.get("promptSegs") or []))
    declared = [r for r in ("9:16", "16:9", "4:3", "3:4", "1:1", "21:9") if r in gb_text]
    if ratio and declared and ratio not in declared:
        issues.append("提示词里写的是 %s 画幅，但视频参数是 %s → 提示词和实际画幅打架，"
                      "模型会按错画幅构图；把 detailed_description 首句改成 %s" % (
                          "、".join(declared), ratio, ratio))
    elif ratio and len(set(declared)) > 1:
        warns.append("提示词里出现了多个画幅（%s），只保留 %s 一个" % ("、".join(declared), ratio))
    if "focus held on the face in every shot" in gb_text.lower():
        warns.append("提示词里写了 focus held on the face in every shot（每镜都锁脸）→ 和"
                     "「焦点给前景还是后景」冲突，删掉这句，让每个 Shot 自己决定")
    props = [a for a in st.get("assets") or [] if a.get("type") == "prop"]
    prop_words = []
    for a in props:
        prop_words += _split_words((a.get("name") or "") + " " + (a.get("note") or ""))

    total = 0
    for seg in st.get("segments") or []:
        sid = seg.get("id")
        shots = _seg_shots(seg)
        if not shots:
            warns.append("%s 没有 [Shot N] 分段，H3 会把整段当一个长镜头乱切" % sid)
            continue
        total += len(shots)

        # ⑪ 六段式结构（2026-10-19 用户钦定，按官方 H3 长提示词格式）
        seg_all = "\n".join((p.get("en") or "") for p in seg.get("promptSegs") or [])
        miss = [n for n, _ in H3_BLOCKS
                if not re.search(r"(?im)^[ \t]*" + re.escape(n), seg_all)]
        if miss:
            issues.append("%s 缺六段式块：%s → 必须按 subject_definitions / summary / "
                          "retention_analysis / detailed_description / overall_soundscape / "
                          "non_diegetic_music 六块输出，块名英文小写加冒号、顶格" % (sid, "、".join(miss)))
        else:
            pos = [re.search(r"(?im)^[ \t]*" + re.escape(n), seg_all).start() for n, _ in H3_BLOCKS]
            if pos != sorted(pos):
                warns.append("%s 六个块的顺序乱了，应为 subject_definitions → summary → "
                             "retention_analysis → detailed_description → overall_soundscape → "
                             "non_diegetic_music" % sid)
        def_text = _h3_block_text(seg, "subject_definitions:")
        ret_text = _h3_block_text(seg, "retention_analysis:")
        no_ret = sorted(set(re.findall(r"<Subject\s*(\d+)>", def_text))
                        - set(re.findall(r"<Subject\s*(\d+)>", ret_text)))
        if no_ret:
            warns.append("%s 的 retention_analysis 漏了 <Subject %s>，保真说明要逐个主体写" % (
                sid, "、".join(no_ret)))
        if not def_text.strip():
            warns.append("%s 的 subject_definitions 是空的，模型认不出 <Subject N> 是谁" % sid)

        # 本段出场人物：<Subject K>NAME → K（点名和 <Subject K> 都折算成同一个编号，避免重复计数）
        subj_idx = {}
        for b in seg.get("promptSegs") or []:
            t = b.get("en") or ""
            if H3_SHOT_RE.match(t.strip()):
                continue
            for mm in re.finditer(
                    r"<Subject\s*(\d+)>\s*([A-Z][A-Za-z'’]+(?:\s+[A-Z][A-Za-z'’]+)*)", t):
                subj_idx[mm.group(2).strip()] = int(mm.group(1))

        def _who(text):
            ids = set(int(x) for x in re.findall(r"<Subject\s*(\d+)>", text))
            ids |= set(int(x) for x in re.findall(r"\bS(\d)\b", text))
            for nm, i in subj_idx.items():
                if nm in text:
                    ids.add(i)
            return ids

        # ① 场景不穿帮：只查"一段里换了空间"；背景只写在场景段，Shot 不再要求背景落点
        scene_hit = {}
        for name, kws in SCENE_GROUPS.items():
            for n, t in shots:
                if _hits(t, kws):
                    scene_hit.setdefault(name, []).append(n)
        if len(scene_hit) >= 2:
            warns.append("%s 一段里出现了多个空间（%s），背景会跳；写清移动过程或拆段" % (
                sid, "、".join(sorted(scene_hit))))

        # ③ 风格贯穿
        if not any(_hits(t, PERF) for _, t in shots):
            warns.append("%s 通篇没有可见的表演（表情/眼神/呼吸），容易被演成严肃正剧" % sid)
        bad_tone = [n for n, t in shots if _hits(t, TONE_BAD)]
        if bad_tone:
            warns.append("%s 的 Shot %s 用了正剧化词，与轻喜剧调性冲突" % (
                sid, ",".join(map(str, bad_tone))))

        # ④ 抽象转具象
        for n, t in shots:
            h = _hits(t, PSY_HARD)
            if h:
                issues.append("%s 的 Shot %d 有心理/旁白描述（%s）→ 模型演不出来，换成可见表情与动作" % (
                    sid, n, "、".join(h[:3])))
            s = _hits(t, PSY_SOFT)
            if s:
                warns.append("%s 的 Shot %d 用了抽象情绪词（%s），换成具体表情/小动作" % (
                    sid, n, "、".join(s[:3])))
            hh = _hits(t, HAND_FINE)
            if hh:
                warns.append("%s 的 Shot %d 有精细手部操作（%s），H3 手部弱，降级成「手持某物」" % (
                    sid, n, "、".join(hh[:3])))

        # ⑤ 时序与连续性（姿势只在本段场景段交代，Shot 里不再重复）
        for n, t in shots:
            ev = _hits(t, EVENT)
            if len(ev) >= 3:
                warns.append("%s 的 Shot %d 一镜塞了 %d 个事件（%s），要拆镜" % (
                    sid, n, len(ev), "、".join(ev)))
        # 相邻镜姿势跳变：只比较同一个人（按 <Subject N> 认人，不写死人名）
        prev = {}
        for n, t in shots:
            low = t.lower().replace("standing out", "").replace("stands out", "")
            cur = "坐" if _hits(low, ("seated", "sits", "sitting", "sprawled", "slumped",
                                      "perched", "坐在", "坐着", "瘫")) else (
                "站" if _hits(low, ("stands", "standing", "站着")) else None)
            who = sorted(_who(t))
            for w in who:
                if cur and prev.get(w) and prev[w] != cur and not _hits(t, POSE_MOVE):
                    warns.append("%s 的 Shot %d 姿势从%s直接变%s、中间没有过渡动作 → 会瞬移" % (
                        sid, n, prev[w], cur))
                if cur:
                    prev[w] = cur

        # ⑨ 每段独立（ComfyUI 逐段生成，模型看不到上一段）：不许跨段指代 + 场景段必须写开场站位
        scene_text = "\n".join((b.get("en") or "") + " " + (b.get("zh") or "")
                               for b in seg.get("promptSegs") or []
                               if not H3_SHOT_RE.match((b.get("en") or "").strip()))
        ctx = _hits(scene_text + "\n" + "\n".join(t for _, t in shots), CONTEXT_REF)
        if ctx:
            issues.append("%s 用了跨段指代（%s）→ 每段单独送进 ComfyUI，模型没有上一段的记忆，"
                          "本段开场状态必须重写一遍" % (sid, "、".join(ctx[:3])))
        if not _hits(scene_text, POSE):
            issues.append("%s 的场景段没写本段开场站位/姿势（坐/站/靠/躺）→ 模型只能瞎猜，"
                          "上一段结尾的姿势接不上" % sid)
        elif not _hits(scene_text, POS_ANCHOR):
            warns.append("%s 的场景段写了姿势但没写人在哪（沙发左/右、床、门口…），站位会飘" % sid)

        # ⑩ Shot 不写光影（全局已有）；人物没移动就不写画面位置；不写死时长
        for n, t in shots:
            tc = TIMECODE_RE.findall(t)
            if tc:
                issues.append("%s 的 Shot %d 写死了时长（%s）→ 每个 Shot 只写运镜/景别/动作，"
                              "镜头长短交给模型，时间码全部删掉" % (sid, n, tc[0]))
            if _hits(t, OTS):
                ots_used += 1
            lg = _hits(t, LIGHT_WORDS)
            if lg:
                issues.append("%s 的 Shot %d 写了光影（%s）→ 全局光影已声明，每镜再写会把光位带跑，删掉" % (
                    sid, n, "、".join(lg[:3])))
            fp = _hits(t, FRAME_POS)
            if fp and not _hits(t, EVENT):
                warns.append("%s 的 Shot %d 人物没移动却写了画面位置（%s），模型会重排站位，删掉" % (
                    sid, n, "、".join(fp[:3])))
            bg = _hits(t, BACKDROP_RESTATE)
            if bg:
                warns.append("%s 的 Shot %d 复述了背景（%s）→ 场景段已经声明过一次，"
                             "Shot 只写这一镜的动作，删掉这句" % (sid, n, "、".join(bg[:3])))

        # ⑥ 术语
        bad = list(dict.fromkeys(w for _, t in shots for w in _hits(t, CINE_BAD)))
        if bad:
            warns.append("%s 用了 H3 不认识的电影术语（%s），换大白话" % (sid, "、".join(bad)))
        if not any(_hits(t, CINE_OK) for _, t in shots):
            warns.append("%s 全段没有可识别的镜头术语（推/拉/摇/跟/近景/中景/全景），H3 会自己乱运镜" % sid)

        # ② 关键道具
        if props:
            for n, t in shots:
                if _hits(t, ("holding", "picks up", "puts down", "hands it", "拿", "握", "递", "放下")) \
                        and not _hits(t, prop_words):
                    warns.append("%s 的 Shot %d 有持物动作但没写拿的是什么" % (sid, n))
            seg_text = " ".join(t for _, t in shots).lower()
            gone = [a.get("id") for a in props
                    if not any(w in seg_text for w in _split_words(
                        (a.get("name") or "") + " " + (a.get("note") or "")))]
            if gone:
                warns.append("%s 建了道具 %s 但镜头里没出现，关键道具不能凭空消失" % (sid, "、".join(gone)))

        # ⑦ 画幅决定同框　⑧ 窄屏一律双人分镜
        for n, t in shots:
            subs = _who(t)
            if t.count("<d>") >= 2:
                issues.append("%s 的 Shot %d 里两个人在说话，一镜只允许一人说话，必须分镜" % (sid, n))
            if len(subs) < 2:
                continue
            if narrow:
                issues.append("%s 的 Shot %d 在 %s 窄屏里让两人同框 → 会被劈成左右两半，"
                              "必须拆成正反打一人一镜" % (sid, n, ratio or "窄屏"))
            elif wide and _hits(t, FAR) and not _hits(t, NEAR):
                issues.append("%s 的 Shot %d 让两人隔着整个房间同框 → 宽屏也会拍成两个小人，"
                              "拆成正反打或写清走近" % (sid, n))
            elif not (wide or _hits(t, NEAR)):
                warns.append("%s 的 Shot %d 方屏双人同框但没写并肩/贴身，有劈屏风险" % (sid, n))

    if total and not ots_used:
        warns.append("全片没有用过脸/过肩/过腰/正反打这类关系镜头 → 都成了平面单人照，"
                     "至少给关键对话配一次过肩或正反打")
    if total:
        print("H3 落地规则 + 构图连续性四铁律：%d 段 / %d 个镜头（画幅同框·关系镜头·逐段独立·无光影无背景复述）" % (
            len(st.get("segments") or []), total), flush=True)


# ---------------------------------------------------------------- 运镜与跨段衔接
SHOT_MARK = re.compile(r"\[\s*(?:Shot|镜头)\s*(\d+)\s*\]", re.I)

SIZE_HINTS = (
    ("extreme close", "near"), ("extreme-close", "near"), ("medium close", "near"),
    ("close-up", "near"), ("close up", "near"), ("head and shoulders", "near"),
    ("head-and-shoulders", "near"), ("chest-up", "near"), ("big close", "near"),
    ("medium-wide", "mid"), ("medium wide", "mid"), ("waist up", "mid"),
    ("waist-up", "mid"), ("medium shot", "mid"), ("two-shot", "mid"), ("medium", "mid"),
    ("full-body", "wide"), ("full body", "wide"), ("wide shot", "wide"),
    ("establishing", "wide"), ("overhead", "wide"), ("top-down", "wide"),
    ("aerial", "wide"), ("wide", "wide"),
    ("大特写", "near"), ("特写", "near"), ("中近景", "near"), ("近景", "near"),
    ("中景", "mid"), ("双人", "mid"),
    ("大全", "wide"), ("全景", "wide"), ("远景", "wide"), ("俯拍", "wide"),
)

DIR_HINTS = (
    ("over-the-shoulder", "ots"), ("over the shoulder", "ots"), ("过肩", "ots"),
    ("top-down", "top"), ("overhead", "top"), ("顶拍", "top"), ("俯拍", "top"),
    ("from behind", "back"), ("behind him", "back"), ("behind her", "back"),
    ("背向", "back"), ("身后", "back"),
    ("from the side", "side"), ("side view", "side"), ("侧面", "side"),
    ("front", "front"), ("正面", "front"), ("面向镜头", "front"),
)


def split_shots(seg, key="en"):
    """把一个段拆成 [{n, t}]：按 [Shot N] / [镜头 N] 切；没有标记就整段算一个镜头。"""
    text = "\n".join((p.get(key) or "") for p in (seg.get("promptSegs") or []))
    if not text.strip():
        text = seg.get("prompt") or ""
    parts = SHOT_MARK.split(text)
    shots = []
    for i in range(1, len(parts), 2):
        try:
            n = int(parts[i])
        except (TypeError, ValueError):
            continue
        body = parts[i + 1] if i + 1 < len(parts) else ""
        shots.append({"n": n, "t": body})
    if not shots and text.strip():
        shots = [{"n": 1, "t": text}]
    return shots


def _hint(text, table):
    low = (text or "").lower()
    for key, val in table:
        if key in low:
            return val
    return ""


def shot_signature(seg, key="en"):
    """本段首/尾两个镜头的「机位指纹」：(景别, 机位方向)。用来判断跨段拼接会不会闪。"""
    shots = split_shots(seg, key)
    if not shots:
        return None, None
    def sig(sh):
        t = sh["t"]
        return {"n": sh["n"], "size": _hint(t, SIZE_HINTS), "dir": _hint(t, DIR_HINTS), "t": t}
    return sig(shots[0]), sig(shots[-1])


def check_camera(st, issues, warns, avail=None):
    """运镜目录 + 运镜 LoRA + 跨段首尾镜头重复。

    跨段规则（用户钦定）：上一段最后一个 Shot 是 A 在说话/行动、剧情没完，
    下一段第一个 Shot 还是 A 时，**机位必须换**——同景别 + 同方向拼起来会闪或人物跳动。
    """
    segs = [x for x in (st.get("segments") or []) if isinstance(x, dict)]
    if not segs:
        return
    # 1) 运镜 id 合法性 + 档位（T0 导演钦点 / T1 近景 / T2 中景 / T3 本机缺文件）
    leads = []
    for seg in segs:
        sid = seg.get("id") or "?"
        c = camera_of(seg)
        mid = str(c.get("move") or "").strip()
        lead = camera_lead(seg)
        if not mid:
            if lead:
                warns.append("%s 标了「导演钦点（T0）」但没选运镜 → 勾了就要有具体运镜，"
                             "或者把钦点取消" % sid)
            continue
        mv = CAMERA_MOVES.get(mid)
        if not mv:
            issues.append("%s 的运镜 id %r 不在运镜目录里（见 references/camera-moves.json）" % (sid, mid))
            continue
        tier = camera_tier(mid, avail, lead=lead)
        if lead:
            leads.append(sid)
        if tier == "T3":
            if lead:
                warns.append("%s 钦点（T0）的「%s」要挂运镜 LoRA，本机没有对应文件 → 只能按 T3 处理："
                             "不挂、不写触发词、用降级句。想让这个镜头成立，换一条同功能的原生运镜"
                             "（见 06-camera-moves 的降级列）" % (sid, mv.get("zh")))
            else:
                warns.append("%s 用「%s」，它要挂运镜 LoRA，本机没有对应文件 → 降 T3，"
                             "只靠提示词写；可换等价的原生运镜（见 06-camera-moves 的降级列）"
                             % (sid, mv.get("zh")))
        if not (c.get("why") or "").strip():
            warns.append("%s 选了运镜「%s」但没写为什么用（camera.why）→ 运镜要有戏因，不是装饰"
                         % (sid, mv.get("zh")))
    # 钦点太多 = 没有钦点：一段戏里最重的那个才配 T0
    if len(leads) > max(2, len(segs) // 2):
        warns.append("有 %d 段标了「导演钦点（T0）」（%s）→ 钦点太密就没有主次了，"
                     "一部剧留 1–2 个最重的 T0 就够" % (len(leads), "、".join(leads)))
    # 2) 相邻两段用了同一个运镜 → 拼起来像一条，缺少段落感
    for a, b in zip(segs, segs[1:]):
        ma = str(camera_of(a).get("move") or "").strip()
        mb = str(camera_of(b).get("move") or "").strip()
        if ma and ma == mb:
            warns.append("%s 与 %s 用了同一个运镜（%s）→ 连着看会像一镜，建议换一个"
                         % (a.get("id"), b.get("id"), (CAMERA_MOVES.get(ma) or {}).get("zh") or ma))
    # 3) 跨段首尾镜头：同景别 + 同方向 = 拼接会闪/人物跳动
    for a, b in zip(segs, segs[1:]):
        cast_a = set(a.get("cast") or [])
        cast_b = set(b.get("cast") or [])
        if cast_a and cast_b and not (cast_a & cast_b):
            continue                      # 两段没有同一个人，接不上就是另一回事
        _, tail = shot_signature(a)
        head, _ = shot_signature(b)
        if not tail or not head:
            continue
        if tail["size"] and tail["size"] == head["size"] and tail["dir"] and tail["dir"] == head["dir"]:
            same_move = (str(camera_of(a).get("move") or "") == str(camera_of(b).get("move") or ""))
            msg = ("%s 最后 1 个镜头（Shot %d）和 %s 第 1 个镜头（Shot %d）是同一机位"
                   "（同为%s、同为%s）→ 拼接会闪屏或人物跳一下。换景别或换机位方向，两段之间至少差一项"
                   % (a.get("id"), tail["n"], b.get("id"), head["n"],
                      {"near": "近景", "mid": "中景", "wide": "全景"}.get(tail["size"], tail["size"]),
                      {"ots": "过肩", "top": "俯视", "back": "背向", "side": "侧向", "front": "正面"}.get(tail["dir"], tail["dir"])))
            (issues if same_move else warns).append(msg)


def cmd_check(args):
    proj = os.path.abspath(args.project)
    st = load_state(proj)
    st["_proj"] = proj
    p = paths(proj)
    issues, warns = [], []

    if not (st["meta"].get("hook") or "").strip():
        warns.append("简介页没有「一句话钩子」，0–3 秒抓不住人")
    if not (st["meta"].get("synopsis") or "").strip():
        warns.append("简介页没有「视频简介」")
    if not (st["meta"].get("styleLock") or "").strip():
        warns.append("没有「统一美术风格锁」，资产容易一张写实一张二次元")
    cblk = char_block(st)
    csx = (st["settings"].get("charSheet") or {})
    if csx.get("edited") and (csx.get("zh") or "").strip():
        warns.append("人物视图模板的中文改过了、英文还没同步 → 现在送进模型的是中文那版（能用，"
                     "但建议让 AI 按原格式重写英文，并清掉 edited 标记）")
    for a in st["assets"]:
        if a.get("type") == "character":
            r = str(a.get("ratio") or TYPE_RATIO["character"])
            tpl_ratio = ""
            m = re.search(r"(\d{1,2})\s*[:：]\s*(\d{1,2})", cblk)
            if m:
                tpl_ratio = "%s:%s" % (m.group(1), m.group(2))
            if tpl_ratio and r.replace("：", ":") != tpl_ratio:
                warns.append("%s（%s）是人物资产，画布比例是 %s，但人物视图模板里写的是 %s → 面板会被裁掉或留白，"
                             "把资产卡上的比例改成 %s" % (a.get("id"), a.get("name") or "", r, tpl_ratio, tpl_ratio))

    ids = [a.get("id") for a in st["assets"]]
    dup = {x for x in ids if ids.count(x) > 1}
    if dup:
        issues.append("资产 id 重复：%s" % ", ".join(sorted(dup)))

    # 资产提示词：一个资产只出一条 + 够详细（铁律 21，词库见 references/07-qwen-wordbank.md）
    for a in st["assets"]:
        aid = a.get("id") or "?"
        pr = (a.get("prompt") or "").strip()
        if not pr:
            continue
        if "\n\n" in pr:
            warns.append("%s 的资产提示词里有空行分段 → 看着像写了多段或给了备选；"
                         "一个资产只出一条，合成一段（铁律 21）" % aid)
        wc = len(re.findall(r"[A-Za-z][A-Za-z'\-]*", pr))
        typ = a.get("type") or ""
        lo = 300 if typ == "prop" else 350
        if wc < lo * 0.7:
            warns.append("%s 的资产提示词只有约 %d 个英文词（%s 建议 %d+）→ 细节不足，"
                         "按 07 词库往下补槽（材质 / 痕迹 / 尺寸 / 真实感瑕疵）" % (aid, wc, typ or "资产", lo))
        if re.search(r"\b(8K|masterpiece|award-winning|highly detailed|best quality)\b", pr, re.I):
            warns.append("%s 的资产提示词里有空词（8K / masterpiece 之类）→ 删掉，换成光学与材质事实" % aid)

    vids = {v.get("id") for v in st["voices"]}
    vmap = {v.get("id"): v for v in st["voices"]}
    for a in st["assets"]:
        if a.get("voice") and a["voice"] not in vids:
            issues.append("%s 指向了不存在的参考音 %s" % (a.get("id"), a["voice"]))
        if a.get("voice") and a.get("type") != "character":
            warns.append("%s 不是人物资产，声音参考不生效" % a.get("id"))
        if a.get("type") == "character":
            v = vmap.get(a.get("voice") or "")
            has_audio = bool(v and (v.get("file") or "").strip() and
                             os.path.isfile(os.path.join(p["proj"], v["file"])))
            if not has_audio and not (a.get("voicePrompt") or "").strip():
                issues.append(
                    "%s（%s）没挂参考音频，也没有音色提示词 → 这个人物没有音色依据，"
                    "补 assets[].voicePrompt（英文一句，整部剧共用）" % (a.get("id"), a.get("name") or ""))
            elif has_audio and not (a.get("voicePrompt") or "").strip():
                warns.append("%s（%s）用了参考音频；建议同时留一条音色提示词做兜底" % (a.get("id"), a.get("name") or ""))

    gb = st["meta"].get("globalBlock") or {}
    for seg in st["segments"]:
        sid = seg.get("id")
        pairs = seg.get("promptSegs") or []
        p = seg_prompt(seg, gb)
        if not p.strip():
            issues.append("%s 缺 H3 提示词" % sid)
            continue
        if pairs and any((x.get("zh") or "").strip() for x in pairs) and len([x for x in pairs if (x.get("en") or "").strip()]) != len([x for x in pairs if (x.get("zh") or "").strip()]):
            warns.append("%s 中英段数不一致（%d vs %d），修改后要逐段对齐" % (
                sid, len([x for x in pairs if (x.get("en") or "").strip()]), len([x for x in pairs if (x.get("zh") or "").strip()])))
        ed = seg_edited(seg)
        if ed:
            warns.append("%s 有 %d 处中文改动还没同步进英文（AI 需重写对应英文段）" % (sid, len(ed)))
        if not re.search(r"no on-screen text|no subtitles|no watermark|no logo", p, re.I):
            warns.append("%s 的 detailed_description 首句没有写禁止字幕/水印/UI 的声明" % sid)
        if re.search(r"永远是说话人|is always the speaker", p):
            issues.append("%s 提示词里还有「S1 永远是说话人」这类句子，删掉（音色由 <Audio> 或固定音色句负责）" % sid)
        if re.search(r"always uses one fixed voice|始终使用一种固定的声音", p):
            warns.append("%s 提示词里还留着行内的旧版声线描述，跑一次 build 会搬进 assets[].voicePrompt" % sid)
        if TIMECODE_RE.search(p):
            warns.append("%s 提示词里出现了时间码/时长（%s），镜头长短交给模型" % (
                sid, TIMECODE_RE.search(p).group(0)))
        sec = float(seg.get("sec") or 0)
        if sec < 5 or sec > 18:
            warns.append("%s 提示词时长 %.0fs 超出 5–18 秒窗口" % (sid, sec))
        if gen_sec(sec) != seg.get("genSec"):
            issues.append("%s genSec 与 sec 不匹配（应 %d）" % (sid, gen_sec(sec)))
        pics = {int(x) for x in re.findall(r"<Picture\s*(\d+)>", p)}
        refs = seg.get("refs") or []
        if pics and pics != {i + 1 for i in range(len(refs))}:
            warns.append("%s 提示词用了 Picture %s，实际挂载 %d 张" % (sid, sorted(pics), len(refs)))
        if not refs:
            warns.append("%s 没有参考图，全参考模式会退化成纯文生视频" % sid)
        if len(refs) < len(pics):
            issues.append("%s Picture 编号多于参考图数量" % sid)
        for r in refs:
            aid = r.get("asset") if isinstance(r, dict) else r
            if aid not in ids:
                issues.append("%s 引用了不存在的资产 %s" % (sid, aid))
            else:
                a = next(x for x in st["assets"] if x.get("id") == aid)
                if not a.get("image"):
                    warns.append("%s 的参考图 %s 还没出图，生成视频会失败" % (sid, aid))
        cast = seg.get("cast") or []
        if not cast:
            warns.append("%s 没有登记出场人物，配音面板提取不到角色" % sid)
        for aid in cast:
            if aid not in ids:
                issues.append("%s 的 cast 里有不存在的资产 %s" % (sid, aid))

        binds = voice_binding(st, seg)
        for b in binds:
            blks = _subject_blocks(seg, "en", b["subject"])
            if not blks:
                issues.append("%s 找不到 <Subject%d> 段，%s 的音色句写不进去" % (
                    sid, b["subject"], b.get("asset")))
                continue
            cur = blks[0][1].get("en") or ""
            if b["kind"] == "none":
                issues.append("%s 的 %s 既没参考音频也没音色提示词，该人物没有音色依据" % (
                    sid, b.get("asset")))
            elif voice_sentence(b, "en") not in cur:
                warns.append("%s 的 %s 音色句还没写进 <Subject%d>（跑一次 build 会自动补）" % (
                    sid, b.get("asset"), b["subject"]))
        if len(seg.get("voiceTags") or []) != len([b for b in binds if b["kind"] != "none"]):
            warns.append("%s 音色句登记 %d 条、应 %d 条（build 会同步）" % (
                sid, len(seg.get("voiceTags") or []), len([b for b in binds if b["kind"] != "none"])))

    # 工作流模板与脚本映射是否对齐（换模板后最容易在这里翻车）
    try:
        tpl = load_wf(H3_WF)
        miss = [k for k in ("prompt", "core", "res", "duration", "steps", "seed", "save", "refs")
                if H3_NODE.get(k) not in tpl]
        if miss:
            issues.append("H3 工作流模板缺少节点：%s（模板 %s 与 H3_NODE 映射对不上）" % (
                ", ".join("%s=%s" % (k, H3_NODE.get(k)) for k in miss), H3_WF))
        else:
            print("工作流：%s｜%d 个节点｜步数 %s｜参考音 %d 路" % (
                H3_WF, len(tpl), st["settings"].get("steps"), AUDIO_SLOTS), flush=True)
    except Exception as e:
        issues.append("H3 工作流模板读取失败（%s）：%s" % (H3_WF, e))

    # 帧数：工作流里的 ComfyMathExpression 按 5 (mod 17) 补齐（见 h3_frames），这里只是让人看见实际帧数
    try:
        rows = []
        for sg in st["segments"]:
            sec = gen_sec(sg.get("sec"))
            fr = h3_frames(sec)
            rows.append("%s %ds/%d帧(%.2fs)" % (sg["id"], sec, fr, fr / 24.0))
        print("时长与帧数：%s" % "｜".join(rows), flush=True)
    except Exception as e:
        warns.append("帧数检查失败：%s" % e)

    # H3 落地八条 + 构图连续性四铁律（画幅同框 / 关系镜头 / 逐段独立 / Shot 不写光影与位置）
    try:
        check_h3_rules(st, issues, warns)
    except Exception as e:
        warns.append("H3 落地八条校验失败：%s" % e)

    # 运镜目录 / 运镜 LoRA / 跨段首尾镜头是否重复（拼起来会闪）
    try:
        # 本机 LoRA 列表：ComfyUI 在线就现读（判断运镜 LoRA 是 T1 还是降 T2），离线就不判这段
        avail = None
        try:
            md = comfy_models((st["settings"].get("comfy") or "http://127.0.0.1:8188").strip(), force=True)
            avail = md["lora"] if (md.get("lora") and not md.get("error")) else None
        except Exception:
            avail = None
        if avail is None:
            warns.append("ComfyUI 不在线，读不到本机 LoRA 列表 → 这次不判「运镜 LoRA 是否存在」"
                         "（离线时按 T2 处理会误报）")
        check_camera(st, issues, warns, avail)
        rows = []
        for sg in st["segments"]:
            c = camera_of(sg)
            mid = str(c.get("move") or "").strip()
            if not mid:
                continue
            mv = CAMERA_MOVES.get(mid) or {}
            lead = camera_lead(sg)
            t = camera_tier(mid, avail, lead=lead) or "-"
            if not avail and (mv.get("need") == "lora"):
                t = ("T0?" if lead else "T?") + "（离线不判 LoRA）"
            elif lead and t == "T0":
                t += "·钦点"
            rows.append("%s %s%s %s" % (sg.get("id"), mid, mv.get("zh") or "?", t))
        if rows:
            print("运镜：%s" % "｜".join(rows), flush=True)
    except Exception as e:
        warns.append("运镜与跨段衔接校验失败：%s" % e)

    print("自检：%d 个硬问题，%d 条建议" % (len(issues), len(warns)), flush=True)
    for x in issues:
        print("  [×] " + x, flush=True)
    for x in warns:
        print("  [!] " + x, flush=True)
    return 1 if issues else 0


def cmd_settings(args):
    """技能级参数记忆：查看 / 从项目覆盖 / 清空。"""
    if args.reset:
        if os.path.isfile(USER_SETTINGS_PATH):
            os.remove(USER_SETTINGS_PATH)
            print("已清空参数记忆（%s），回到技能内置默认。" % USER_SETTINGS_PATH, flush=True)
        else:
            print("本来就没有记忆文件，当前就是内置默认。", flush=True)
        return 0

    if args.from_project:
        proj = os.path.abspath(args.from_project)
        st = load_state(proj)
        doc = remember_settings(st, proj)
        if not doc:
            die("这个项目没有可记的参数：%s" % proj)
        print("已记住这些参数（来自 %s）：" % proj, flush=True)

    mem = load_user_settings()
    doc = {}
    if os.path.isfile(USER_SETTINGS_PATH):
        try:
            with open(USER_SETTINGS_PATH, "r", encoding="utf-8") as f:
                doc = json.load(f)
        except Exception:
            doc = {}
    print("记忆文件：%s" % (USER_SETTINGS_PATH if doc else "（无，用内置默认）"), flush=True)
    if doc.get("updatedAt"):
        print("更新时间：%s（来源项目：%s）" % (doc.get("updatedAt"), doc.get("from") or "—"), flush=True)
    print("", flush=True)
    print("视频参数：", flush=True)
    for k, lab in (("h3Model", "H3 主模型"), ("h3Lora", "LoRA"), ("h3LoraStrength", "LoRA 强度"),
                   ("h3Clip", "CLIP"), ("h3VideoVae", "视频 VAE"), ("h3AudioVae", "音频 VAE"),
                   ("steps", "生成步数"), ("ratio", "宽高比"), ("megapixels", "分辨率 MP"),
                   ("seed", "随机种"), ("afterGenerate", "生成后控制"), ("comfy", "ComfyUI 地址")):
        print("  %-14s %s" % (lab, mem.get(k)), flush=True)
    print("生图参数（Qwen-Image 2.1）：", flush=True)
    for k, lab in (("imgUnet", "UNet"), ("imgClip", "CLIP"), ("imgVae", "VAE"), ("imgSteps", "步数")):
        print("  %-14s %s" % (lab, mem.get(k)), flush=True)
    csz = (mem.get("charSheet") or {}).get("zh") or ""
    print("  %-14s %s" % ("人物视图模板", ("自定义 %d 字" % len(csz)) if (mem.get("charSheet") or {}).get("edited") else ("内置默认 %d 字" % len(csz))), flush=True)
    print("", flush=True)
    print("新建项目时自动沿用；工作台点「保存参数」会更新这份记忆。", flush=True)
    return 0


# ---------------------------------------------------------------- 入口
def main(argv=None):
    ap = argparse.ArgumentParser(description="短剧工作台（comfyui 直连 API 版 v2）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("init", help="新建项目（默认落在系统「下载」目录/<剧名>-<日期>/）")
    a.add_argument("--project", default="", help="不填则自动用 <系统下载>/<剧名>-<日期>")
    a.add_argument("--title", default="")
    a.add_argument("--source", default="")
    a.add_argument("--force", action="store_true")
    a.set_defaults(func=cmd_init)

    a = sub.add_parser("build", help="重建 HTML")
    a.add_argument("--project", required=True)
    a.add_argument("--no-audio-sync", "--no-voice-sync", dest="no_audio_sync", action="store_true",
                   help="只重建页面，不把音色句写进提示词（提示词与指纹保持不变，常用于纯界面调整）")
    a.set_defaults(func=cmd_build)

    a = sub.add_parser("present", help="登记这一版已呈现给用户（生成前必须）")
    a.add_argument("--project", required=True)
    a.set_defaults(func=cmd_present)

    a = sub.add_parser("serve", help="起本地桥接服务")
    a.add_argument("--project", required=True)
    a.add_argument("--port", type=int, default=8765)
    a.add_argument("--no-open", action="store_true")
    a.set_defaults(func=cmd_serve)

    a = sub.add_parser("images", help="生成资产图")
    a.add_argument("--project", required=True)
    a.add_argument("--only", default="", help="只跑指定资产 id，逗号分隔")
    a.add_argument("--force", action="store_true")
    a.add_argument("--unet", default="", help="临时指定 UNet（不改动已记住的参数）")
    a.add_argument("--clip", default="", help="临时指定 CLIP")
    a.add_argument("--vae", default="", help="临时指定 VAE")
    a.add_argument("--img-steps", dest="img_steps", type=int, default=None,
                   help="临时指定生图采样步数（整数，默认取工作台里的设置）")
    a.add_argument("--addr", default="")
    a.add_argument("--timeout", type=int, default=1800)
    a.add_argument("--dry", action="store_true")
    a.add_argument("--serial", action="store_true", help="串行：提交一张等一张（默认整批入队）")
    a.add_argument("--skip-review", dest="skip_review", action="store_true", help="跳过「必须先呈现 HTML」的闸门")
    a.add_argument("--stop-on-error", action="store_true")
    a.set_defaults(func=cmd_images)

    a = sub.add_parser("videos", help="生成视频")
    a.add_argument("--project", required=True)
    a.add_argument("--only", default="")
    a.add_argument("--force", action="store_true")
    a.add_argument("--addr", default="")
    a.add_argument("--ratio", default="")
    a.add_argument("--megapixels", type=float, default=None)
    a.add_argument("--steps", type=int, default=None)
    a.add_argument("--timeout", type=int, default=14400)
    a.add_argument("--dry", action="store_true")
    a.add_argument("--serial", action="store_true", help="串行：提交一条等一条（默认整批入队）")
    a.add_argument("--skip-review", dest="skip_review", action="store_true", help="跳过「必须先呈现 HTML」的闸门")
    a.add_argument("--stop-on-error", action="store_true")
    a.add_argument("--no-merge", dest="no_merge", action="store_true",
                   help="全部跑完也不自动合并成片（默认会自动合并成 成片.mp4）")
    a.set_defaults(func=cmd_videos)

    a = sub.add_parser("merge", help="把各段成片拼成一个整片（默认 成片.mp4）")
    a.add_argument("--project", required=True)
    a.add_argument("--only", default="")
    a.add_argument("--out", default="", help="输出文件名，默认沿用 meta.finalVideo 或 成片.mp4")
    a.add_argument("--partial", action="store_true", help="允许只合并已生成的段（默认要求全段齐）")
    a.set_defaults(func=cmd_merge)

    a = sub.add_parser("voices", help="参考音库")
    a.add_argument("--project", required=True)
    a.add_argument("--import", dest="import_path", default="", help="导入音频文件或目录")
    a.add_argument("--name", default="")
    a.add_argument("--gender", default="")
    a.add_argument("--age", default="")
    a.add_argument("--desc", default="")
    a.add_argument("--delete", default="")
    a.set_defaults(func=cmd_voices)

    a = sub.add_parser("status", help="查看进度")
    a.add_argument("--project", required=True)
    a.add_argument("--addr", default="")
    a.set_defaults(func=cmd_status)

    a = sub.add_parser("check", help="交付前自检")
    a.add_argument("--project", required=True)
    a.set_defaults(func=cmd_check)

    a = sub.add_parser("settings", help="查看 / 更新技能里记住的生图与视频参数")
    a.add_argument("--from", dest="from_project", default="", help="用某个项目的当前参数覆写记忆")
    a.add_argument("--reset", action="store_true", help="删掉记忆文件，回到技能内置默认")
    a.set_defaults(func=cmd_settings)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
