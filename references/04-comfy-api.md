# 04 · ComfyUI 直连接口与工作流节点对照

本技能不封装客户端，直接打 ComfyUI 的官方 HTTP 接口。三份工作流已内嵌在
`references/workflows/`，不要再去原来的文件夹调用。

| 用途 | 文件 | 说明 |
|---|---|---|
| 资产图 | `qwen-image21.quality25.api.json` | Qwen-Image 2.1 int8，25 步（turbo 6 步版已删） |
| 视频 | `minimax-h3.ref2va.api.json` | MiniMax H3，Ref2VA 全参考模式 |

---

## 一、接口契约（5 个）

| 动作 | 请求 | 说明 |
|---|---|---|
| 探活 | `GET /system_stats` | 200 即在线；连不上说明 ComfyUI 没启动 |
| 上传文件 | `POST /upload/image`（multipart） | 字段 `image`(file) / `subfolder` / `type=input` / `overwrite=true`；返回 `{name, subfolder}`。**该接口不校验扩展名，参考图 `.wav` 参考音也走它** |
| 提交任务 | `POST /prompt`，body `{"prompt": <API格式工作流>, "client_id": "<任意uuid>"}` | 返回 `{prompt_id}`；有 `node_errors` 表示工作流校验失败 |
| 查结果 | `GET /history/{prompt_id}` | `status.status_str == "error"` 失败；`outputs` 出现即完成 |
| 下载产出 | `GET /view?filename=&subfolder=&type=output` | 图片、视频都从这里取 |

命令行等价形式（排查时直接用）：

```bash
curl -s --noproxy '*' http://127.0.0.1:8188/system_stats

curl -s --noproxy '*' -X POST http://127.0.0.1:8188/prompt \
  -H "Content-Type: application/json" \
  --data-binary @payload.json      # payload.json = {"prompt": <填好参数的工作流>}

curl -s --noproxy '*' http://127.0.0.1:8188/history/<prompt_id>

curl -s --noproxy '*' "http://127.0.0.1:8188/view?filename=xxx.mp4&subfolder=drama&type=output" -o out.mp4
```

> **踩坑**：本机若开了 HTTP_PROXY，`127.0.0.1` 也会被代理拦成 `502 Bad Gateway`。
> `scripts/comfy_api.py` 已强制 `ProxyHandler({})` 绕过代理；自己写 curl 时加 `--noproxy '*'`。

---

## 二、Qwen-Image 2.1 工作流要改的节点

| 节点 | class_type | 改哪个 input | 说明 |
|---|---|---|---|
| `517` | PrimitiveStringMultiline | `value` | 提示词正文（风格锁 + 资产本体 + 类型拼接块） |
| `514` | EmptyLatentImage | `width` / `height` | **直接写整数**，按比例+百万像素算，32 的倍数 |
| `524` | Seed (rgthree) | `seed` | 随机整数；固定它可复现同一张图 |
| `508` | SaveImage | `filename_prefix` | 用 `drama/<资产id>`，方便在 ComfyUI 里找 |
| `515` | KSampler | `steps` | 6（turbo）或 25（quality），一般不用动 |
| `523` | UNETLoader | `unet_name` | turbo 版 / 质量版模型，切换模型就换这个 |

**为什么不改 `512` ResolutionSelector**：它的 `aspect_ratio` 是枚举字符串（`16:9 (Widescreen)` 等），
不同版本枚举值可能变。直接把 `514` 的 `width`/`height` 写成数字最稳，`512` 变成孤儿节点不参与执行。

---

## 三、MiniMax H3 工作流要改的节点

模板：`references/workflows/minimax-h3.ref2va.api.json`，来源 `MiniMax-H3-Star7chunk-1006APii`（v2.8.0 起替换旧版）。
节点 id 与用途集中在 `scripts/drama.py` 顶部的 `H3_NODE`，**换模板只改那一处**。

