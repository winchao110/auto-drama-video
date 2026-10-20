# 05 · 项目结构与 drama.json 结构

## 一、目录

项目默认建在 **ComfyUI 的 output 目录**下，文件夹名 `剧名-YYYYMMDD`（`init` 不给 `--project` 时自动如此）：

```
<ComfyUI>/output/<剧名>-<YYYYMMDD>/
  drama.json          唯一事实源（AI 写这个，人也通过 HTML 改这个）
  workbench.html      人机桥梁（由 drama.json 生成，不要手改）
  assets/             资产图（c1.png / s1.png / p1.png）
  videos/             分段视频（P01.mp4）
  voices/             参考音（v1.wav / v2.wav）
  .run.log            HTML 里点「生成」时的日志
```

## 二、命令

```bash
PY=python   # 用当前环境的 python 即可，无第三方依赖

$PY scripts/drama.py init    --title "剧名"                          # 建项目（自动落 系统下载/剧名-日期/）
$PY scripts/drama.py init    --project "<目录>" --title "剧名"      # 指定目录
$PY scripts/drama.py build   --project "<目录>"                     # 改完 json 重建 HTML（必做）
$PY scripts/drama.py serve   --project "<目录>" --port 8765         # 起桥接服务（推荐，保存直写磁盘）
$PY scripts/drama.py present --project "<目录>"                     # 登记这一版 HTML 已呈现给人看（生成前置条件）
$PY scripts/drama.py status  --project "<目录>"                     # 看进度 + ComfyUI 是否在线
$PY scripts/drama.py images  --project "<目录>"                     # 生成全部资产图（整批入队）
$PY scripts/drama.py videos  --project "<目录>"                     # 整批入队生成全部视频
$PY scripts/drama.py voices  --project "<目录>" --import <文件/目录> # 导入参考音
$PY scripts/drama.py check   --project "<目录>"                     # 交付前自检
```

常用开关：`--only c1,s1` / `--only P01,P03` 只跑指定项、`--force` 重跑已完成的、`--dry` 只打印不生成、
`--serial` 退回串行提交（排查问题用）、`--addr http://127.0.0.1:8188` 指定 ComfyUI 地址、`--unet/--clip/--vae` 临时换生图三件套。

## 三、drama.json 全字段

```json
{
  "meta": {
    "title": "寒舟",
    "source": "《寒舟》第一章～第三章",
    "hook": "他亲手处决了自己的同志，转身走进敌人的庆功宴。",
    "synopsis": "1946 年山城，潜伏在保密局的寒舟……",
    "styleLock": "真人实拍电影质感，ARRI Alexa65，青灰与木褐低饱和…",
    "globalBlock": { "en": "【GLOBAL QUALITY & CINEMATOGRAPHY】…", "zh": "【全局画质与摄影前置】…", "edited": false },
    "stage": 2,
    "createdAt": "2026-10-17 15:58:01",
    "updatedAt": "2026-10-17 16:02:11"
  },
  "settings": {
    "imgUnet": "Qwen-Image\\qwen_image_2.1_int8_convrot.safetensors",
    "imgClip": "Qwen-Image\\qwen3vl_8b_int8_convrot.safetensors",
    "imgVae": "Qwen-Image\\qwen_image_2.1_vae_bf16.safetensors",
    "imgSteps": 25,
    "ratio": "9:16",
    "megapixels": 0.7,
    "steps": 5,
    "comfy": "http://127.0.0.1:8188",
    "h3Model": "MiniMaxH3\\minimax_h3_hybrid_fl2va_ref2va_b25-49-int8.safetensors",
    "h3Lora": "MiniMaxH3\\minimax_h3_turbo_v4_step600_ema_pruned_comfyui.safetensors",
    "h3LoraStrength": 0.75,
    "h3Clip": "Qwen-Image\\qwen3vl_8b_int8_convrot.safetensors",
    "h3VideoVae": "MiniMaxH3\\minimax_h3_video_vae_int8_convrot1.safetensors",
    "h3AudioVae": "MiniMaxH3\\minimax_h3_audio_vae_fp32.safetensors",
    "h3Veda": false,
    "h3Hd": false,
    "h3HdMegapixels": 1.5,
    "h3Wf": "star7chunk-1006api-optveda",
    "seed": 0,
    "afterGenerate": "fixed"
  },
  "voices": [
    { "id": "v1", "name": "低沉男中音 · 压抑克制", "gender": "男", "age": "30-40",
      "desc": "胸腔共鸣重，语速偏慢", "file": "voices/v1.wav" }
  ],
  "assets": [
    {
      "id": "c1", "type": "character", "name": "沈砚",
      "desc": "28 岁，保密局副处长，实为潜伏者",
      "prompt": "28 岁中国男性，浓眉压眼…",
      "ratio": "4:3", "megapixels": 1.5,
      "image": "assets/c1.png", "status": "done",
      "voice": "v1",
      "voicePrompt": "older male, low raspy chesty timbre, slow deliberate speech, controlled volume, clipped sentence endings; never shouts.",
      "voicePromptZh": "中老年男性，低音沙哑带胸腔共鸣，语速偏慢克制，句尾收得干脆；不喊。"
    }
  ],
  "segments": [
    {
      "id": "P01",
      "title": "雨夜刑房 · 他亲手签了处决令",
      "chapter": "第一章",
      "sec": 18,
      "genSec": 15,
      "logline": "老何啐了他一口，他下令就地处理。",
      "cast": ["c1", "c2", "s1"],
      "refs": [{ "asset": "c1" }, { "asset": "c2" }, { "asset": "s1" }],
      "promptSegs": [
        { "en": "【GLOBAL QUALITY & CINEMATOGRAPHY】…", "zh": "【全局画质与摄影前置】…", "edited": false },
        { "en": "<Subject1>SHEN YAN is <Picture 1>…", "zh": "<Subject1>沈砚是<Picture 1>…", "edited": false }
      ],
      "video": "videos/P01.mp4",
      "status": "done"
    }
  ]
}
```

