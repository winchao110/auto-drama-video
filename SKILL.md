---
name: auto-drama-video
description: "「全本地自动短剧视频生成」全自动短视频/短剧生成流水线（人机协同，3 阶段）：小说/剧本/点子 → 直接产出 MiniMax H3 分段提示词（英文正文+中文对照）+ Qwen-Image 2.1 资产提示词 + 视频简介 → 本地 ComfyUI 生成资产图 → 整批入队生成视频，全部跑完自动用 ffmpeg 拼成一个成片交给用户审核，全程用一份 HTML 工作台人机来回改稿。H3 提示词规范融合 minimax-h3-wenxi-prompt-v2；资产提示词按 Qwen-Image 2.1 官方改写规范（融合 qwen-image-2.1-skill，英文单段八步法）；音色在「资产」页人物图下定（选参考音/试听/替换音频，或写一条整部剧共用的音色提示词），提示词里对应 <Subject> 自动写入 <Audio N> 或固定音色句，同一个人物全剧音色一致；时长按 5/6 折算成 API 实传值。提示词按「构图与连续性四铁律」写：宽屏可两人同框、窄屏一律一人一镜，优先过脸/过肩/过腰并交代前景后景，每段独立重写开场站位与姿势（禁止“仍然/如前”式跨段指代），Shot 里不写光影、不写人物没发生的位移，check 自动卡这四条。H3 工作流为 MiniMax-H3-Star7chunk-1006（euler/simple 5 步 + 分块解码 + 可选二采高清放大）。生成全部走 ComfyUI 原生 HTTP 接口，只用 Python 标准库，任何智能体都能跑。触发词：全本地自动短剧视频生成、全本地短剧、自动短剧视频、全自动视频生成、短剧、短视频、AI 短剧、小说改编、小说转视频、H3 视频提示词、minimax h3、qwen image、资产提示词、参考音配音、音色提示词、音色一致、drama、auto-drama-video。"
metadata:
  version: "3.2.0"
  title: "全本地自动短剧视频生成"
  author: "太阳阶梯jqk8707"
  entry: "SKILL.md（本文件）"
  manual: "使用手册.md（给用户看的中文说明书）"
  requires: "Python 3.9+（仅标准库）、本地 ComfyUI（默认 http://127.0.0.1:8188）；产物落在系统「下载」目录/剧名-日期/"
---

# 全本地自动短剧视频生成

**作者：太阳阶梯jqk8707**

**一句话进去，一部剧出来。** 全流程跑在自己机器上：提示词 → 资产图 → 视频 → 自动合并成整片，每步之间停下来让你拍板。

一份 `drama.json` 是唯一事实源，一份 `workbench.html` 是人机来回改稿的桥。
**所有生成都直接调 ComfyUI 的 HTTP 接口，不封装客户端，不依赖任何外部技能或第三方库。**

> **没有"剧本"环节。** 用户给的小说/剧本就是输入，本技能**直接**产出：
> ① MiniMax H3 分段提示词（英文正文 + 中文对照）　② 资产提示词　③ 视频简介。
> 不写分集大纲、不写分镜表、不做"剧本页"。

相对路径都相对**本技能目录**。下文的 `$S` 就是技能目录，`$P` 是项目目录。
命令都在技能目录下执行；不在技能目录时把 `scripts/drama.py` 换成它的绝对路径即可（脚本内部路径都按自身位置解析）。

```bash
$PY = 当前环境的 python（Windows 例：python 或 py -3）
```

---

## 铁律（违反即返工）

1. **一次只推进一个阶段**。每阶段产出写进 HTML 后，**停下来让用户看**，等用户明确说"可以/继续/没问题"才进入下一阶段。
   用户提意见就改 `drama.json` 再 `build`，直到满意。
2. **人改了 HTML，就按人的改**。重读的是 `drama.json`（serve 模式点保存已直接写盘）。
   如果用户是文件模式（看到的是下载的 json），先问他要文件路径，再覆盖进项目。
3. **中文是人的入口，英文是机器的入口**。用户只改 `promptSegs[].zh`；AI 必须把中文改动**逐段、按原格式**重写进 `promptSegs[].en`，
   再把 `edited` 复位。**绝对不要把中文塞进 `en`**，也不要中英混排送生成。规则见 `references/01-h3-prompt-bilingual.md` 2.4。
4. **生成前必须同步英文**：只要还有 `edited == true`，先同步、`build`、再生成视频，不许拿旧英文去跑。
5. **H3 时长恒定少 1/6**：提示词写 `sec` 秒，API 实传 `genSec = round(sec×5/6)`（5–15s）。`genSec` 由脚本算，不要手填。
6. **景别不许乱写**：主角和重要配角正脸只能 特写 / 近景 / 中景（H3 中景以上人脸糊）。
7. **不伪造产出**：没有真的生成出来的图/视频，不许在 json 里写 `image` / `video` 路径。
8. **不调用技能外的模板**：H3 结构规范 = `references/01-h3-prompt-bilingual.md` + `references/h3-wenxi-v2-template.md`；
   资产规范 = `references/02-asset-prompt-spec.md`。不要去读别的技能目录。
