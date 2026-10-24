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
  .drama-skill        技能目录指针（每次保存自动写；把 启动工作台.bat 单独复制进项目时靠它找回技能）
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
    "imgUnet": "Moss_image\\moss_image_sft_int8_convrot.safetensors",
    "imgClip": "Moss_image\\qwen3.5_9b_int8_convrot.safetensors",
    "imgVae": "Moss_image\\flux2-vae.safetensors",
    "imgSteps": 25,
    "ratio": "9:16",
    "megapixels": 0.7,
    "steps": 5,
    "comfy": "http://127.0.0.1:8188",
    "h3Model": "MiniMaxH3\\minimax_h3_hybrid_fl2va_ref2va_b25-49-int8.safetensors",
    "h3Lora": "MiniMaxH3\\minimax_h3_dmad_full_dareties_v4_step600_comfy_fro.safetensors",
    "h3LoraStrength": 0.8,
    "h3Lora2": "",
    "h3Lora2Strength": 0.75,
    "h3Lora3": "",
    "h3Lora3Strength": 0.75,
    "h3Clip": "MinimaxH3\\qwen3vl_32b_minimax_h3_int8_convrot.safetensors",
    "h3VideoVae": "minimax_h3_video_vae_int8_convrot.safetensors",
    "h3AudioVae": "minimax_h3_audio_vae_fp32.safetensors",
    "h3Sparse": true,
    "h3Attn": "comfy kitchen attention",
    "h3Chunks": 2,
    "h3SeqThreshold": 4096,
    "h3HeadChunks": 4,
    "h3Wf": "native-ref2va-20261023b",
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
      "camera": { "move": "B1", "why": "他签下名字的那一秒，推近把观众按到他脸上", "lead": true },
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
| `segments[].camera` | `{"move": "<运镜 id>", "why": "<一句戏因>", "lead": false}`，也可直接写字符串 id。`move` 取 `references/camera-moves.json` 里的 id，**空字符串 = 这段不用运镜（最常见）**；`why` 空着 `check` 报问题；`lead: true` = **导演钦点（T0）**，由模型按剧情判定这场戏非这个镜头不可，与景别无关，一段最多一个、一部剧留 1–2 个。一段只能一个运镜 —— 一段最多挂一个运镜 LoRA（铁律 20） | AI 写，人在页面下拉选 + 勾钦点 |
| `segments[].cast` | 本段出场资产 id，顺序 = Subject 顺序 | AI |
| `segments[].refs` | 顺序即 `<Picture N>` 编号 | AI |
| `segments[].promptSegs` | 中英段落对数组；`edited` 由 HTML 置位 | AI 写 en/zh，人改 zh |
| `segments[].voiceTags` | 本轮写进提示词的音色句（`kind` = audio / prompt，含 subject/audio_no 和 en/zh 原文），供下次同步时精确删除。旧项目的 `audioTags` 会自动迁移 | **脚本**（`sync_voice_tags`） |
| `segments[].legacy` | true 表示旧版单语提示词，`promptSegs[0].en` 直接送生成 | 迁移时自动置 |
| `assets[].type` | character / scene / prop | AI |
| `assets[].imageSource` | 空 / `"user-upload"`。等于 `user-upload` 表示图是用户上传替换的 → 各段 `<Subject N>` 只留「严格参照图 N」，描述词会被 `sync_upload_subjects()` 清掉（`build` / 上传接口自动执行） | `/api/upload` 自动置 |
| `assets[].voice` | 参考音 id（仅人物有效）。空 = 不挂参考音，走 `voicePrompt` | 人在「资产」页选 / 上传 |
| `assets[].voicePrompt` | 人物固定音色描述（英文一句，40–80 词，整部剧共用）。没挂参考音时写进每个 `<Subject K>` | AI 写，人可改 |
| `assets[].voicePromptZh` | 上面的中文对照 | AI 写，人可改 |
| `voices[].file` | 项目内相对路径；空 = 该音色还没绑音频 | 人上传 |
| `settings.*` | HTML 里的全局生成参数 | 人在 HTML 改，生成时读取 |
| `settings` 的缺省来源 | **技能目录 `settings.user.json`**（跨项目参数记忆，只记生图/视频的参数项）；记忆也没有才落 `builtin_settings()` 内置默认 | `/api/save` 与 `drama.py settings --from` 写；`new_state` / `migrate` 读 |
| `settings.ratio` / `megapixels` | 画幅与分辨率，写进 `ResolutionSelector(252)`；实际宽高由节点按 32 对齐算出 | 人在「视频提示词」页选 / 改 |
| `settings.imgFaceEraseChar` / `imgFaceEraseOther` | 小脸抹除（`TaiYangSmallFaceErase(79)`）**按资产类型分开**：`imgFaceEraseChar` 管人物（默认 `true`），`imgFaceEraseOther` 管场景 / 道具（默认 `false`）。老项目里的单个 `imgFaceErase` 会被 `align_face_scope()` 自动拆成这两项并删掉老键 | 人在「生图参数」里勾 |
| `settings.segSecMin` / `segSecMax` | **每段时长的实传区间**（5–15 秒，默认 6 / 15）。`genSec()` 先按 5/6 折算，再夹进这个区间；区间非法（<5、>15、lo>hi）自动回落 | 人在「视频提示词」页两个下拉选 |
| `settings.h3Lora` / `h3Lora2` / `h3Lora3` | 三个 LoRA 位置，依次写进节点 `53` / `400` / `490`，按 1→2→3 串联。**1 号位默认挂主 LoRA，2、3 号位默认空（不挂）**；哪一格空就那颗节点整颗摘掉、链条重接 | 人在页面选 |
| `settings.h3LoraStrength` / `h3Lora2Strength` / `h3Lora3Strength` | 与三格一一对应的强度（1 号位默认 0.8，2、3 号位默认 0.75，-2～2） | 人在页面改 |
| `settings.h3Wf` | 当前 H3 工作流标记（`native-ref2va-20261023`）。不等于当前 `H3_WF_TAG` 时，脚本把上一代默认值（旧 turbo LoRA / 4 步）对齐一次，人改过的值不动 | **脚本** |
| `settings.h3Sparse` | 块稀疏注意力开关（默认 `true`）→ 决定 `BlockSparseAttention(332)` 在不在图上；节点内部稀疏参数不暴露 | 人在「视频提示词」页勾选 |
| `settings.h3Attn` | 注意力后端 → `ModelAttentionBackend(331).attention`。只有 `comfy kitchen attention`（默认）/ `pytorch attention` 两档，其它值在 `migrate()` 里回落到默认 | 人在页面下拉 |
| `settings.h3Chunks` | 分块前馈的 `chunks`（默认 2，1–16）→ `MiniMaxChunkFeedForward(401)` | 人在页面改 |
| `settings.h3SeqThreshold` | 分块前馈的 `seq_threshold`（默认 4096，256–65536）→ `401.seq_threshold` | 人在页面改 |
| `settings.h3HeadChunks` | 低显存注意力的 `head_chunks`（默认 4，1–16）→ `MiniMaxLowVRAMAttention(403)` | 人在页面改 |
| `settings.h3Hd` / `h3HdMegapixels` / `h3Veda` | **已废弃**（新工作流没有二采高清 / VEDA）。`H3_RETIRED_KEYS` 在 `migrate()` 里直接 `pop` 掉，页面也不再显示 | **脚本清理** |
| `image` / `video` / `status` | 由生成脚本写 | 脚本 |

### 四条纪律

1. **不要手改 `workbench.html`**：每次 `build` 都会覆盖。改内容改 `drama.json`，或让人在 HTML 里改后保存。
2. **id 用短 ASCII**：`c1` `s2` `p1` `v1`，文件名直接用它，避免中文路径在 ComfyUI 侧出问题。
3. **中文只改 `zh`，英文只由 AI 重写 `en`**：见 `01-h3-prompt-bilingual.md` 2.4。人改完中文保存后，AI 必须先同步英文再生成。
4. **不要手改 `genSec`**：`build` 会按 `sec` 重算，手改会被覆盖。
