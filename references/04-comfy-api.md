# 04 · ComfyUI 直连接口与工作流节点对照

本技能不封装客户端，直接打 ComfyUI 的官方 HTTP 接口。两份工作流已内嵌在
`references/workflows/`，不要再去原来的文件夹调用。

| 用途 | 文件 | 说明 |
|---|---|---|
| 资产图 | `moss-image.te-speed.api.json` | Moss Image（int8）+ TE-Speed 加速，50 步；Qwen-Image 2.1 已删 |
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

## 二、Moss Image（TE-Speed）工作流要改的节点

模板：`references/workflows/moss-image.te-speed.api.json`，来源 `TE-Speed-Mossimageapi.json`（用户导出，2026-10-24 替换掉 Qwen-Image 2.1）。

```
UNET(51) → TESpeedMoss(57) → KSampler(60) ← 正向 CLIP(54) / 负向 CLIP(55) / 空 latent(58) ← ResolutionSelector(56)
   → VAE 解码(61) → 小脸涂抹(79) → 保存(62)
提示词 → PrimitiveStringMultiline(77) → CLIPTextEncode(54)
```

| 节点 | class_type | 改哪个 input | 说明 |
|---|---|---|---|
| `77` | PrimitiveStringMultiline | `value` | 提示词正文（风格锁 + 资产本体 + 类型拼接块） |
| `56` | ResolutionSelector | `aspect_ratio` / `megapixels` | 宽高比枚举必须与节点定义逐字一致（`4:3 (Standard)` / `16:9 (Widescreen)` / `1:1 (Square)`…），像素由它算，`multiple` 16 |
| `58` | EmptyFlux2LatentImage | 连线取自 `56` | 宽高不再写死，改成连 `56` 的输出 |
| `60` | KSampler | `seed` / `steps` / `cfg` / `sampler_name` / `scheduler` | 默认 50 步、cfg 3.5、euler + simple |
| `57` | TESpeedMoss | `attention` / `step_cache` / `reuse_threshold` / `start_percent` / `end_percent` / `predictor_error_limit` / `uncond_cache` / `verbose` | 加速节点，默认 `default` / `te_predictor 2` / 0.12 / 0.2 / 0.8 / 0.06 / 关 / 关 |
| `51` | UNETLoader | `unet_name` | `Moss_image\moss_image_sft_int8_convrot.safetensors` |
| `52` | CLIPLoader | `clip_name`（`type` 固定 `moss_image`） | `Moss_image\qwen3.5_9b_int8_convrot.safetensors` |
| `53` | VAELoader | `vae_name` | `Moss_image\flux2-vae.safetensors`（Flux2 VAE） |
| `79` | TaiYangSmallFaceErase | `人脸模型` / `检测阈值` / `保留脸数` / `涂抹倍数` / `填充色` | 去掉参考图带进来的小脸。默认 `face_yolov8m.pt` / 0.12 / 1 / 1.8 / 自动背景 |
| `62` | SaveImage | `filename_prefix` | 用 `drama/<资产id>` |

**小脸涂抹按资产类型决定挂不挂**（2026-10-24 用户口径）：人物资产看 `settings.imgFaceEraseChar`（默认开），
场景 / 道具看 `settings.imgFaceEraseOther`（默认关）。判定入口是 `face_erase_for(settings, type)`，
`images` 逐资产把结果传给 `image_graph(face_erase=...)`。

**不挂的时候**：`79` 整颗摘掉，`62.images` 改连 `61`（VAE 解码）—— 这个重连由 `image_graph()` 处理，别手改模板。

**为什么 `56` 可以直接改**：Moss 模板本来就用 `ResolutionSelector` 出宽高，本技能的 `H3_RATIO_OPTS`
（`1:1 (Square)` / `4:3 (Standard)` / `16:9 (Widescreen)` …）与它逐字一致，改枚举值即可。

**依赖的自定义节点**：`TESpeedMoss`（TE-Speed 的 MOSS 版）、`TaiYangSmallFaceErase`（TaiYang 系列）、
`ResolutionSelector` / `EmptyFlux2LatentImage`（ComfyUI 本体或 flux2 插件）。缺节点会在这个工作流入队时报
`node type not found`——先装节点，别改工作流绕开。

---

## 三、MiniMax H3 工作流要改的节点

模板：`references/workflows/minimax-h3.ref2va.api.json`，来源 `MiniMax_H3API专用api.json`（用户导出，2026-10-23 替换）。
节点 id 与用途集中在 `scripts/drama.py` 顶部的 `H3_NODE`，宽高比枚举在 `H3_RATIO_OPTS`，**换模板只改这两处**。

