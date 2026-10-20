# auto-drama-video · 全本地自动短剧视频生成

> **一句话进去，一部剧出来。**
> 作者：**太阳阶梯jqk8707**

把小说、剧本或随口一个点子丢进来，全流程跑在**自己的机器上**：
**H3 分段提示词 → Qwen-Image 2.1 资产图 → MiniMax H3 视频**。
每两步之间都会停下来，把产物摆到工作台页面上让你拍板——不是黑盒式"一键生成"。

生成全部走 **ComfyUI 原生 HTTP 接口**（`/prompt`、`/upload/image`、`/history`、`/view`、`/object_info`），
**只用 Python 标准库**，不封装客户端、不依赖第三方包，任何智能体/脚本都能跑。

---

## 它做什么，不做什么

| | 内容 |
|---|---|
| **做** | ① MiniMax H3 分段提示词（英文正文 + 中文对照）　② 人物/场景/道具资产提示词　③ 视频简介 |
| | 用 Qwen-Image 2.1 出资产图（人物默认 4:3 三段定设图）　生成带声音的分段成片　一键拼整片 |
| **不做** | 不写分集大纲、不写分镜表、不做"剧本页"——你要的是片子，不是 PPT |

**没有"剧本"环节**：你给的原文就是输入，直接进提示词生产。

---

## 三阶段流水线

| 阶段 | 产物 | 谁来做 | 你确认什么 |
|---|---|---|---|
| **1 提示词** | `meta` + `assets[]` + `segments[].promptSegs / refs / cast` | AI 写，你改中文 | 钩子狠不狠、英文格式对不对、中文是不是你想说的 |
| **2 资产图** | `assets[].image` | 脚本整批生成，可上传替换 | 脸像不像、场景对不对、留白够不够 |
| **3 视频** | `segments[].video` + **`成片.mp4`** | 脚本整批生成，跑完自动合并 | 口型、音色、光影、有没有多出人；最后看整片，不用一段段点 |

两份文件撑起整个工程：

- `drama.json` —— **唯一事实源**（提示词、参数、音色、每段状态全在里面）
- `workbench.html` —— **人机往返的桥**（四页：简介 / 资产 / 视频提示词 / 成品）

---

## 核心特性

**① 中英双语分工**
中文是你改的入口，英文是送模型的入口。你只改 `promptSegs[].zh`，
AI 必须把改动逐段按原格式重写进 `en`，绝不中英混排送生成。

**② 音色全剧一致（两条路二选一）**
- **参考音频**：人物卡上挂参考音 → 提示词自动写 `<Audio N>` 句（第 N 路 = 工作流 `ref_audio_{N-1}`）
- **固定音色提示词**：没挂音频 → 用该人物专属的一句英文音色描述，全剧同一句

两句都由 `sync_voice_tags()` 自动维护，改完音色重跑 `build` 即可。参考音最多 2 路，第 3 人起自动退回固定音色句，**不会有人物没声音设定**。

**③ 时长自动折算**
H3 恒定少 1/6：提示词写 `sec` 秒，API 实传 `round(sec×5/6)`（5–15s），由脚本算，不用手填。

**④ 整批入队、模型常驻**
出图/出视频默认**一次性 `POST /prompt` 整批入队**，ComfyUI 队列连续执行，模型全程停在显存；
不会在任务之间 `/free`、重启、换模型夹在批次中间（半路换模型 = 一半一个脸）。

**⑤ 模型下拉实时读 ComfyUI**
工作台每次打开、切页、点刷新都会现读 `/object_info`，**下拉里不会出现已被删掉的模型**；
已保存的模型若不存在，会自动切到可用默认项并给出提示。UNet / LoRA / CLIP / VAE 全部来自你 ComfyUI 自己的 `models` 目录。

**⑥ 参数记忆跨项目**
生图与视频参数（21 项：三件套模型、步数、比例、百万像素、种子、二采、人物视图模板…）存技能目录 `settings.user.json`，
新剧 `init` 自动沿用。**只记参数，不记剧情/资产/提示词。**