9. **必须把 HTML 真的打开给人看，并且先呈现、后生成**。每次 `build` 之后，不能只在终端里打印路径就算交付：
   - 先 `serve`，再用 `present_files` 传 **serve / status 打印出来的那条带 `?v=` 的新地址**
     （推荐，页面里的「保存」会直接写回 `drama.json`；`?v=` 每次都要换，见铁律 14）；
   - 服务起不来就传 `workbench.html` 本地路径，让它在预览面板里打开；
   - **呈现完立刻 `drama.py present --project "$P"` 登记**。
   `images` / `videos` 带硬闸门，不一致就**直接退出**，只有 `--skip-review` 能绕过（排查问题时才用）：
   - `images` 比对 `meta.reviewedHash`（提示词指纹）：提示词动一个字，指纹就变 → 必须先 `build` → `present_files` → `present`；
   - `videos` 比对 `meta.reviewedAssetsHash`（提示词 + 资产图指纹）：**图一出完/一换，指纹就变** →
     必须把出好的图呈现给人看过、`present` 之后，才允许出视频。
   一句话：**写完提示词要呈现，出完图要再呈现，人拍板了才往下走。**

   **端口纪律（踩过坑，别再来一次）**：`serve` 现在会**独占绑定**端口，指定端口被占用时
   **不会**和旧进程共存，而是自动往后顺延，并在终端打印 `[!] 端口 8765 已被占用…已自动改用 8766`。
   - **地址一律以终端打印的那一行 `工作台已启动：http://…` 为准**，不要凭记忆硬套 `8765`；
   - 如果页面打开看到的**是上一部剧**的数据，100% 是端口串台：先 `netstat -ano | findstr :8765`
     看有没有多个 PID 同时 LISTENING，把旧项目残留的 `drama.py serve` 进程（连同它的父 bash）结束掉，
     再用本项目重新 `serve`；
   - 真实端口会写进项目目录的 `.serve.json`，`drama.py status` 会把「本项目工作台正在跑的地址」打出来，
     判断"到底连的是哪部剧"以它为准。
   **没把页面呈现在人眼前 = 这一阶段没做完**，不要进入下一阶段。每个阶段完成、每批图/视频生成完，都要重新 `build` 并再呈现一次。
   **而"呈现"必须是新开一条地址**：上一阶段那个页面还开着不算数，必须用带全新 `?v=` 的地址重新打开，见铁律 14。
10. **整批入队，模型常驻**。MiniMax H3 加载一次要几十秒到几分钟。
    - 视频**默认整批一次性 `POST /prompt`**（`drama.py videos` 已实现），ComfyUI 队列连续执行，模型全程在显存；
    - 资产图同理（`drama.py images` 也是整批入队），Qwen 只加载一次就连出全部图；
    - **不许**在任务之间调 `/free`、`/interrupt`、重启 ComfyUI，也不许把"换模型"夹在一批中间；
    - **唯一例外**：人要换工作流 / 换主模型 / 换 LoRA 时，必须先停掉当前批次（`/interrupt` 正在跑的 + `/queue {"clear": true}` 清掉排队），
      再按新配置重新整批入队。半路换模型出来的片子会一半一个脸，返工更贵。
    - 只有排查问题才用 `--serial`；
    - ComfyUI 启动别用 `--lowvram` / `--novram`。
11. **参数只认 HTML 落盘的值，重读后原样执行，不再追问**。人在工作台里调过的比例 / 百万像素 / 步数 / 主模型 / LoRA /
    随机种 / 生成后控制，就是这一轮的唯一口径：
    - 重读 = 读 `drama.json`（serve 模式点「保存」已直接写盘），**不要拿旧印象去覆盖人的设置**；
    - **不许**因为"觉得这个值不合理 / 会掉分辨率 / 会变慢"就停下来问一遍，也不许擅自换成自己认为更好的值；
    - 顶多在最终回复里**用一句话备注一句副作用**（例：`百万像素同时决定视频分辨率，0.7MP 出 640x1120`），
      但**命令照原参数跑**，跑完再一起说；
    - 只有会造成**不可逆损失**的情况（删文件、覆盖已拍板产物）才需要先确认。
    - 这些参数项**保存时会写进技能目录 `settings.user.json`，下一部剧 init 直接沿用**（只记参数，不记剧情 /
      资产 / 提示词）。新项目建好先跑 `drama.py settings` 核一眼记忆，别让上一部剧的机器地址、模型路径带病开工。
    - 同理，**工作台「生图参数」里那个「人物视图模板」中文框就是唯一口径**（存 `settings.charSheet.zh`，
      改过会带 `edited` 标记，此时送进模型的就是中文那版），不许用 `drama.py` 内置默认去覆盖它；
      确实觉得有冲突，只在回复里备注一句。要补英文版就按原格式重写、写回 `charSheet.en` 并把 `edited` 置 false。
12. **每个人物必须有一条音色依据，两条路二选一，全剧同一个人物永远用同一套**：
    - **路 A：参考音频**（`assets[].voice` 指向 `voices[]`，且音频文件真实存在）→ 提示词写 `<Audio N>` 参考句；
      第 N 路参考音 = 工作流的 `ref_audio_{N-1}` = 提示词里的 **`<Audio N>`**（1 起数，和 `<Picture 1>` 同规矩），
      写在该人物 **`<Subject K>` 段的末尾**，K = 该人物在 `cast` 里的下标 + 1；
    - **路 B：固定音色提示词**（没挂参考音频）→ 用 `assets[].voicePrompt`（英文）+ `voicePromptZh`（中文对照）写一句
      "整部剧只用这一种音色"的句子。**音色描述存在资产上，不写在每一段里**，所以全剧天然一致；
    - 两句都由 `build` / `videos` 里的 `sync_voice_tags()` 自动维护（先按 `seg.voiceTags` 精确删旧句、再按最新绑定插新句），
      **不要手写、不要重复写**；人换了音色 / 换了参考音就必须重跑 `build`
      （提示词变了 → 指纹变了 → 必须重新呈现 + `present` 才准出视频）；
    - 参考音最多 2 路（节点只有 `ref_audio_0/1`）；一段里有第 3 个人物起自动退回"固定音色提示词"，不会有人物没声音设定；
    - **提示词里不许出现 `S1 永远是说话人` / `S1 is always the speaker` 这类句子**，也不要写"某人负责说话"的旁白式说明，
      说话人由 `says:` + `<d>` 台词标签表达；
    - `check` 会核对：每个人物有没有音色依据、`<Subject K>` 段是否存在、`<Audio>` / 固定音色句有没有真的落进提示词、
      以及有没有残留旧版"永远是说话人"的句子。