| 节点 | class_type | 改哪个 input | 说明 |
|---|---|---|---|
| `424` | PrimitiveStringMultiline | `value` | H3 提示词全文（纯文本） |
| `252` | ResolutionSelector | `aspect_ratio` / `megapixels` / `multiple` | **宽高比枚举 + 百万像素**，宽度按 32 对齐；枚举必须与节点定义逐字一致 |
| `413` | MiniMaxH3ReferenceToVideo | `ref_images.ref_image_0..N` | 每个指向 `["421", i]`，i 从 0 开始（节点上限 9 张） |
| `413` | MiniMaxH3ReferenceToVideo | `ref_audio_0..N` | 每个指向 `["414", i]`，最多 3 路（`<Audio 1>` ↔ `ref_audio_0`） |
| `413` | MiniMaxH3ReferenceToVideo | `width` / `height` / `length` | **连线**，不要写整数：`["252",0]` / `["252",1]` / `["250",1]` |
| `259` | PrimitiveFloat | `value` | **时长（秒）= genSec**，`250` 换算成 24fps 帧数并对齐 5 (mod 17) |
| `261` | BasicScheduler | `steps` | **生成步数**，默认 5（`simple` 调度 + `euler` 采样） |
| `407` | RandomNoise | `noise_seed` | 随机种子 |
| `421` | TaiYangMultiImageLoader | `image_files` | JSON 数组字符串，例如 `["drama/a.png","drama/b.png"]` |
| `414` | TaiYangMultiAudioLoader | `audio_files` | JSON 数组字符串，参考音文件名；没参考音时整节点从图上摘掉 |
| `417` | SaveVideo | `filename_prefix` | 用 `drama/<段号>`（`format` / `codec` = auto → mp4） |
| `192` | UNETLoader | `unet_name` | H3 主模型 |
| `53` / `400` / `490` | LoraLoaderModelOnly | `lora_name` / `strength_model` | **三个 LoRA 位置**（页面三行下拉 + 三个强度，按 1→2→3 串联）：`53` = 1 号位（默认 `dmad_full_dareties_v4_step600` @ 0.8）、`400` = 2 号位、`490` = 3 号位（**模板里没有**，3 号位真挂了东西时由 `video_graph()` 按 `400` 复制一颗）。哪一格为空就整颗摘掉、链条重接；三格全空时 `331.model` 直连 `192` |
| `331` | ModelAttentionBackend | `attention` | **注意力后端**，只有两档：`comfy kitchen attention`（默认，量化 INT8）/ `pytorch attention`。← `settings.h3Attn` |
| `332` | BlockSparseAttention | —（只决定在不在图上） | **块稀疏注意力**，`selection = sol-attn`、`tau = 1.3`、`start/end = 0.2/1`、`min_tokens = 12288`、`extra_tokens = 256`、`sink_conditioning = exact_kv_and_rows`、`verbose = true`。页面**只给一个开关**（`settings.h3Sparse`），这些内部参数不暴露；不勾时整颗节点摘掉，`333.model` 直连 `331` |
| `401` | MiniMaxChunkFeedForward | `chunks` / `seq_threshold` | **分块前馈** ← `settings.h3Chunks`（默认 2）/ `settings.h3SeqThreshold`（默认 4096）。前馈层切 `chunks` 份算，序列长度超过 `seq_threshold` 才分块 |
| `403` | MiniMaxLowVRAMAttention | `head_chunks` | **低显存注意力** ← `settings.h3HeadChunks`（默认 4）。注意力按头分 `head_chunks` 份算，压低显存峰值 |
| `36` / `37` | VAELoader | `vae_name` | 视频 VAE / 音频 VAE |
| `38` | CLIPLoader | `clip_name` | 32B（5120 维）H3 专用 CLIP，`type = minimax` |

采样链（`332` 可整颗摘掉）：
`192 → 53 → 400 → 333(SigmaShift 12/3) → 332(sol-attn) → 331(注意力后端) → 401(分块FF) → 403(低显存注意力) → 329(预览覆盖) → {261(调度器) , 408(引导器)}`；
`407(噪声) + 408 + 411(euler 采样器) → 253(视频解码) / 254(音频解码) → 418(CreateVideo 24fps) → 417(SaveVideo)`。

**这一版没有的能力**（不要自己往图里加）：二采高清放大、VEDA 稀疏注意力、可选的显存加速内核、
分块解码、人脸精修、工作流导出、`VHS_VideoCombine`。对应设置项 `h3Hd / h3HdMegapixels / h3Veda`
已从页面和 `REMEMBER_KEYS` 移除，老项目残留由 `H3_RETIRED_KEYS` 在 `migrate()` 清掉。
`h3Attn` 这一项**保留但换了含义**：现在只认 `ModelAttentionBackend` 的两档
（`comfy kitchen attention` / `pytorch attention`），老项目里别的旧值会被判为不认识并回落到默认。