**⑦ 审核闸门**
`images` 比对提示词指纹，`videos` 比对提示词 + 资产图指纹——
**没在页面上呈现过、没登记 `present`，就拒绝生成**。防止"图还没看就往下跑"。

---

## 环境要求

- **Python 3.9+**（只用标准库，不需要 `pip install` 任何东西）
- **本地 ComfyUI** 已启动（默认 `http://127.0.0.1:8188`）
- ComfyUI 侧需要（脚本自动读它们暴露的节点与模型列表）：
  - **自定义节点**：**必须先装齐下表 4 个仓库**，缺一个工作流就提交不了（见下节）
  - **VHS**（`VHS_VideoCombine`）用于 mp4 输出；工作流里还用到 rgthree / KJNodes
  - **模型**：H3 主模型 + H3 LoRA + 32B H3 专用 CLIP + 视频 VAE + 音频 VAE；生图侧 Qwen-Image 2.1 UNet + 8B CLIP + VAE
  - 具体文件名见 `使用手册.md` 第二章，或直接看工作台参数区的下拉

> **不需要联网**。除了本地 ComfyUI，全程不访问外部服务（也不下载任何权重）。

### ComfyUI 需要安装的自定义节点

内嵌的两份工作流（H3 视频 + Qwen-Image 2.1 生图）依赖下面 4 个自定义节点仓库。
**缺节点时 ComfyUI 会直接报 `node type not found` / 提交被拒，工作台参数区也会读不到模型下拉**，装完重启 ComfyUI 再跑。