13. **换 H3 工作流 = 换模板 + 同步 `H3_NODE` 映射，不带病入队**。模板换代（v2.8.0 → `Star7chunk-1006`）时：
    - 只改 `references/workflows/minimax-h3.ref2va.api.json` 和 `scripts/drama.py` 顶部的 `H3_NODE` / `DEFAULT_H3_*`，
      **不要**在 `video_graph()` 里写死节点 id；
    - 提交前 `verify_graph()` 会核对节点映射、断链、关键值（宽高/步数/种子/参考图槽位/audio_mode/二采节点），
      有一条不过就**退出并指出是哪个节点**，`--dry` 也会跑这套自检；
    - 老项目（`settings.h3Wf` ≠ `H3_WF_TAG`）只对齐一次**上一代默认值**（旧 `dmad` LoRA / 4 步），
      用户自己改过的模型 / LoRA / 步数一律不动（铁律 11）。
14. **每次交人审核，必须给他一条全新的地址；上一阶段那个页面还开着，不算"已经呈现"**。
    浏览器和预览面板都按 URL 判重：同一个地址第二次打开只做聚焦、**不会重新加载 DOM**，
    于是人对着上一阶段的旧页面做判断。典型症状就是：图明明已经出好落盘了，页面还写着「未生成」，
    人以为是技能坏了或 AI 没干活，实际只是他看的还是二十分钟前那一屏。
    - 呈现地址**一律取 `drama.py serve` / `drama.py status` 打印的、带 `?v=` 的那一条**
      （由 `fresh_url()` 生成，形如 `http://127.0.0.1:8765/?v=1018172600`）；
    - **每次 present 都要重新取一次**，`?v=` 的值必须与上一次不同。不许手写 `http://127.0.0.1:8765/`，
      更不许复用前面任何一条消息里已经用过的链接——哪怕它现在还能打开、还能看到内容；
    - 端口不靠记忆：以 `serve` 打印行 / 项目目录 `.serve.json` / `drama.py status` 为准；
    - **呈现前先自证这一屏是新的**：`curl -s "<新地址>" | grep "<本步刚产出的标志>"`，
      标志取本步新增的东西（刚出的图名、刚出的视频名、刚改的标题）。
      取不到就是 `build` 没真正落盘、或 serve 连的是别的项目目录，先修好再呈现，不许"先打开再说"；
    - 一批结果一起给：图/视频传本地路径，工作台传**新地址**，排在第一位让面板先开它；
      呈现完立刻 `drama.py present --project "$P"` 登记；
    - 人反馈「没变化 / 还是旧的 / 显示未生成」时，**第一步查链接是不是复用了**（以及是不是旧标签页），
      不要先去怀疑 `drama.json`、图片文件或生成流程。

15. **生成完先呈现，不许自作主张改**（2026-10-19 用户钦定，违反就是返工）。
    - **图出完 / 视频出完的第一件事是呈现**：`build` → 取新 `?v=` 地址 → `present_files`（工作台排第一 + 全部产物本地路径）
      → `present` 登记，然后**停下来等人说"可以"**。
    - **禁止**在用户没点头的情况下：改资产提示词、改 `charSheet`、换种子/参数重跑、挑一张"更好的"顶掉已出的图、
      自动重剪视频、为了让画面好看擅自加戏。**发现不满意只报告 + 给方案**，等一句"改"再动手。
    - 一轮里最多只做**用户明确要求的那一件事**；"顺带优化一下"属于越权。
    - 用户说"改"之后，改完仍然要重新 `build` + 新地址呈现 + `present`，再等下一次点头。

16. **提示词阶段先校验、后呈现**。`check` 报「N 个硬问题」时 N 必须为 0 才允许 `build` / `serve` / `present_files`；
    `[×]` 是硬问题，必须改提示词或数据，**不许用"页面能开"当通过**；`[!]` 是建议，能改就改，改不掉的逐条说明理由。
    校验不通过就在终端里把问题列清楚继续修，别把半成品页面推给人看。
17. **构图与连续性四铁律**（2026-10-19 用户钦定，优先级高于 `h3-wenxi-v2-template.md` 的冲突写法，
    细则与英文句式见 `references/01-h3-prompt-bilingual.md` 的「四之三」）：
    - **画幅决定同框**：宽屏（16:9 / 21:9 / 4:3）可以两人同框；**窄屏（9:16 / 3:4）一律禁止两人同框**，
      一人一镜、用正反打接，不许"并肩硬塞"。
    - **优先过脸 / 过肩 / 过腰**，每个 Shot 都要交代前景是什么、后景是什么；说话或做动作的人在焦点上，
      对手只作前景轮廓（写 `the focus sits on the far figure` 这类大白话，禁用 `rack focus / shallow depth of field`）。
    - **每段独立**：一段一个 ComfyUI 任务，模型没有上文。禁止 `still / remains / as before / 仍然 / 依旧 / 如前`
      这类跨段指代；**每段场景 `<Subject N>` 段必须重写"本段开场站位与姿势"**——谁在哪、坐/站/靠/躺、
      手里有什么、朝向谁。上一段结尾的姿势不能靠"仍"字继承，只能重写。
    - **Shot 只写这一镜的变化**：全局光影只在 `detailed_description:` 首句声明一次，**Shot 里不写任何光影**
      （灯/光/色温/亮边/阴影）；人物没移动就**不写画面位置**，移动时必须写 `from…to…`，起点与本段开场状态一致。
    - **画幅词**必须与 `settings.ratio` 一致（16:9 就写 `horizontal 16:9 framing`），改了比例必须同步；
      不要写 `focus held on the face in every shot`，那会让"焦点给前景还是后景"失效。

    `check` 会逐条卡：窄屏双人同框、Shot 光影词、跨段指代、场景条缺开场姿势、**画幅与 ratio 不符**、
    **缺六段式块**、**Shot 里写死时长** → **硬问题**；
    人物没动却写画面位置、全片没有关系镜头、retention_analysis 漏主体 → **建议**。