### 换模板时的自检：`verify_graph()`

`video_graph()` 建好图后 `verify_graph()` 会核对以下几件事，任一条不过就退出并打印具体节点，
**不带病入队**（`videos --dry` 也跑这套自检）：

1. 所有 `["节点id", 输出口]` 连线是否仍指向存在的节点（摘节点后最容易断在这里）；
2. `H3_NODE` 里点名的节点（`prompt/core/res/duration/steps/seed/save/refs/unet/clip/videoVae/audioVae`）是否都在模板里；
3. 关键值是否真写进去：提示词非空、`413.width/height` 是合法整数或指向存在的节点、
   `252.aspect_ratio` 在 `H3_RATIO_OPTS` 枚举里且 `megapixels > 0`、步数/种子/保存前缀、参考图列表与槽位数一致、
   参考音槽位数与文件列表一致且 `414.audio_files` 内容对得上；
4. 注意力/显存四件套：`331.attention` 必须在两档枚举里、`332` 的存在与否与 `h3Sparse` 一致、
   `401.chunks` / `401.seq_threshold` / `403.head_chunks` 三个整数与设置值相等。

### 参考图槽位怎么确定

`TaiYangMultiImageLoader` 有 16 个输出口（`GET /object_info/TaiYangMultiImageLoader` 的 `output` 数组长度），
`MiniMaxH3ReferenceToVideo` 的 `ref_images` 上限是 9 张（`COMFY_AUTOGROW_V3`，`prefix = ref_image_`）。

- 输出口够：逐张挂 `ref_image_0..N` → 每个编号对应一张图，最准。
- 输出口只有 1 个：多张图按 batch 送入，只挂 `ref_image_0`。若出现串脸/多出人，
  说明这条路走不通，需要把场景图从 refs 里去掉，只用人物图（提示词里场景改成文字描述）。

`scripts/drama.py videos` 会自动探测并按实际能力挂载，挂不满时会打印提示。

### 参考音怎么挂

`MiniMaxH3ReferenceToVideo` 的 `optional.ref_audios` 是 `COMFY_AUTOGROW_V3`（`prefix = ref_audio_`，上限 3 路），
统一走 `414`（`TaiYangMultiAudioLoader`，8 路输出）：把 `audio_files` 写成 JSON 数组，
再让 `ref_audio_0/1/2` 指向 `["414",0]` / `["414",1]` / `["414",2]`。

**新版没有 `audio_mode` 开关**：挂了 `ref_audio_*` 就是参考音，没挂就是模型原生生成。
`drama.py` 的 `video_graph()` 会自动清理模板里残留的 `ref_audio_*` 槽位，并在没有参考音时把 `414` 整节点摘掉，
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

提示词里写 `sec` 秒，**真正传给 `259`（再经 `250` 换成帧数）的是 `genSec = round(sec × 5/6)`**（下限 5、上限 15）：

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
   `MiniMaxH3\` `Qwen-Image\` 子目录），或用到的自定义节点没装（KJNodes / TaiYang 系列）。
   **子目录大小写也要对上**：`MiniMaxH3\` 与 `MinimaxH3\` 在 ComfyUI 里是两个不同选项，写错就是 `value_not_in_list`。
   参数区的下拉直接读 ComfyUI 返回的原文，别手抄。
2b. **采样器报 `mat1 and mat2 shapes cannot be multiplied (…x4096 and 5120x…)`**：
   文本编码器维度不对。H3 的 20G 主模型（`minimax_h3_*_b25-49-int8` 等）要 **32B CLIP（5120 维）**，
   `Qwen-Image\qwen3vl_8b_int8_convrot`（4096 维）是给 Qwen-Image 出图用的，接 H3 必报这个错。
   改回 `MinimaxH3\qwen3vl_32b_minimax_h3_int8_convrot` 或 `MiniMaxH3\qwen3vl_32b_h3_ultra_uncensored_heretic_int4_convrot`。
3. **参考音不生效**：`LoadAudio` 的 `audio` 必须是 **input 根目录文件名**（不能带 `drama/` 子目录）；
   再确认 `413` 的 `ref_audio_0` 已连到 `["414", 0]`，且 `414.audio_files` 里真的是那几个文件名。
4. **跑一半报显存**：降低百万像素（0.9 → 0.7）、降低步数，或先只生成单段定位问题。
5. **出图黑屏 / 花屏**：Qwen 工作流的 `attention` 若是 `kitchen_int8`，长边超 1536 时容易崩，
   把百万像素降到 1.5 以下重试，或换一个 UNet / VAE（生图参数里就是干这个的）。
6. **参考图不生效**：看 `refs` 是否为空、图片是否真的存在（`assets/` 下）、
   提示词里的 `<Picture N>` 编号是否和 `refs` 顺序一致。