| 节点 | class_type | 改哪个 input | 说明 |
|---|---|---|---|
| `334` | MiniMaxH3PromptImportStar7 | `prompt` | H3 提示词全文（**纯文本，不是 `value`**） |
| `275` | MiniMaxH3MaterialPromptStar7 | `width` / `height` | **直接写整数**，按宽高比 + 百万像素算 |
| `135` | PrimitiveFloat | `value` | **时长（秒）= genSec**，`134` 换算成 24fps 帧数并对齐 17k+5 |
| `126` | BasicScheduler | `steps` | **生成步数**，默认 5（`simple` 调度 + `euler` 采样） |
| `131` | RandomNoise | `noise_seed` | 随机种子 |
| `429` | TaiYangMultiImageLoader | `image_files` | JSON 数组字符串，例如 `["drama/a.png","drama/b.png"]` |
| `275` | MiniMaxH3MaterialPromptStar7 | `ref_images.ref_image_0..N` | 每个都指向 `["429", i]`，i 从 0 开始 |
| `430` | TaiYangMultiAudioLoader | `audio_files` | JSON 数组字符串，参考音文件名 |
| `275` | MiniMaxH3MaterialPromptStar7 | `ref_audio_0` / `ref_audio_1` | 最多两路，接 `["430",0]` / `["430",1]` |
| `275` | MiniMaxH3MaterialPromptStar7 | `task_type` | `自动判断 / Auto`（挂了参考素材就按 Ref2VA 走） |
| `275` | MiniMaxH3MaterialPromptStar7 | `audio_mode` | 有参考音 → `仅作音频参考 / Reference Only`；无 → `模型原生生成 / Native` |
| `150` | VHS_VideoCombine | `filename_prefix` | 用 `drama/<段号>`（`nvenc_h264-mp4`、5 Mbps） |
| `391` | MiniMaxH3ChunkEnhancedLoaderStar7 | `unet_name` | H3 主模型 |
| `311` | LoraLoaderModelOnly | `lora_name` / `strength_model` | 默认 `turbo_v4_step600`、强度 0.75；选「不挂」把整条摘掉并把下游接到 `391` |
| `376` | MiniMaxH3OneClickHDStar7 | `enable_hd` / `target_megapixels` | **二采高清放大** ← `settings.h3Hd` / `h3HdMegapixels`（默认 false / 1.5） |
| `395` | MiniMaxH3FaceRefineLatentStar7 | `enable_refine` | 一键人脸修复，技能里**默认关**（`false`，直通） |
| `339` | Star7VideoWorkflowExport | — | 提交前**整节点摘掉**：只会多写一份带工作流的视频，还抢 `pick_video` |

采样链：`391 → 311 → 313(SigmaShift 6/3) → 408(VEDA 稀疏) → 363(分块加速) → 275 / 360(实时预览) → 128 → 127(euler·simple·5 步) → 376(二采) → 395(人脸) → 377(分块解码) → 150`。

### 换模板时的自检：`verify_graph()`

`video_graph()` 建好图后 `verify_graph()` 会核对四件事，任一条不过就退出并打印具体节点，
**不带病入队**（`videos --dry` 也跑这套自检）：

1. 所有 `["节点id", 输出口]` 连线是否仍指向存在的节点（摘节点后最容易断在这里）；
2. `H3_NODE` 里点名的节点是否都在模板里；
3. 关键值是否真写进去：提示词非空、宽高是 `int`、步数/种子/保存前缀、参考图列表与槽位数一致、`audio_mode` 与是否挂参考音一致；
4. 二采节点 `376` 是否存在（缺了说明模板不是新版）。

### 参考图槽位怎么确定

`ref_image_0` 是模板里已经存在的；`ref_image_1..15` 是否可用，取决于
`TaiYangMultiImageLoader` 有几个输出口（`GET /object_info/TaiYangMultiImageLoader` 的 `output` 数组长度，本机 16 个）。

- 输出口 ≥ 参考图张数：逐张挂 `ref_image_0..N` → 每个编号对应一张图，最准。
- 输出口只有 1 个：多张图按 batch 送入，只挂 `ref_image_0`。若出现串脸/多出人，
  说明这条路走不通，需要把场景图从 refs 里去掉，只用人物图（提示词里场景改成文字描述）。

`scripts/drama.py videos` 会自动探测并按实际能力挂载，挂不满时会打印提示。

### 参考音怎么挂

`MiniMaxH3MaterialPromptStar7` 的 `optional` 里有 `ref_audio_0` / `ref_audio_1`，类型 `AUDIO`；
新工作流统一走 `430`（`TaiYangMultiAudioLoader`，8 路输出）：把 `audio_files` 写成 JSON 数组，
再让 `ref_audio_0/1` 指向 `["430",0]` / `["430",1]`。`audio_mode` 必须一起切：

| 情况 | audio_mode | 结果 |
|---|---|---|
| 角色选了参考音且音频文件存在 | `仅作音频参考 / Reference Only` | 音色/语速参考上传音频，台词仍由模型生成 |
| 角色没选，或选了但没绑音频 | `模型原生生成 / Native` | 完全由提示词里的声线描述决定 |

`drama.py` 的 `video_graph()` 会自动清理模板里残留的 `ref_audio_*` 槽位，
所以不会出现"上一段挂了音、下一段被污染"的情况。

---

## 四、参数换算

```
宽 = round(h × 比例 / 32) × 32
高 = round(sqrt(百万像素 × 1e6 / 比例) / 32) × 32
```

实测参考值：

| 比例 | 百万像素 | 实际尺寸 |
|---|---|---|
| 16:9 | 0.9 | 1248 × 704 |
| 16:9 | 1.9 | 1824 × 1024 |
| 4:3 | 1.5 | 1408 × 1056 |
| 1:1 | 1.5 | 1216 × 1216 |
| 9:16 | 0.9 | 704 × 1280 |

### H3 时长：恒定少 1/6

提示词里写 `sec` 秒，**真正传给 `132` 的是 `genSec = round(sec × 5/6)`**（下限 5、上限 15）：