18. **H3 提示词按六段式输出**（2026-10-19 用户钦定，格式对齐官方长提示词）：
    `subject_definitions:` → `summary:` → `retention_analysis:` → `detailed_description:` →
    `overall_soundscape:` → `non_diegetic_music:`，块名英文小写加冒号、顶格另起一行，顺序不许变。
    - `subject_definitions:` 每个 `<Subject N>` 一条，**有场景图时场景排第一条**，末尾带
      `Opening state: …`（本段开场站位与姿势）；`<Audio N>` 紧跟它对应的人物条。
    - `retention_analysis:` 逐个主体写 `fully_preserved - …`，音频写 `reference - …`。
    - `detailed_description:` 首句写全局风格 + 画幅 + 画质 + 禁止项（字幕/水印/UI/配乐），随后每镜一个 `[Shot N]`。
    - **`[Shot N]` 里不许写时长**（不写 `At 00:03.000`、不写 `[0-3秒]`），镜头长短交给模型。
    - 不再有 `【禁止项】` / `【强制声明】` 尾部块，禁止项并进 `detailed_description:` 首句。

19. **视频跑完必须合成一条整片再交人审核**（2026-10-19 用户钦定）：
    全部段 `done` 后，`videos` 会自动调 `merge` 拼成 `项目根/成片.mp4`；**紧接着 `present_files` 把整片呈现给用户**，
    同时给出工作台的 `?v=` 新地址。不许只报"各段都好了"让用户自己一段段点开看。
    - 合并完先自己抽几帧对一遍（`ffmpeg -ss` 抽首/中/尾），确认没有错帧、错位、掉音；
    - 用户提意见要重跑某几段时，跑完再 `merge` 一次（覆盖同名文件），重新呈现整片；
    - 合并失败（多半是找不到 ffmpeg）要明说，并给出补救：装 ffmpeg 或把路径写进 `settings.ffmpeg`／`DRAMA_FFMPEG`。

---

## 第 0 步：建项目 + 探活

```bash
$PY scripts/drama.py init --title "剧名"        # 不用给 --project：自动建到 系统下载/剧名-日期/
$PY scripts/drama.py status --project "$P"
```

**产物默认落在系统「下载」目录里**（Windows 一般是 `C:\Users\<用户名>\Downloads`）：`drama.py` 会自己定位
（① 环境变量 `DRAMA_PROJECT_ROOT`；② 技能目录 `config.json` 的 `projectRoot`；③ 注册表里用户真实的下载目录；④ `~/Downloads`）。
新建出来的文件夹名就是 **`剧名-YYYYMMDD`**，`drama.json`、`workbench.html`、`assets/`、`videos/`、`voices/` 全在里面，
用户打开「下载」就能直接拿到成片，不用钻进 ComfyUI 的目录里翻。
要放别处就显式给 `--project`，或在 `config.json` 里把 `projectRoot` 指到别的盘。

`status` 会打印 ComfyUI 是否在线。**不在线就先让用户启动本地 ComfyUI**（桌面版 / `run_nvidia_gpu.bat`）。
第 1 阶段不需要 ComfyUI，可以先出提示词。

**ComfyUI 报节点缺失（`node type not found` / `value_not_in_list` / 参数区下拉读不到模型）时，先让用户把这 4 个自定义节点装到 `ComfyUI/custom_nodes/` 再重启 ComfyUI，不要改工作流绕开：**

| 仓库 | 提供 |
|---|---|
| <https://github.com/star7code/minimax-h3-chunk-star7> | Star7chunk 系列 H3 节点（`MiniMaxH3ChunkEnhancedLoaderStar7` / `MiniMaxH3PromptImportStar7` / `MiniMaxH3MaterialPromptStar7` / `MiniMaxH3OneClickHDStar7` / 分块解码） |
| <https://github.com/star7code/minimax-h3-fp16-exact-star7> | H3 fp16 精确计算节点 |
| <https://github.com/tl2012tl/TE-Speed-QwenImage21> | Qwen-Image 2.1 生图加速 |
| <https://github.com/winchao110/TaiYang_MultiImage> | 多图输入 / 参考图槽位 |

```bash
cd <ComfyUI>/custom_nodes
git clone https://github.com/star7code/minimax-h3-fp16-exact-star7.git
git clone https://github.com/star7code/minimax-h3-chunk-star7.git
git clone https://github.com/tl2012tl/TE-Speed-QwenImage21.git
git clone https://github.com/winchao110/TaiYang_MultiImage.git
```

装完用 `images --dry` / `videos --dry` 验证 `verify_graph()` 能过，再入队。

---

## 第 1 阶段：提示词（一次出全三样）