### 字段约定

| 字段 | 取值 | 谁维护 |
|---|---|---|
| `meta.stage` | 1 提示词 / 2 资产图 / 3 视频 | AI |
| `meta.globalBlock` | 「全局画质与摄影前置」的 `en` / `zh` / `edited`；`build` 会自动把各段首重复的 `【GLOBAL…】` 段抽到这里，送 H3 时再拼回每段最前面 | 脚本抽取，人在页面改 |
| `meta.synopsis` | 视频简介（发布文案用） | AI 写，人可改 |
| `meta.finalVideo` | 整片相对路径，默认 `成片.mp4`；全部段跑完后 `videos` 自动合并写入 | 脚本 |
| `meta.finalVideoSec` / `finalVideoAt` / `finalVideoParts` | 整片时长、合并时间、参与合并的段 id | 脚本 |
| `segments[].sec` | 5–18（提示词声明的时长） | AI |
| `segments[].genSec` | `round(sec×5/6)`，脚本自动算，**不要手填** | 脚本 |
| `segments[].cast` | 本段出场资产 id，顺序 = Subject 顺序 | AI |
| `segments[].refs` | 顺序即 `<Picture N>` 编号 | AI |
| `segments[].promptSegs` | 中英段落对数组；`edited` 由 HTML 置位 | AI 写 en/zh，人改 zh |
| `segments[].voiceTags` | 本轮写进提示词的音色句（`kind` = audio / prompt，含 subject/audio_no 和 en/zh 原文），供下次同步时精确删除。旧项目的 `audioTags` 会自动迁移 | **脚本**（`sync_voice_tags`） |
| `segments[].legacy` | true 表示旧版单语提示词，`promptSegs[0].en` 直接送生成 | 迁移时自动置 |
| `assets[].type` | character / scene / prop | AI |
| `assets[].voice` | 参考音 id（仅人物有效）。空 = 不挂参考音，走 `voicePrompt` | 人在「资产」页选 / 上传 |
| `assets[].voicePrompt` | 人物固定音色描述（英文一句，40–80 词，整部剧共用）。没挂参考音时写进每个 `<Subject K>` | AI 写，人可改 |
| `assets[].voicePromptZh` | 上面的中文对照 | AI 写，人可改 |
| `voices[].file` | 项目内相对路径；空 = 该音色还没绑音频 | 人上传 |
| `settings.*` | HTML 里的全局生成参数 | 人在 HTML 改，生成时读取 |
| `settings` 的缺省来源 | **技能目录 `settings.user.json`**（跨项目参数记忆，只记生图/视频那 13 个参数项）；记忆也没有才落 `builtin_settings()` 内置默认 | `/api/save` 与 `drama.py settings --from` 写；`new_state` / `migrate` 读 |
| `settings.h3Veda` | VEDA 稀疏注意力开关（默认 `false`）。`true` 才把 `408` 留在图上；`false` 提交前整节点摘掉、`363.model` 直连 `313` | 人在「视频提示词」页勾选 |
| `settings.h3Hd` | 二采高清放大开关（默认 `false`）→ 工作流 `376.enable_hd` | 人在「视频提示词」页开/关 |
| `settings.h3HdMegapixels` | 二采目标像素（默认 `1.5`），只在该开关打开时生效 | 人在页面改 |
| `settings.h3Wf` | 当前 H3 工作流标记（`star7chunk-1006api-optveda`）。不等于当前 `H3_WF_TAG` 时，脚本把上一代默认值（旧 dmad LoRA / 4 步）对齐一次，人改过的值不动 | **脚本** |
| `image` / `video` / `status` | 由生成脚本写 | 脚本 |

### 四条纪律

1. **不要手改 `workbench.html`**：每次 `build` 都会覆盖。改内容改 `drama.json`，或让人在 HTML 里改后保存。
2. **id 用短 ASCII**：`c1` `s2` `p1` `v1`，文件名直接用它，避免中文路径在 ComfyUI 侧出问题。
3. **中文只改 `zh`，英文只由 AI 重写 `en`**：见 `01-h3-prompt-bilingual.md` 2.4。人改完中文保存后，AI 必须先同步英文再生成。
4. **不要手改 `genSec`**：`build` 会按 `sec` 重算，手改会被覆盖。