| sec | 8 | 10 | 12 | 15 | 18 |
|---|---|---|---|---|---|
| genSec | 7 | 8 | 10 | 13 | 15 |

不要手改 `genSec`，`build` 每次按 `sec` 重算，`check` 会校验。

---

## 五、模型热缓存：整批一次性入队（速度关键）

H3 光是把 checkpoint + VAE + CLIP 加载进显存就要几十秒到几分钟，比采样本身还久。
"提交一条 → 等它跑完 → 再提交下一条"会在每条之间留出空档，ComfyUI 有空档就会把模型换出去，
下一条又从零冷启动——这正是"每段都要重新加载一次模型"的来源。

**正确做法：把所有段的 `POST /prompt` 一次性全打进队列，再统一收结果。**

```
上传全部参考图/参考音  →  build 全部工作流  →  连续 POST /prompt（N 条）
      →  轮询 /history 逐个收 →  下载 → 写回 drama.json
```

ComfyUI 队列会连续执行，模型常驻显存，全程没有空档。**`videos` 和 `images` 默认都是这个模式**
（打印 `[整批入队] 一次性把 N 条 H3 任务 POST 进队列` / `[整批入队] 一次性把 N 张图 POST 进队列`），
只有加 `--serial` 才退回串行。生图同理：Qwen 一次加载后连出 8 张，比每张重载省掉 7 次加载。

必须遵守：

| 禁止 | 原因 |
|---|---|
| 提交一条等一条（不带 `--serial` 时不要这么做） | 条间空档会被 ComfyUI 用来换出模型，等于每条冷启动 |
| `POST /free`（unload_models / free_memory） | 直接清空模型缓存，下一条从零冷启动 |
| `POST /interrupt` 后重排 | 会打断并清理运行态，等于重启一次 |
| 每条之间重启 ComfyUI（`run_nvidia_gpu.bat`） | 最贵的一种，模型、节点、VAE 全要重载 |
| 一批任务里混着换模型（H3 ↔ Qwen） | 每次换模型都是一次完整加载 |

实测（RTX 2080Ti / 704×1280 / 4 步）：同模型连续跑，**第一条含加载 ≈ 9–10 分钟，
后续条只算采样，时间基本只跟秒数线性相关**；一旦每条都冷启动，等于每条都按"第一条"算。

ComfyUI 启动参数也会影响模型是否被频繁换出：

- `--lowvram` / `--novram`：显存不足时反复把模型搬进搬出，一条能慢一倍以上；
- 显存够（≥12G，H3 用 9:16·0.9MP 时 2080Ti 11G 也够）就用默认或 `--highvram`；
- 不要开 `--cache-none`。

`drama.py` 全程不调用任何释放接口，**不要给它加"每条跑完清一下显存"的逻辑**。

---

## 六、失败排查顺序

1. **连不上**：ComfyUI 是否启动；端口是否 8188；是否有代理拦截（502）。
2. **提交被拒 / node_errors**：通常是模型文件名不对（`unet_name`、`vae_name`、`clip_name` 里的
   `MiniMaxH3\` `Qwen-Image\` 子目录），或用到的自定义节点没装（Star7 系列、VHS、rgthree、KJNodes）。
   **子目录大小写也要对上**：`MiniMaxH3\` 与 `MinimaxH3\` 在 ComfyUI 里是两个不同选项，写错就是 `value_not_in_list`。
   参数区的下拉直接读 ComfyUI 返回的原文，别手抄。
2b. **采样器报 `mat1 and mat2 shapes cannot be multiplied (…x4096 and 5120x…)`**：
   文本编码器维度不对。H3 的 20G 主模型（`minimax_h3_*_b25-49-int8` 等）要 **32B CLIP（5120 维）**，
   `Qwen-Image\qwen3vl_8b_int8_convrot`（4096 维）是给 Qwen-Image 出图用的，接 H3 必报这个错。
   改回 `MinimaxH3\qwen3vl_32b_minimax_h3_int8_convrot` 或 `MiniMaxH3\qwen3vl_32b_h3_ultra_uncensored_heretic_int4_convrot`。
3. **参考音不生效**：`LoadAudio` 的 `audio` 必须是 **input 根目录文件名**（不能带 `drama/` 子目录）；
   再确认 `audio_mode` 真的是 `仅作音频参考 / Reference Only`，且 `ref_audio_0` 已连上。
4. **跑一半报显存**：降低百万像素（0.9 → 0.7）、降低步数，或先只生成单段定位问题。
5. **出图黑屏 / 花屏**：Qwen 工作流的 `attention` 若是 `kitchen_int8`，长边超 1536 时容易崩，
   把百万像素降到 1.5 以下重试，或换一个 UNet / VAE（生图参数里就是干这个的）。
6. **参考图不生效**：看 `refs` 是否为空、图片是否真的存在（`assets/` 下）、
   提示词里的 `<Picture N>` 编号是否和 `refs` 顺序一致。