先读两份规范，再动笔：
- `references/01-h3-prompt-bilingual.md`（双语段落对、断段规则、时长口径、配音规则、JSON 落地）
- `references/h3-wenxi-v2-template.md`（**权威结构模板**：Subject/S 编号、运镜公式、光影套件、台词预算、固定尾部、交付检查）
- `references/02-asset-prompt-spec.md`（该建哪些资产、人物 10 项信息、场景/道具信息项、分辨率）
- `references/03-qwen-image-prompt.md`（**资产提示词怎么写**：Qwen-Image 2.1 八步框架、五条硬禁令、三类资产落地）

要做的事：

1. **通读素材，切段**：按 5–18 秒切成"一个主场景 + 一次关系变化 + 一条主动作链"的独立单元，
   先标硬边界，再把"问句+回答+眼神"这种小回合合并进同一段。不要凑镜头。
2. **写视频简介**：`meta.hook`（0–3 秒钩子）+ `meta.synopsis`（观众视角 3–6 句）+ `meta.styleLock`（统一美术风格锁）。
3. **写资产提示词**：`assets[]`，两个以上段落出现的人物/道具必须建；只写本体，不写动作/镜头/光位。
4. **写 H3 分段提示词**：`segments[]`，每段
   - `id`（P01…）、`title`、`chapter`、`sec`（5–18）、`logline`
   - `cast`：本段出场资产 id，**按 Subject 顺序**（人物在前、场景在后）
   - `refs`：本段参考图，顺序 = `<Picture N>`，段内从 P1 连续重排
   - `promptSegs`：**中英段落对数组**，英文段是唯一送生成的文本，中文段给人改
   - **构图与连续性（四铁律，见铁律 17）**：按 `settings.ratio` 决定能不能两人同框（窄屏一律一人一镜）；
     优先过脸/过肩/过腰；场景段第一句写本段开场站位与姿势；Shot 不写光影、不写人物没发生的位移
5. **给每个人物写音色提示词**（整部剧共用一条，铁律 12）：
   - `assets[].voicePrompt`（英文一句，40–80 词）+ `assets[].voicePromptZh`（中文对照）；
   - 内容写：年龄段与性别呈现、音域、音色质感、语速、音量、句尾习惯、情绪变化，最后带一句"禁止××"；
   - `voice` 先留空（人会在「资产」页选参考音 / 上传音频；一旦挂了参考音，这句话自动退居兜底）；
   - 同一个角色的这条描述**只写一次**，所有分镜共用；**不要**在 `promptSegs` 里重复写声线，也**不要**写
     `S1 永远是说话人` 这类句子。

写完：

```bash
$PY scripts/drama.py check --project "$P"    # 自检：缺提示词 / 中英段数不一致 / Picture 编号 / 尾部缺失 / H3 落地八条
$PY scripts/drama.py build --project "$P"
$PY scripts/drama.py serve --project "$P" --port 8765
```

`check` 除常规项外，还会按 **H3 落地规则 + 构图连续性四铁律**逐镜扫一遍（细则见 `references/01-h3-prompt-bilingual.md`
第「四之二」「四之三」节）：
道具凭空消失、风格演成正剧、抽象心理描写、一镜多事件/姿势瞬移、不可识别的电影术语、
多人同框无站位、窄屏双人同框；以及**窄屏禁同框、Shot 光影、跨段指代、场景段开场站位**。
**报出来的每一条都要改提示词，不要放着不管**——这些正是"文字通顺、模型做不到"的那一层。
**Shot 里不许再写"身后是沙发靠背和墙面"这类背景句**：场景已在场景段声明一次，重复只会稀释动作（2026-10-19 用户要求取消）。

**呈现前必须先过 `check`（铁律 16）**：`自检：N 个硬问题` 里 N 必须为 0，`[×]` 一条都不许带进页面；
`[!]` 建议能改就改，改不掉的在回复里逐条说明理由。校验没过就呈现等于让用户替你排查。

`build` 默认会顺带把音色参考句同步进提示词（铁律 12）。**只改界面、不想动提示词**时加 `--no-audio-sync`：
提示词内容与审核指纹保持不变，页面照样换新模板。

然后**把页面打开给人看**（铁律 9 + 铁律 14）：`present_files` 传 **serve / status 打印的那条带 `?v=` 的新地址**
（默认 `--port 8765`，被占用会自动顺延，**以打印值为准**，别硬拼 8765；`?v=` 每次都要新，不许复用上一步的链接）；
起不来就传 `workbench.html`。**页面打开后再登记一次**，否则第 2/3 阶段会被闸门拦住：

```bash
$PY scripts/drama.py present --project "$P"
```

页面四页：**简介**（钩子/视频简介/风格锁 + 分段总览）、**资产**（提示词 + 出图 + 人物音色）、
**视频提示词**（六段式中英对照 + 音色总览；旧项目顶部仍有全局画质块）、**成品**（播放器）。

**音色在「资产」页定**（铁律 12），人物卡图片下方就是音色区：
- **参考音频**：下拉选参考音库里的音色 → 「▶ 试听」；不满意就「替换音频」或「上传参考音」直接传自己的；
- **固定音色**：不选参考音，直接改 `音色提示词 · 英文 / 中文`（整部剧共用一条）；
- 两者二选一，页面会打标签：`参考音频` / `系统音色` / `缺音色`（红标，必须补）。

在「视频提示词」页用户可以：
- 页首「音色总览」只读展示每个人物当前走哪条路（要改请回资产页，避免同一件事两个入口）；
- 顶部「全局画质与摄影前置」一块，改一次对所有分镜生效；
- 默认是**整段视图**：一个分镜（P01、P02…）就是一整段英文 + 一整段中文，不按段落拆卡片；
  改中文时**段与段之间空一行**（页面按空行切回 N 段，切不出 N 段会拒绝写入并提示），
  需要逐段对照时点顶部的「切成逐段编辑」；改过会打上"待同步"标记，保存后写回 `drama.json`。

