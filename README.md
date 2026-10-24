# auto-drama-video · 全本地自动短剧视频生成

> **一句话进去，一部剧出来。**
> 作者：**太阳阶梯jqk8707**

把小说、剧本或随口一个点子丢进来，全流程跑在**自己的机器上**：
**H3 分段提示词 → Moss Image 资产图 → MiniMax H3 视频**。
每两步之间都会停下来，把产物摆到工作台页面上让你拍板——不是黑盒式"一键生成"。

生成全部走 **ComfyUI 原生 HTTP 接口**（`/prompt`、`/upload/image`、`/history`、`/view`、`/object_info`），
**只用 Python 标准库**，不封装客户端、不依赖第三方包，任何智能体/脚本都能跑。

---

## 它做什么，不做什么

| | 内容 |
|---|---|
| **做** | ① MiniMax H3 分段提示词（英文正文 + 中文对照）　② 人物/场景/道具资产提示词　③ 视频简介 |
| | 用 Moss Image（TE-Speed 加速）出资产图（人物默认 4:3 三段定设图）　生成带声音的分段成片　一键拼整片 |
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

**⑧ 运镜目录（44 条）· 按导演思维选，不硬用**
`references/camera-moves.json` 收录 44 条 H3 可落地的运镜（主角主导 / 机器主导 / 光学变化 / 视角设定 / 复合 / 双人机位），
每条带中英镜头句、戏用说明、LoRA 候选与降级写法。选用顺序是**戏眼 → 站位 → 能量走向**，不是"先挑一个炫的"：

- 一段里**最多 1 个 shot 有明确运镜**，其余定机位；大部分段落根本不用运镜。
- 每段只挂 **1 个运镜 LoRA**，接在链条最末的独立节点 `491`，**不占**页面那三个可选 LoRA 位。
- 档位四档（2026-10-24 整体往后推一档）：**T0 导演钦点**（模型按剧情判定 `camera.lead = true`，与景别无关）/
  **T1 近景**（有必挂）/ **T2 中景**（不需要 LoRA 的不挂，需要且有的挂；**全景已并入中景**）/
  **T3 本机缺文件**（不挂、不写触发词，改用降级句）。
- 有触发词的运镜（`dolly_zm`、`lockstab`、`mpov…`、360-orbit 固定 caption）由脚本自动前置到提示词最前面。
- **跨段接头硬规则**：上一段尾镜与下一段首镜不许**同景别 + 同方向**，否则拼接后闪屏、人物跳动。
  `check` 会解析每段的景别词 + 机位方向词自动抓，`[×]` 硬问题。
- 工作台每个分镜卡片里都有「运镜」下拉（按分类分组）+ 实时档位徽标 + 「为什么用这个镜头」输入。

细则见 `references/06-camera-moves.md`。

**⑨ 资产取词库（42 槽 / 370 条英文词条）**
`references/qwen-wordbank.json` + `07-qwen-wordbank.md`：从 Luori-Sunset 的 93 字段中文词库裁出来，
只留人物 / 场景 / 道具三类用得上的槽位，改写成一词一条的英文短词条，配槽位顺序与配额。

- **一个资产 = 一条提示词**，不给 A/B 版；要更细就往下补槽，不是写成两版让人挑。
- **一个槽只取一个词**：长发＋寸头、素颜＋浓妆这类互斥词同写会把脸拉糊。
- 人物 18 槽挑 14–17、场景 10 槽挑 9–10，**两者都 ≥500 词（500–700 最佳）**；道具 8 槽全用（400–600 词）。
- **默认把人写好看、写体面**：质感靠皮肤纹理 / 毛发细节 / 布料材质 / 一处高光，
  **不许**用「毛孔清晰可见 / 无修图 / 干裂 / 凌乱 / 皱巴巴 / 污渍 / 油光」换"真实"。
- 痣 / 疤 / 伤口 / 痘印 / 破衣烂衫只有剧本写明才写，且只留 1 条、记进 `assets[].note`。

取词只管"用什么词"；行文仍是 `03` 的八步框架与五条硬禁令。

**⑩ 用户上传替换的资产，提示词自动让位给图**
页面点「上传替换」后，资产被打上 `imageSource: user-upload`，所有分段里对应的 `<Subject N>` 会被自动压成一句
「相貌／衣着／体型严格参照图 N」（场景：格局/材质/陈设/光位；道具：外形/材质/颜色/磨损），**描述词全部清空**——
文字和图对不上，H3 会按文字画另一个版本。本段开场站位与音色句保留；`check` 对"上传了图还在写描述"判硬问题。

---

## 环境要求