| 仓库 | 提供什么 | 用在哪 |
|---|---|---|
| [`star7code/minimax-h3-chunk-star7`](https://github.com/star7code/minimax-h3-chunk-star7) | Star7chunk 系列 H3 节点（`MiniMaxH3ChunkEnhancedLoaderStar7`、`MiniMaxH3PromptImportStar7`、`MiniMaxH3MaterialPromptStar7`、`MiniMaxH3OneClickHDStar7`、分块解码等） | 视频工作流主干 |
| [`star7code/minimax-h3-fp16-exact-star7`](https://github.com/star7code/minimax-h3-fp16-exact-star7) | H3 fp16 精确计算相关节点 | 视频工作流 |
| [`tl2012tl/TE-Speed-QwenImage21`](https://github.com/tl2012tl/TE-Speed-QwenImage21) | Qwen-Image 2.1 推理加速 | 生图工作流（25 步） |
| [`winchao110/TaiYang_MultiImage`](https://github.com/winchao110/TaiYang_MultiImage) | 多图输入 / 参考图槽位 | 生图与参考图挂载 |

```bash
cd <ComfyUI>/custom_nodes
git clone https://github.com/star7code/minimax-h3-fp16-exact-star7.git
git clone https://github.com/star7code/minimax-h3-chunk-star7.git
git clone https://github.com/tl2012tl/TE-Speed-QwenImage21.git
git clone https://github.com/winchao110/TaiYang_MultiImage.git
# 各自按仓库 README 装 requirements（如有），然后重启 ComfyUI
```

装好的自检：在任意终端跑 `python scripts/drama.py status --project "<项目>"`，
ComfyUI 在线且 `images --dry` / `videos --dry` 能过 `verify_graph()`，就说明节点齐了。

---

## 安装

本技能是一个**纯目录**技能包，不绑定任何平台：一个 `SKILL.md` + `scripts/` + `references/` + `assets/`，
没有平台私有接口、没有私有 SDK、不用注册。**任何智能体都能装，随便放哪都能跑**——`scripts/drama.py`
内部所有路径都按自身位置解析，你把它克隆到 D 盘某个角落一样能用。

```bash
git clone https://github.com/winchao110/auto-drama-video.git <你的智能体技能目录>/auto-drama-video
```

「技能目录」各家框架命名不同（多是 `~/.<框架名>/skills/`，也有放在应用安装目录里的），
本技能不挑位置。**判定装好只有两条**：放到该框架能读到 `SKILL.md` 的目录里，且能用 Python 跑到
`scripts/drama.py`。只走命令行、不用对话的话，连「技能目录」都不需要，直接 `git clone` 到任意位置即可。

**可选**：在技能目录建 `config.json` 指定默认路径（不进仓库，本机专用）

```json
{
  "projectRoot": "D:/短剧",
  "comfyOutput": "F:/ComfyUI/output"
}
```

对应环境变量：`DRAMA_PROJECT_ROOT` / `DRAMA_COMFY_OUTPUT`。

**Windows 一键启动器**：`启动工作台.bat` 里没有任何硬编码路径——技能目录按「本文件所在目录 →
`AUTO_DRAMA_HOME` → 当前目录 → 项目里的 `.drama-skill` 指针」找，Python 按「`AUTO_DRAMA_PY` →
`py -3` → `python`」找。换机器、换盘符、把 bat 单独复制进项目文件夹，都不用改一行。

---

## 快速开始

### 对话方式（推荐）

把下面几种说法直接发给你的智能体，三种都认：

- 「**全本地自动短剧视频生成，剧名《星巴克社死》，这是原文：……**」
- 「**用全本地自动短剧视频生成，把我这篇改成短剧**」+ 附件
- 「**auto-drama-video，标题《XX》，来源如下……**」

它会建项目 → 探活 ComfyUI → 一口气写出第一步的三样东西 → 打开工作台等你改。

### 命令行方式

在技能目录下执行：

```bash
# 1) 建项目（不填 --project 就落在系统「下载」目录/<剧名>-<日期>/）
python scripts/drama.py init --project "D:/短剧/剧名-20261019" --title "剧名" --source "原文.txt"

# 2) 写提示词 → 重建页面 → 起服务 → 把新地址给人看
python scripts/drama.py build  --project "D:/短剧/剧名-20261019"
python scripts/drama.py serve  --project "D:/短剧/剧名-20261019" --port 8765
python scripts/drama.py present --project "D:/短剧/剧名-20261019"   # 登记"已呈现"

# 3) 出资产图（整批入队）
python scripts/drama.py images --project "D:/短剧/剧名-20261019"

# 4) 看图画、定音色、再登记 → 出视频
python scripts/drama.py videos --project "D:/短剧/剧名-20261019"

# 5) 自检 / 看进度
python scripts/drama.py check  --project "D:/短剧/剧名-20261019"
python scripts/drama.py status --project "D:/短剧/剧名-20261019"
```

---

## 工作台四页

| 页 | 干什么 |
|---|---|
| **简介** | 剧名、一句话简介、总时长、参数总览 |
| **资产** | 人物/场景/道具卡：提示词（中英对照）、出图、上传替换、**音色区**（选参考音/试听/替换，或写固定音色提示词） |
| **视频提示词** | 每段 `promptSegs`（英文在上、中文在下），改中文后点保存，AI 按原格式重写英文 |
| **成品** | 每段成片预览、重跑单段、拼成整片 |

- `serve` 模式下点「保存」**直接写回 `drama.json`**；纯双击打开 `workbench.html` 则是下载文件模式。
- 每次 `build` 会**覆盖** `workbench.html`，别直接改它。
- 每个阶段的地址都带新的 `?v=` 时间戳——同一个地址再打开只做聚焦、不重载 DOM，容易让人对着旧页面判断。

---

## 参数区

### 生图参数（Qwen-Image 2.1）

| 参数 | 说明 |
|---|---|
| UNet / CLIP / VAE | 下拉现读 ComfyUI，默认 `qwen_image_2.1_int8_convrot` + `qwen3vl_8b_int8_convrot` + `qwen_image_2.1_vae_bf16` |
| **步数** | 整数，可自行填写，默认 **25**（对应 `qwen-image21.quality25` 工作流） |
| 百万像素 | 人物/场景/道具默认均 **2.0** |
| 比例 | 人物 **4:3**、场景 16:9、道具 1:1 |
| 人物视图模板 | 中文框即是唯一口径：左大幅脸部特写 \| 中无头全身 \| 右有头背面 的三段式定设图 |

### 视频参数（MiniMax H3 · Star7chunk-1006）

| 参数 | 说明 |
|---|---|
| 主模型 / LoRA / LoRA 强度 | 下拉现读；默认 `minimax_h3_hybrid_fl2va_ref2va_b25-49-int8` + `turbo_v4_step600` @ 0.75 |
| **CLIP** | 必须 **32B H3 专用**（5120 维），见下方"已踩过的坑" |
| **视频 VAE / 音频 VAE** | 下拉现读，默认 `minimax_h3_video_vae_int8_convrot1` + `minimax_h3_audio_vae_fp32` |
| 步数 / 种子 / 生成后控制 | 默认 5 步、`fixed` 可改 `increment / decrement / randomize` |
| 比例 / 百万像素 | 同时决定视频分辨率（例：0.9MP → 640×1120） |
| 二采高清放大 | 默认关；开了可设目标像素（默认 1.5MP） |
| 显存加速后端 | 默认 `comfy_kitchen_int8`；决定 363 节点用哪种注意力内核（existing / sla_ / sol_ / vsa_ / hybrid_，选项实时读 ComfyUI） |
| VEDA 加速 | 默认**不勾**；勾了才把 `Star7VedaSparseAttention(408)` 留在工作流里，需要 ComfyUI 里已有 VEDA 预测模型 |

同一个人在页面上调过的值就是这一轮的唯一口径，脚本原样执行、不再追问，也**不会**擅自换成"更好"的值。

---

## 项目目录结构

```
<项目根>/剧名-20261019/
├─ drama.json        唯一事实源（提示词 / 参数 / 音色 / 状态）
├─ workbench.html    工作台（每次 build 覆盖）
├─ 启动工作台.bat     双击起本地服务（保存直接写盘）
├─ assets/           资产图（文件名即资产 id：c1.png / s1.png / p1.png）
├─ 成片.mp4          整片（全部段跑完自动合并，给用户一次看完）
├─ videos/           分段（P01.mp4 …）
├─ voices/           参考音
└─ .drama-skill      技能目录指针（自动生成，启动器靠它定位技能）
```

技能目录结构：

```
auto-drama-video/
├─ SKILL.md                    主流程与 19 条铁律（给智能体看）
├─ 使用手册.md                  中文说明书（给人看）
├─ assets/workbench.template.html   工作台模板
├─ references/
│  ├─ 01-h3-prompt-bilingual.md     H3 提示词落地规范（中英分段）
│  ├─ h3-wenxi-v2-template.md       权威结构模板（运镜/光影/台词预算）
│  ├─ 02-asset-prompt-spec.md       资产清单与信息项
│  ├─ 03-qwen-image-prompt.md       Qwen-Image 2.1 提示词规范
│  ├─ qwen-t2i-rules.md / qwen-cheat-sheet.md / qwen-edit-rules.md
│  ├─ 04-comfy-api.md               接口与排错
│  ├─ 05-project-schema.md          drama.json 字段表
│  └─ workflows/
│     ├─ minimax-h3.ref2va.api.json        H3 视频工作流（Star7chunk-1006）
│     └─ qwen-image21.quality25.api.json   生图工作流（25 步）
└─ scripts/
   ├─ drama.py           主程序（init/build/serve/images/videos/check/…）
   ├─ comfy_api.py       ComfyUI HTTP 封装（标准库）
   └─ qwen_validate_prompt.py  提示词自检
```

---

## 命令行速查

| 命令 | 作用 |
|---|---|
| `init` | 新建项目（默认落在系统「下载」/剧名-日期/） |
| `build` | 重建 `workbench.html`（同时同步音色句） |
| `serve` | 起本地桥接服务，保存直接写盘；端口占用自动顺延 |
| `present` | 登记"这一版已呈现给用户"（生成前的闸门） |
| `images` | 生成资产图，整批入队 |
| `videos` | 生成视频，整批入队；**全部完成后自动合并成 `成片.mp4`** |
| `merge` | 只做合并：把各段按顺序拼成整片（`--partial` 可只合已生成的段） |
| `voices` | 参考音库：导入 / 改名 / 删除 |
| `status` | 进度一览 + 本项目工作台真实地址 |
| `check` | 交付前自检：提示词、音色、资产、工作流 |
| `settings` | 查看 / 覆写 / 清空跨项目参数记忆 |

常用开关：

```bash
--only P03            # 只跑指定段/资产（逗号分隔）
--force               # 已有产物也重跑
--dry                 # 只校验参数与工作流，不入队
--serial              # 串行提交（仅排查问题）
--skip-review         # 跳过呈现闸门（仅排查问题）
--ratio 16:9 --megapixels 1.2 --steps 6   # 临时改参数，不写记忆
--img-steps 30 --unet "…" --clip "…" --vae "…"   # 临时换生图三件套
--hd --hd-megapixels 1.8   # 临时开二采高清
--veda                     # 临时开 VEDA 稀疏注意力（需 VEDA 模型）
--attn vsa_sm75            # 临时换显存加速后端（363 的 attention_backend）
```

---

## 已踩过的坑

**H3 的 CLIP 不能随便换 8B。**
视频主模型是 20G 级的 H3，要 **5120 维**文本特征；`Qwen-Image\qwen3vl_8b` 只有 4096 维，采样阶段直接报
`mat1 and mat2 shapes cannot be multiplied (965x4096 and 5120x5376)`。
→ 视频默认停在实测可用的 **32B H3 专用 CLIP**；8B 在生图侧是正确的（下拉里随时可选）。

**模型路径大小写是两个不同选项。**
`MiniMaxH3\` 与 `MinimaxH3\` 在 ComfyUI 里是两个不同目录，写错就是 `value_not_in_list`。
这也是下拉必须现读 `/object_info` 而不是硬编码的原因。

**端口串台。**
`serve` 独占绑定端口，被占用时自动顺延并打印提示。页面数据对不上，先看 `drama.py status` 里的真实地址和 `.serve.json`，别凭记忆硬套 8765。

**本机有系统代理时，访问 `127.0.0.1` 必须绕过代理**，否则一律 502。

**H3 提示词的三类隐形返工。**
每镜都写光影 → 光位互相打架，画面一会儿暖一会儿冷；每镜重复"她在左侧、他在右侧" → 模型当成新指令重排站位；
写"仍然坐在同一张沙发上" → 每段是单独送进 ComfyUI 的，模型根本不知道上一段。这三类现在由 `check` 直接拦下（硬问题），
写提示词按 SKILL.md 铁律 17 的「构图与连续性四铁律」+ 铁律 18 的「六段式输出」走。

**改完脚本要重启 `serve`。**
否则页面保存仍走旧代码，参数记忆不会更新。

---

## 参考文档

| 文件 | 什么时候看 |
|---|---|
| `使用手册.md` | 中文说明书：怎么唤起、四页怎么用、参数怎么调、常见问题 |
| `SKILL.md` | 主流程 + 19 条铁律（智能体执行口径） |
| `references/01` + `h3-wenxi-v2-template.md` | 写 H3 提示词 |
| `references/02` + `03` | 写资产提示词 |
| `references/04` | 调接口、排错 |
| `references/05` | `drama.json` 字段含义 |

---

**把故事给它 → 改中文、定音色、看图 → 点生成 → 收片。**
它负责技术活（提示词规范、ComfyUI 调度、整批入队、音色一致性），你负责审美和拍板。

作者：**太阳阶梯jqk8707**