**等用户确认**。用户说"改好了"之后：
```bash
# 1) 读 drama.json，找出 edited == true 的段，逐段把中文意思重写进对应英文段（保持原格式、段落数、标签）
# 2) 复位 edited，然后
$PY scripts/drama.py build --project "$P" && $PY scripts/drama.py check --project "$P"
```
再 `present_files` 呈现一次，让用户核对英文。

---

## 第 2 阶段：生成资产图

> 闸门：`images` 会先查 `meta.reviewedHash`。没呈现过、或提示词在上次呈现后改过 → 直接退出（`--skip-review` 才能绕过）。

```bash
$PY scripts/drama.py images --project "$P"                  # 用 HTML 里选的 UNet / CLIP / VAE
$PY scripts/drama.py images --project "$P" --clip "Qwen-Image\qwen3vl_8b_int8_convrot.safetensors" --only c1   # 临时换 CLIP
```

- **整批入队**：全部图一次性 `POST /prompt`，Qwen 只加载一次就连出全部图（铁律 10）；每出一张就写回 `drama.json` 并重建 HTML。
- 人物图自动拼「人物视图模板」（默认 **4:3 三段**：左=大幅脸部特写 / 中=无头全身像，颈部平整截断 / 右=有头背面照，
  肩膀与左侧视图齐平；模板存在 `settings.charSheet`，工作台资产页可改，改完只影响本项目）；
  场景自动拼「全景宽构图」；道具自动拼「纯白背景单件」。
  人物画布必须是 4:3，16:9 会把三段压变形（`check` 会按模板里写的比例核对并报出来）。
- 资产默认百万像素：人物 / 场景 / 道具统一 **2.0 MP**；默认比例：人物 **4:3**、场景 **16:9**、道具 **1:1**。
- 用户对某张不满意：在 HTML 里改提示词再点「生成这张」，或直接「上传替换」自己的图。
- **AI 不许自己动**：看到不满意的图，只能报告问题 + 给修改方案，等人点头再重出（铁律 15）。
- 失败了先看 `references/04-comfy-api.md` 的排查顺序，不要盲目重跑。

生成完让用户逐张确认，**等确认**再进第 3 阶段。每张图落地后脚本都会自动 `build`，但**必须再 `present_files` 呈现一次并 `present` 登记**
（**用一条新的 `?v=` 地址**，铁律 14：不得让人继续看第 1 阶段那一屏），
否则第 3 阶段的闸门会把你挡住（这是设计，不是 bug）。

---

## 第 3 阶段：生成视频

> 闸门同上，而且更严：`videos` 比的是「提示词 + 资产图」指纹，图一生成就变 → 必须重新 `build`、再 `present_files` 把图给人看、
> `present` 登记（**又是新的一条 `?v=` 地址**，铁律 14），等用户明确说"图可以了，出视频"才跑。

```bash
$PY scripts/drama.py videos --project "$P"                          # 整批入队，全部段
$PY scripts/drama.py videos --project "$P" --only P01,P03           # 只跑指定段
$PY scripts/drama.py videos --project "$P" --steps 6 --megapixels 1.2   # 临时调参数
$PY scripts/drama.py videos --project "$P" --hd --hd-megapixels 1.5     # 临时打开二采高清
$PY scripts/drama.py merge  --project "$P"                              # 手动重拼成片（默认 成片.mp4）
```

### 全部跑完 → 自动合并成片并交人审核

`videos` 跑最后一条时，只要**每一段都 `status == done` 且有视频文件**，脚本会自动调用 `merge`，
把各段按 `segments` 顺序拼成 `项目根/成片.mp4`（先 `-c copy` 无损；时长对不上或编码不一致时自动回退
libx264 重编码 + 统一分辨率/帧率/音轨），并把结果写进 `meta.finalVideo / finalVideoAt / finalVideoSec / finalVideoParts`，
工作台「成品」页顶部会多出一个整片播放器 +「下载整片」。

- 想单独跑某几段对比 → `videos --only P02` 不会触发合并（没全齐）；
- 全齐但不想合并 → `videos --no-merge`；
- 只合已生成的段（预览用）→ `merge --partial`；
- 换了参数重跑某几段之后，重新 `merge` 一次即可，文件名不变、旧成片被覆盖；
- 合并失败**不算生成失败**：会打印原因（多半是找不到 ffmpeg），各段原片仍然完好。

**合并完必须做的一步**：直接 `present_files` 呈现 `成片.mp4`（连同工作台的 `?v=` 新地址），
让用户一次看完再提意见——不要只报"四段都好了"让用户自己一段段点开。

**ffmpeg 从哪来**：先看环境变量 `DRAMA_FFMPEG`，再看 `settings.ffmpeg`，然后 PATH，
最后自动找剪映自带的那份（`%LOCALAPPDATA%\JianyingPro\Apps\*\ffmpeg.exe`，本机已验证可用）。
都没有就装一个 ffmpeg，或把路径写进上面任一处；`ffprobe` 不需要，时长/分辨率由 `ffmpeg -i` 解析。

视频参数全部在 HTML 的「视频参数」卡里改，`drama.json` 的 `settings` 里对应：