- **Python 3.9+**（只用标准库，不需要 `pip install` 任何东西）
- **本地 ComfyUI** 已启动（默认 `http://127.0.0.1:8188`）
- ComfyUI 侧需要（脚本自动读它们暴露的节点与模型列表）：
  - **自定义节点**：**必须先装齐下表 4 个仓库**，缺一个工作流就提交不了（见下节）
  - **VHS**（`VHS_VideoCombine`）用于 mp4 输出；工作流里还用到 rgthree / KJNodes
  - **模型**：H3 主模型 + H3 LoRA（可叠到 3 条）+ 32B H3 专用 CLIP + 视频 VAE + 音频 VAE；生图侧 Moss Image UNet + qwen3.5 9B CLIP（type `moss_image`）+ flux2 VAE
  - 具体文件名见 `使用手册.md` 第二章，或直接看工作台参数区的下拉

> **不需要联网**。除了本地 ComfyUI，全程不访问外部服务（也不下载任何权重）。

### ComfyUI 需要安装的自定义节点

内嵌的两份工作流（H3 视频 + Moss Image 生图）里，H3 那条走的是 **ComfyUI 原生的 MiniMax H3 节点链**，
主干节点随 ComfyUI 本体（≥ 0.42）就有；另外还需要下面 3 个仓库。
**缺节点时 ComfyUI 会直接报 `node type not found` / 提交被拒，工作台参数区也会读不到模型下拉**，装完重启 ComfyUI 再跑。