| 界面 | settings 字段 | 说明 |
|---|---|---|
| H3 主模型 | `h3Model` | 选项来自已连接 ComfyUI 的 `models/diffusion_models`（读 `MiniMaxH3ChunkEnhancedLoaderStar7.unet_name`） |
| LoRA | `h3Lora` | 选项来自 `models/loras`；选「不挂 LoRA」会把 `LoraLoaderModelOnly` 节点整条摘掉并把下游接到 unet |
| LoRA 强度 | `h3LoraStrength` | 默认 0.75 |
| CLIP | `h3Clip` | 选项来自 `models/text_encoders`（读 `CLIPLoader.clip_name`），写进节点 130；2026-10-19 起默认 `Qwen-Image\qwen3vl_8b_int8_convrot`，类型仍为 `minimax` |
| 视频 VAE | `h3VideoVae` | 选项来自 `models/vae`（读 `VAELoader.vae_name`），写进节点 121；条件载入 275 与分块解码 377 都是连线引用它 |
| 音频 VAE | `h3AudioVae` | 同上，写进节点 122 |
| 随机种 | `seed` | 0 = 每次随机；每段按「生成后控制」往后推 |
| 生成后控制 | `afterGenerate` | `fixed` / `increment` / `decrement` / `randomize` |
| 宽高比 / 百万像素 / 步数 | `ratio` / `megapixels` / `steps` | 一采分辨率；步数默认 5（turbo_v4 蒸馏 LoRA 按 5 步走） |
| 二采高清放大 | `h3Hd` | **默认关**。开 → `MiniMaxH3OneClickHDStar7.enable_hd = true`，一采后再放大精修一轮 |
| 二采目标像素（MP） | `h3HdMegapixels` | **默认 1.5**；只在开关打开时生效，关闭时输入框置灰 |

### 参数记忆：这些项会跟着人走到下一部剧

生图参数（UNet / CLIP / VAE / 步数 / 比例 / 百万像素 / 人物视图模板）+ 视频参数（主模型 / LoRA / 强度 / CLIP /
视频 VAE / 音频 VAE / 步数 / 种子 / 生成后控制 / 二采 / ComfyUI 地址）**保存在技能目录的 `settings.user.json`**，不随项目丢失：

- **写**：工作台点任何一次「保存参数 / 保存」都会顺带写一遍（`/api/save` → `remember_settings()`），
  以最后一次保存为准；只写 `REMEMBER_KEYS` 里那 19 个参数项；
- **读**：`new_state()` 和 `migrate()` 都优先用记忆值——新项目 `init` 直接继承；老项目缺字段也吃记忆值，
  项目里已经写了的字段不会被覆盖（项目仍然是这一轮的最终口径，铁律 11 不变）；
- **不记**：剧情、钩子、简介、风格锁、资产、提示词、音色、审核登记。别把"记住参数"理解成"记住这部剧"；
- **管理**：`drama.py settings` 看当前记忆，`--from <项目>` 用某个项目的参数覆写记忆，`--reset` 删掉记忆回到内置默认；
- 换了机器 / 换了 ComfyUI 地址，记得 `--reset` 或重新保存一次，否则新项目会带着旧机器的地址和模型路径起步。

### 第 3 阶段用的 H3 工作流（`references/workflows/minimax-h3.ref2va.api.json`）

来源：`MiniMax-H3-Star7chunk-1006api专用.json`（用户导出，2026-10-20 替换；相比上一版去掉了 VEDA 稀疏注意力与实时预览）。
节点 id、入参口径与上一版完全一致，`H3_NODE` 映射不用改。链路：

```
增强载入(391) → LoRA turbo_v4(311) → SigmaShift 6/3(313) → 显存分块加速(363)
 → 基本引导器(128) → 采样器(127, euler/simple/5 步)
 → 一键高清放大(376, enable_hd 由 h3Hd 控制) → 一键人脸修复(395, 默认关)
 → 分块解码(377) → VideoCombine(150, nvenc h264 5Mbps)
```

- 提示词走 `MiniMaxH3PromptImportStar7(334).prompt`（纯文本，不是旧版的 `PrimitiveStringMultiline.value`）。
- 参考图 `TaiYangMultiImageLoader(429)` 16 路输出、参考音 `TaiYangMultiAudioLoader(430)` 8 路输出；
  技能最多挂 `AUDIO_SLOTS = 2` 路参考音（`ref_audio_0/1` ← `<Audio 1>/<Audio 2>`）。
- **二采高清**：`MiniMaxH3OneClickHDStar7(376)`，`enable_hd` + `target_megapixels`。关着节点仍在链上直通，
  不改模型图结构；打开后每段多一采，耗时约成一采的 1.6–2 倍。
- **导出节点 `Star7VideoWorkflowExport(339)` 提交前会被摘掉**：它只是再写一份带工作流的视频，
  批量跑用不上，还会让 `history.outputs` 里出现两个视频、挑错文件。
- 每次提交前 `verify_graph()` 会自检：节点映射是否对得上、连线是否指向已删节点、关键值是否写进去，
  不通过直接退出并指出是哪个节点（`--dry` 也会跑这套自检）。


模型列表走 `GET /api/models`：serve 进程每次**现读** ComfyUI 的 `/object_info`，**不做任何缓存**（浏览器端同样
`cache: no-store`）。页面每次打开、每次切到「资产 / 视频提示词」页、每次点「刷新模型列表」都会重读一遍，
所以下拉里只会有此刻真实存在的模型文件——删掉的模型不会赖在列表里。

- 保存过的模型如果已经不在 ComfyUI 里：前端 `alignModels()` 会把它切到「默认名若存在则默认名，否则列表第一项」
  （LoRA 特殊情况：文件没了就不挂 LoRA），并在参数区提示 + 弹一次 toast，同时置脏，等用户点保存落盘。
- 读不到列表（ComfyUI 离线 / 地址错）时：下拉只显示一条「（ComfyUI 里没读到模型）」占位，**不动项目里已存的模型值**，
  免得把设置改成空。ComfyUI 起来后点「刷新模型列表」即可。

- **整批入队**：先把所有段的参考图/参考音上传、工作流建好，再连续 `POST /prompt`，最后统一收结果。
  ComfyUI 队列连续执行，模型只加载一次（铁律 10）。
- 每完成一段就写回 `drama.json` 并重建 HTML，成品页立刻出现播放器。
- 参考音：`cast` 里前两个"已绑定参考音"的角色会挂 `ref_audio_0/1`，`audio_mode` 自动切 `仅作音频参考 / Reference Only`；
  其余角色（含第 3 个人物起）走 `模型原生生成 / Native`，但提示词里仍有他们的固定音色描述。
- 音色句由 `build` / `videos` 调 `sync_voice_tags()` 自动补/改（铁律 12）：挂参考音写 `<Audio N>`，
  没挂就写该人物的固定音色提示词。换完音色一定要重跑 `build` 再呈现（提示词变了 → 指纹变了）。
- 中途断了直接重跑同一条命令，已完成的会跳过（`--force` 才重跑）；**重跑前不要重启 ComfyUI**，模型还在显存里。
- 单段失败不会中断整批，失败原因写进 `segments[].error`，页面卡片上会看到。
- 耗时心里要有数：H3 工作流换代后（5 步 + 分块加速 + 分块解码）速度跟旧链路不一样，
  **第一次跑先只跑一段量实际速度**，再按实测值 × 段数估算告诉用户。开二采高清要在此基础上再乘约 1.6–2。
  实测口径（RTX 2080Ti / 640x1120·0.72MP / 5 步 / 3 张参考图）：**每秒成片约 0.9–1.1 分钟**，
  11.5 秒的段大约 10–13 分钟采样、再加 1.5–2 分钟装模型与解码。**开跑前先把预计总时长告诉用户**，长批次分批跑。
- **速度三件事**（都是实测结论，报工期时按这个说，别拿旧链路的 1.5–2.5 分钟/秒去估）：
  1. **时长必须落在帧数干净档上**。工作流的 `ComfyMathExpression(134)` 会把帧数补齐到 `5 (mod 17)`，
     所以能精确对齐的只有 **243 帧 = 10.125s** 和 **345 帧 = 14.375s**。落在档间（11.5s、12.2s）会被就近吸到
     别的档，每步明显变慢。`check` 会直接报「时长与帧数档位」并给建议。
     写剧本时优先把单段凑成 10 秒档；确实需要更长就凑 14.4 秒档，不要写 11–13 秒这种中间值。
  2. **参考图每多挂一张，`S` 就多约 7.7k token**（`reference_quality` 默认是 Max）。三张（两个人物 + 一个场景）
     约占总量 32%，每步多 8 秒左右。场景图不是每段都必须挂，靠 `<Subject 3>` 文字锁场景也能过。
  3. **机器状态浮动极大**：同一台机、同一参数，一天里每步可以从 95s 飘到 168s（250W 功率墙 + 长跑降频）。
     所以「比我在 ComfyUI 里慢」这类反馈，先看 `user/comfyui.log` 里那次运行的 `Tile plan` 与每步 `s/it`，
     再对比 token 数 `S`，**不要凭感觉归因到技能**。

最后：

```bash
$PY scripts/drama.py check --project "$P"
```

需要拼接成片时，用本机 ffmpeg（例如剪映自带）按 `segments` 顺序无损 concat：

```bash
FF="<ffmpeg 路径>"
for id in P01 P02 P03; do echo "file 'videos/$id.mp4'" >> list.txt; done
"$FF" -y -hide_banner -f concat -safe 0 -i list.txt -c copy -movflags +faststart "成片.mp4"
```

---

## 阶段与产物一览

| 阶段 | 产物 | 谁来改 | 确认点 |
|---|---|---|---|
| 1 提示词 | `meta` + `assets[]` + `segments[].promptSegs/refs/cast` | AI 写，人改中文 | 钩子狠不狠、英文格式对不对、中文是不是他想表达的 |
| 2 资产图 | `assets[].image` | 脚本生成，人可上传替换 | 人脸像不像、场景对不对、留白够不够 |
| 3 视频 | `segments[].video` | 脚本生成 | 口型、音色、光影、有没有多出人 |

---

## 参考文件

| 文件 | 什么时候读 |
|---|---|
| `使用手册.md` | **给用户看的中文说明书**（怎么唤起、四页怎么用、参数怎么调、常见问题）。用户问"怎么用"先甩它，不要口头复述 |
| `references/01-h3-prompt-bilingual.md` | 第 1 阶段，写 H3 提示词前（**本技能的落地规范**） |
| `references/h3-wenxi-v2-template.md` | 第 1 阶段，查结构/运镜/光影/台词预算（**权威模板**，原 minimax-h3-wenxi-prompt-v2） |
| `references/02-asset-prompt-spec.md` | 第 1 阶段，写资产前（该建什么、信息项、比例） |
| `references/03-qwen-image-prompt.md` | 第 1 阶段，写资产提示词（**Qwen-Image 2.1 规范**，融合 qwen-image-2.1-skill） |
| `references/qwen-t2i-rules.md` | 资产提示词权威细则（八步框架原文） |
| `references/qwen-cheat-sheet.md` | 查材质 / 方位 / 光照 / 比例词汇 |
| `references/qwen-edit-rules.md` | 人要改图、换背景、多图合成时 |
| `references/04-comfy-api.md` | 第 2/3 阶段，调接口或排查失败时 |
| `references/05-project-schema.md` | 任何需要确认字段含义时 |
| `references/workflows/*.api.json` | 三份内嵌工作流，脚本自动读取，不手动改 |