| 仓库 | 提供什么 | 用在哪 |
|---|---|---|
| ComfyUI 本体（≥ 0.42） | `MiniMaxH3ReferenceToVideo`、`MiniMaxH3SigmaShift`、`MiniMaxChunkFeedForward`、`MiniMaxLowVRAMAttention`、`ModelAttentionBackend`、`BlockSparseAttention`、`ResolutionSelector`、`SaveVideo`、`CreateVideo`，以及 comfy kitchen 量化注意力 | 视频工作流主干 |
| [`kijai/ComfyUI-KJNodes`](https://github.com/kijai/ComfyUI-KJNodes) | `ModelPreviewOverrideKJ`（采样过程中的低分辨率预览） | 视频工作流 |
| [`winchao110/TaiYang_MultiImage`](https://github.com/winchao110/TaiYang_MultiImage) | 多图 / 多音轨输入（`TaiYangMultiImageLoader`、`TaiYangMultiAudioLoader`） | 参考图与参考音挂载 |
| TE-Speed（MOSS 版） | 生图加速 | 生图工作流里的 `TESpeedMoss` 节点，缺它入队会报 `node type not found` |

```bash
cd <ComfyUI>/custom_nodes
git clone https://github.com/kijai/ComfyUI-KJNodes.git
git clone https://github.com/winchao110/TaiYang_MultiImage.git
# TE-Speed（MOSS 版）：装 TESpeedMoss 节点（本机已装；换机器时按作者的 MOSS 版仓库装，别装 Qwen 版）
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

### 生图参数（Moss Image · TE-Speed）

**参数只有五项**（2026-10-24 用户钦定，多一个都不放）：

| 参数 | 说明 |
|---|---|
| 生图 UNet | 下拉现读 ComfyUI，默认 `Moss_image\moss_image_sft_int8_convrot` |
| 生图 CLIP | 默认 `Moss_image\qwen3.5_9b_int8_convrot`（加载器 type = `moss_image`） |
| 生图 VAE | 默认 `Moss_image\flux2-vae` |
| 步数（整数） | 默认 **50**（Moss Image 官方口径，TE-Speed 会跳掉一部分步） |
| 人物参考图 · 小脸自动抹除 | 默认**勾选**，只在人物资产（定设图）生成时生效（挂 `TaiYangSmallFaceErase(79)`）；场景 / 道具一律不挂 |

> CFG 3.5、euler + simple、TE-Speed 六项加速参数、小脸节点的人脸模型/阈值/保留脸数/涂抹倍数/填充色，
> **全部按官方默认写死在代码里，不在页面上暴露，也不进参数记忆**（`REMEMBER_KEYS` 里只留这 5 项）。

| 每张资产自己的参数 | 说明 |
|---|---|
| 百万像素 | 人物/场景/道具默认均 **2.0** |
| 比例 | 人物 **4:3**、场景 16:9、道具 1:1 |
| 人物视图模板 | 中文框即是唯一口径：左大幅脸部特写 \| 中无头全身 \| 右有头背面 的三段式定设图 |

### 视频参数（MiniMax H3 · 原生 Ref2VA）

| 参数 | 说明 |
|---|---|
| 主模型 | 下拉现读；默认 `minimax_h3_hybrid_fl2va_ref2va_b25-49-int8` |
| **LoRA ×3 + 强度 ×3** | 三个独立位置，按 1→2→3 串联。**1 号位默认挂 `dmad_full_dareties_v4_step600` @ 0.8，2、3 号位默认「（不挂 LoRA）」**。哪格留空，那颗 LoRA 节点整颗摘掉、链条自动接回去；想叠风格 LoRA 就在 2 号位选 `MysticXXX_MMH3-V1` @ 0.35 |
| **CLIP** | 必须 **32B H3 专用**（5120 维），见下方"已踩过的坑" |
| **视频 VAE / 音频 VAE** | 下拉现读，默认 `minimax_h3_video_vae_int8_convrot` + `minimax_h3_audio_vae_fp32` |
| 步数 / 种子 / 生成后控制 | 默认 5 步、`fixed` 可改 `increment / decrement / randomize` |
| **每段时长 · 最短 / 最长** | 两个小下拉，控制每段**实传**秒数区间（5–15），默认 **6–15**；`genSec` 先按 5/6 折算再夹进区间。拉长后要同步改台词与动作，`check` 会提示哪段被夹住 |
| 比例 / 百万像素 | 写进分辨率选择器，由它按 32 对齐算出实际宽高（例：9:16 · 0.9MP → 704×1280） |
| **模型稀疏注意力** | 一个勾选：勾上启用块稀疏注意力（省显存、更快），取消就把节点整颗从工作流摘掉、走完整注意力 |
| **模型注意力加速后端** | 两档：`comfy kitchen`（量化 INT8，默认）/ `pytorch`（原生，最兼容） |
| **分块前馈 · 分块数 / 序列阈值** | 默认 2 块 / 4096。显存紧就调大块数、调小阈值 |
| **低显存注意力 · 头分块数** | 默认 4。注意力按头分几份算，越大越省显存越慢 |
| **运镜 LoRA（自动）** | 不在参数区，也不在 `settings` 里。由每段的 `segments[].camera` 决定，最多 1 个，写进独立节点 `491`（链条 `… 490 → 491 → 331`）。本机缺文件就不挂、不写触发词，改用降级句 |

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
├─ SKILL.md                    主流程与 21 条铁律（给智能体看）
├─ 使用手册.md                  中文说明书（给人看）
├─ assets/workbench.template.html   工作台模板
├─ references/
│  ├─ 01-h3-prompt-bilingual.md     H3 提示词落地规范（中英分段）
│  ├─ h3-wenxi-v2-template.md       权威结构模板（运镜/光影/台词预算）
│  ├─ 06-camera-moves.md            44 条运镜目录 + 导演思维 + T0/T1/T2/T3 + 跨段防闪
│  ├─ camera-moves.json             运镜数据源（脚本与页面共用）
│  ├─ 07-qwen-wordbank.md           资产取词库用法（槽位顺序 / 配额 / 正反例）
│  ├─ qwen-wordbank.json            资产词库数据源（42 槽 / 370 条）
│  ├─ 02-asset-prompt-spec.md       资产清单与信息项
│  ├─ 03-qwen-image-prompt.md       生图提示词规范（Qwen 系，现役 Moss Image）
│  ├─ qwen-t2i-rules.md / qwen-cheat-sheet.md / qwen-edit-rules.md
│  ├─ 04-comfy-api.md               接口与排错
│  ├─ 05-project-schema.md          drama.json 字段表
│  └─ workflows/
│     ├─ minimax-h3.ref2va.api.json        H3 视频工作流（原生 Ref2VA，28 节点）
│     └─ moss-image.te-speed.api.json      生图工作流（Moss Image + TE-Speed，50 步）
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
| `SKILL.md` | 主流程 + 21 条铁律（智能体执行口径） |
| `references/01` + `h3-wenxi-v2-template.md` | 写 H3 提示词 |
| `references/02` + `03` | 写资产提示词 |
| `references/04` | 调接口、排错 |
| `references/05` | `drama.json` 字段含义 |
| `references/06` | 运镜怎么选、怎么落地（44 条目录 + 导演思维 + T0/T1/T2/T3 + 跨段防闪） |
| `references/07` | 资产提示词取词库（42 槽 / 370 条 + 配额 + 正反例，每个资产只出一条 ≥500 词的） |

---

**把故事给它 → 改中文、定音色、看图 → 点生成 → 收片。**
它负责技术活（提示词规范、ComfyUI 调度、整批入队、音色一致性），你负责审美和拍板。

作者：**太阳阶梯jqk8707**
