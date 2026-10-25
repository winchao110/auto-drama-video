# 01 · H3 提示词生成规范（双语版 · 融合 minimax-h3-wenxi-prompt-v2）

本技能不再生成"剧本"，也不生成分镜表。**读完小说/剧本，直接产出三样东西**：

1. H3 分段提示词（英文正文 + 中文对照，逐段配对）
2. 资产提示词（人物 / 场景 / 道具）
3. 视频简介（观众视角的成片简介，写给发布文案用）

结构骨架、运镜公式、光影套件、台词预算、固定尾部等全部规则，**权威来源是 `h3-wenxi-v2-template.md`**（原 minimax-h3-wenxi-prompt-v2 的完整模板，已并入本技能）。本文件只规定"在本技能的流水线里怎么落地"。

---

## 一、和原模板的差异（只有这三条）

| 项 | 原 v2 模板 | 本技能 |
|---|---|---|
| 输出语言 | 默认纯中文 | **英文正文为唯一生成用文本，中文逐段对照** |
| 结构 | 中文小标题段落流 | **六段式英文块**：`subject_definitions / summary / retention_analysis / detailed_description / overall_soundscape / non_diegetic_music`（见 2.1） |
| 时长 | 单元标题写 5–15 秒 | 提示词可写 5–18 秒；**API 实传 = round(sec × 5/6)**；**Shot 内一律不写时长** |
| 配音 | 只写声线文字描述 | 可选**参考音**：HTML 里给角色挂音频，H3 切 `仅作音频参考 / Reference Only` |

其余（Subject/S 编号、只写出场人物、Picture 段内重排、口型同步、禁止可读文字等）**全部照原模板执行**。
**四处例外，以本技能为准**：① 不设独立的"人物站位"段，但 `subject_definitions:` 的场景条里必须带一句"本段开场站位与姿势"（四之三 · 铁律 C）；
② 全局光影只在场景条声明一次，Shot 里不再写任何光影微调（四之三 · 铁律 D）；
③ 结尾不再有 `【禁止项】`/`【强制声明】` 两块，禁止项并进 `detailed_description:` 首句；
④ Shot 里不写 `At 00:03.000` 之类时间码，镜头长短交给模型。

---

## 二、双语段落对（核心）

### 2.1 六段式结构（2026-10-19 起强制，按官方 H3 长提示词格式）

每个单元提示词 = **固定六个块，顺序与块名都不许改**（英文小写 + 英文冒号，顶格另起一行）：

| # | 块名 | 写什么 |
|---|---|---|
| 1 | `subject_definitions:` | 每个 `<Subject N>` 一行：是什么 + 对应 `<Picture N>` + 关键外观。`<Audio N>` 也在这里，指向它要模仿的人物。**有场景图时场景排第一条**，人物随后 |
| 2 | `summary:` | 一段话讲本段整体发生什么（模型靠它理解意图），开头可带 `[reference generation + audio reference]` |
| 3 | `retention_analysis:` | 逐 Subject 一行，写本段必须保住的特征：`fully_preserved - …`；音频写 `reference - …` |
| 4 | `detailed_description:` | 第一句是全局风格 + 画幅 + 画质 + 禁止项；随后每个 `[Shot N]` 一块 |
| 5 | `overall_soundscape:` | 环境声一句话（房间底噪、室外声） |
| 6 | `non_diegetic_music:` | 有配乐写配乐，没有就写 `N/A` |

```text
subject_definitions:
<Subject 1> is the living room in <Picture 1>, an oatmeal sofa, an off-white wall, a walnut
tea table with a glass of water, warm lamplight.
<Subject 2> is SU MO in <Picture 2>, a 28-year-old woman, light-grey hoodie, white shorts, low
ponytail. Opening state: she sits on the left half of the sofa, her torso turned to the right.
<Subject 3> is CHEN YU in <Picture 3>, a 30-year-old man, black tee, grey sweatpants, short
black hair. Opening state: he sits sprawled at the right end of the sofa, phone in his right hand.
<Audio 1> is the voice-timbre reference for <Subject 2> (S2), containing a spoken Chinese vocal layer.
<Audio 2> is the voice-timbre reference for <Subject 3> (S3), containing a spoken Chinese vocal layer.

summary:
[reference generation + audio reference] SU MO tests CHEN YU on the sofa; he answers without
lifting his eyes from his phone, and she leans in to press the point.

retention_analysis:
<Subject 1> (appears in [Shot 1], [Shot 2]): fully_preserved - the oatmeal sofa, off-white wall
and walnut tea table are retained.
<Subject 2> (appears in [Shot 1]): fully_preserved - her oval face, low ponytail and grey hoodie are retained.
<Subject 3> (appears in [Shot 2]): fully_preserved - his short black hair, black tee and grey sweatpants are retained.
<Audio 1>: reference - its vocal timbre guides <Subject 2>'s delivery without copying the original signal.
<Audio 2>: reference - its vocal timbre guides <Subject 3>'s delivery without copying the original signal.

detailed_description:
The target video uses a realistic multi-camera sitcom style, 24fps, horizontal 16:9 framing,
natural unretouched skin texture, warm indoor evening light; no on-screen text, subtitles,
watermark, logo or UI at any moment.
[Shot 1] Over-the-shoulder, close-up, ... <Subject 2> (S1) says:
<d>[Chinese]你们男人是不是都喜欢年轻的呀？</d>
[Shot 2] Over-the-shoulder, medium shot, ...

overall_soundscape:
Soft living-room room tone throughout, a faint hum from the building outside the window.

non_diegetic_music:
N/A
```

**上传替换的资产：`<Subject N>` 只写「严格参照图 N」**

资产图如果是用户自己上传替换的（`assets[].imageSource == "user-upload"`），这个 Subject 的段落**不许再有描述词**：

```text
<Subject 2> is the person shown in <Picture 2>; face, hair, body build and clothing strictly follow
<Picture 2>, with nothing added or described.
```

- 场景写 `layout, materials, furniture and lighting strictly follow <Picture 1>`；
  道具写 `shape, material, colour and wear strictly follow <Picture 3>`。
- 中文块同样只写一句：「<Subject 2> 就是 <Picture 2> 里的这个人：相貌、发型、体型与服装全部严格参照 <Picture 2>，不再另加描述。」
- **保留**：场景条的 `Opening state:`、已注入的音色句。
- `retention_analysis` 里对应行改成 `fully_preserved - identity, hair, build and clothing follow <Picture 2>.`
  （场景用 layout/materials/furniture/lighting，道具用 shape/material/colour/wear）。
- 由 `build` / 上传接口自动改写，不要手写回描述；`check` 会判「和上传的图对不上」。

**英文块是唯一送进 H3 的文本**（`seg_prompt()` 只拼 `en`）；中文块只作人读与修改入口。

### 2.2 断段规则（必须逐条遵守，否则中英对不齐）

一个"段落对"= 工作台上可独立编辑的一小块。**块名那一行只写在该块的第一段开头**，
所以中文块的块名要逐字对应（用相同英文块名，方便对位）。

| # | 元素 | 内容 |
|---|---|---|
| 1 | 第 1 个 Subject | `subject_definitions:` 顶格 + 场景或第一个人物（含本段开场站位/姿势） |
| 2… | 其余 Subject | 每人一段 `<Subject N> is …`（含音色句 `<Audio N>`，机器注入） |
| — | `summary:` | 一段，本段剧情概括 |
| — | `retention_analysis:` | 一段，逐 Subject 保真说明（可多行） |
| — | `detailed_description:` | 首句风格/画幅/禁止项，随后 **每个 `[Shot N]` 单独一段** |
| — | `overall_soundscape:` | 一段 |
| — | `non_diegetic_music:` | 一段（`N/A` 也算一段） |

**不要再写 `【禁止项】` / `【强制声明】` 两个尾部块**——禁止项已并进 `detailed_description` 第一句。

**Shot 里绝对不写时长**：不写 `At 00:03.000`、不写 `[0-3秒]`、不写"前 2 秒"。镜头的长短交给模型，
`[Shot N]` 后面直接写这一镜的运镜、景别、动作与台词。

**不要**把两句 Shot 塞进同一个块，也不要把 `says:` 和 `<d>` 拆成两块——否则用户改中文时 AI 无法定位该改哪段英文。

### 2.3 语言规则

- 英文块：描述性内容全部英文；**结构标签原样保留**：`<Subject1>`、`<Subject 1> (S1) says:`、`<d>[Chinese]…</d>`、`<Picture 1>`、`<Audio 1>`、`[Shot N]`、六个块名（`subject_definitions:` 等）。
- **台词一律放在 `<d>[Chinese]台词</d>` 里，保留中文原文**，不做英文翻译、不写拼音。这是让 H3 说中文的唯一开关。
- 人物名：英文块写拼音全大写（`SHEN YAN`），中文块写中文原名（`沈砚`）；两处指向同一 `<SubjectN>`。
- 禁止项并进 `detailed_description` 首句，例如：

```
The target video uses a realistic multi-camera sitcom style, 24fps, horizontal 16:9 framing,
natural unretouched skin texture, warm indoor evening light; no subtitles, no on-screen text,
no watermark, no logo, no UI, no corner mark at any moment; no background music, ambience,
human voice and SFX only.
```

### 2.4 中文改动回同步英文（人机闭环的关键）

用户在 HTML 里只改中文（`promptSegs[i].zh`），一旦输入就把该段标成 `edited: true`。用户保存并说"改好了"后：

1. 读 `drama.json`，找出所有 `promptSegs` 里 `edited == true` 的段。
2. **逐段对齐**：第 i 个中文改动 → 重写第 i 个英文段，段落数、顺序、结构标签一字不动，只把语义换成中文的新意思。
3. 遵守原格式：运镜词库、景别词库、光影公式、Shot 不写时间码、台词仍放 `<d>[Chinese]…</d>`。
4. 改完把 `edited` 置回 `false`，`build` 重建 HTML。
5. 若中文改动导致段落增减（例如用户加了一句台词），按结构补/并英文段，保持"一段对一段"。

**永远不要**把中文直接塞进 `en` 字段，也不要为了省事把整段中英混排送生成。

---

## 三、时长口径（恒定少 1/6）

- `sec`：提示词里声明的时长，5–18 秒（这是"戏看起来有多长"）。
- `genSec`：真正传给 H3 的 `duration`，`genSec = 四舍五入(sec × 5/6)`，再夹进项目设定的**每段时长区间**
  `settings.segSecMin`–`segSecMax`（默认 **6–15**，页面「视频参数」里两个小下拉）。

| sec | 8 | 10 | 12 | 15 | 18 |
|---|---|---|---|---|---|
| genSec（区间 6–15，默认） | 7 | 8 | 10 | 13 | 15 |
| genSec（区间 10–15） | 10 | 10 | 10 | 13 | 15 |

### 区间 = 提示词硬约束（写段之前先反解）

`sec_prompt_range()` 把区间反解成"每段该写多少秒"，**写完必须落在里面**：

| 每段时长区间（实传） | 提示词 `sec` 应写 | 备注 |
|---|---|---|
| 5–15 | 6–18 | 最宽；等于旧的 5–15 口径 |
| **6–15（默认）** | **7–18** | 6s 的短段要补到 7s 才合规 |
| 8–12 | 9–14 | 中间收紧，短视频常用 |
| 10–15 | 12–18 | 想每段都长，台词得加密 |
| 12–15 | 14–18 | 接近 H3 上限 |

- `sec` 写在范围外 → `check` **硬问题**："这段必须按 X–Ys 重写"，不是警告。
- 工作台分镜卡上会直接打红标「超出时长区间：要写成 7–18s」。
- 区间改了 = 提示词指纹变了：旧审核作废，必须重新 `build` → 呈现 → `present`，再生成。
- 重写时优先**加镜头/加反应**，其次扩动作，台词本身尽量不动（台词是剧本的，时长是节奏的）。

代码里由 `gen_sec()` 统一算，`build` 每次重算，`check` 会校验是否一致。**HTML 卡片头写"18s → 实传 15s"，别手改 genSec。**

H3 的帧数由 `length = round(genSec × 24)` 再按 17 帧对齐，节点自己处理，不要手填帧数。

---

## 四、台词与 Shot 密度（照原模板）

| 目标时长 | 建议台词 | 建议 Shot 数 |
|---|---:|---:|
| 5 秒 | 12–18 字 | 1–2 个 |
| 8 秒 | 20–28 字 | 2–3 个 |
| 10 秒 | 24–32 字 | 2–3 个 |
| 12 秒 | 32–40 字 | 3–4 个 |
| 15 秒 | 40–48 字 | 3–5 个 |
| 18 秒 | 48–56 字 | 4–6 个 |

52 字是紧凑语速的经验硬上限，18 秒段最多 56 字。超出就拆段，别硬塞。

---

## 四之二、H3 落地八条（写的时候就要满足，`check` 会逐条验）

H3 不是编剧，它只认"能在几秒画面里看见的东西"。文字通顺但模型做不到，就是废稿。
下面八条是硬约束，可机检的部分已写进 `drama.py check`。
**八条之上还有「四之三 · 构图与连续性四铁律」，优先级更高；两者冲突时按四铁律写。**

### ① 场景不穿帮：场景只声明一次，Shot 不再复述背景

**`subject_definitions:` 里的场景条把空间、家具、墙面一次写全，每个 `[Shot N]` 不再写"身后是什么"。**
Shot 里重复背景等于每镜重新描述一遍同一面墙，模型会把注意力从动作挪到布景上，还会和场景参考图打架。

- ✅ 场景条：`<Subject 1> is the living room in <Picture 1>, a light oatmeal sofa against a plain warm off-white wall, a walnut coffee table in front of it`
- ✅ Shot：`Over-the-shoulder, close-up, the near shoulder of CHEN YU soft along the lower right edge, SU MO sharp beyond it, …`
- ❌ Shot 结尾补一句 `the sofa back and the off-white wall behind her` → 每镜都重述布景，动作被稀释

同段内出现两个不同空间（客厅＋卧室）时，必须写清移动过程，否则拆段。

### ② 关键道具必须有始有终

道具第一次出现要写"谁拿着 / 放在哪"，最后一次不能凭空消失，要写"放下 / 塞进口袋 / 扔在沙发上"。

- ✅ Shot1 `his phone in his right hand`；Shot4 `he drops the phone onto the cushion`
- ❌ Shot1 有手机、Shot4 手里空了，中间没交代 → 明显穿帮

建了 `type=prop` 的资产就必须至少进一镜；进不了镜头的道具删掉。

### ③ 风格要贯穿，别演成严肃正剧

整体风格（轻喜剧 / 写实 / 反转感）必须落到**每段的表演层**，不能只在简介里写一次。

- 每段至少一处可见的生活化反应：`one eyebrow lifts a hair`、`his smirk freezes`、`her mouth falls open`
- 禁正剧化词：`solemn`、`somber`、`tragic`、`沉痛`、`悲壮`、`凝重`
- 反转点写在**表情链**上（僵住 → 慌半秒 → 眼珠一转 → 反将一军），不是写"他反将一军"

### ④ 抽象描述全部转具象（最容易被忽略的一层）

| 抽象（模型看不懂） | 具象（模型演得出） |
|---|---|
| 老公灵机一动 | 表情一僵 → 眼神慌半秒 → 眼珠一转 → 嘴角一挑 |
| 她有点心虚 | 眼神飘向别处 → 手指蜷一下 → 咽了下口水 |
| 气氛尴尬 | 两人都不说话 → 她低头理了理裙摆 → 他清了下嗓子 |

**高难度动作降级**：H3 手部精细操作很弱。

- ✅ `holding a phone`、`resting one hand on the cushion`
- ❌ `指尖在屏幕上快速滑动`、`拨弄着戒指`、`unbuttons his cuff`

### ⑤ 时序与连续性

- **一镜一件事**：`走进客厅 → 坐下 → 拿起手机 → 提问` 是四个事件，至少拆两镜。
- **姿势与位置只在本段场景条写一次**（见「四之三 · 铁律 C」），Shot 里只在**人物真的动了**的时候写
  `from … to …`，没动就一个字都不写位置。上一镜站着、下一镜坐着而中间没有"坐下"动作 = 瞬移。
- **朝向与道具前后一致**：他面朝左，下一镜不能突然面朝右，除非写"转身"。

### ⑥ 只用 H3 认识的术语

- 可用：`push in / pull back / pan / tilt / track / dolly`，`close-up / medium shot / full shot / wide shot / reverse shot`，
  `over-the-shoulder / over-the-waist`（过肩 / 过腰）
  （推、拉、摇、跟、移；近景、中景、全景、正反打；过肩、过腰）
- 不用：`升格`、`跟焦`、`浅景深`、`拉焦`、`变焦`、`荷兰角`、`摇臂`、`斯坦尼康`、
  `slow motion`、`rack focus`、`shallow depth of field`、`dutch angle`
- 想表达浅景深，写大白话：`the background falls away softly`

### ⑦ 多人同框：站位写在场景条，不写进 Shot

一镜出现两个人，**先在 `subject_definitions:` 的场景条**把左右与前后写死一次：

> `S2 sits slumped at the right end of the sofa, one hand holding a phone; S1 sits close on his left, her torso tilted toward him.`

然后 Shot 里**不要重复**"他在左、她在右"——重复等于给模型一条新指令，它会重新排站位。
**一镜只允许一个人说话**，两句台词必须分镜。

### ⑧ 窄屏：一律不许两人同框

窄屏（画幅宽高比 < 1，即 9:16 / 3:4）下**任何情况都不许两人同框**，哪怕并肩也不行——模型会把画面劈成左右两半。

- 一人一镜，用**正反打**接：她说完切他，视线方向对着彼此。
- 需要交代"两人在一起"时，用**过肩/过脸**：前景只留另一个人的肩线或侧脸轮廓，主体仍然只有一个人。
- 宽屏（16:9 / 21:9 / 4:3）才可以两人同框；两人隔着整个房间时必须拆成正反打。

---

## 四之三、构图与连续性四铁律（2026-10-19 用户钦定，优先级最高）

这四条覆盖本文其他条目与 `h3-wenxi-v2-template.md` 里任何冲突的写法。**每一段提示词都要同时满足。**

### 铁律 A：画幅决定能不能同框

| 画幅 | 同框 | 怎么写 |
|---|---|---|
| 宽屏（16:9 / 21:9 / 4:3，宽高比 ≥ 1.3） | 可以 | 两人同框时写清左右，最好用关系镜头 |
| 方屏（1:1） | 可以 | 必须并肩/贴身/同一张沙发，不许分置两端 |
| 窄屏（9:16 / 3:4，宽高比 < 1） | **禁止** | 一人一镜，正反打或过肩/过脸接 |

判断以工作台「视频参数 → 宽高比」为准，不是凭剧本想象。`check` 会直接卡窄屏双人同框。

### 铁律 B：优先"过脸 / 过肩 / 过腰"的关系镜头，交代前景后景

单人镜头也必须有空间关系，不许拍成一张平面照。首选这四种：

| 写法 | 英文 | 交代了什么 |
|---|---|---|
| 过脸 | `past her cheek, close-up, …` | 前景是对方侧脸轮廓，主体在对面 |
| 过肩 | `over-the-shoulder, close-up, …` | 前景是一条肩线压住画面一侧 |
| 过腰 | `framed past his waist, medium shot, …` | 前景人物只入画到腰际，前后景都在 |
| 正反打 | `reverse shot, medium shot, …` | 一人一镜，靠视线方向接起来 |

**每个镜头都要能说出"前景是什么、后景是什么"**，写不出来就是平面照。可套的句式：

```
over-the-shoulder, close-up, the near shoulder of <Subject 2> filling the lower left edge,
<Subject 1> sharp beyond it, the sofa back and the off-white wall behind her
```

**焦距给谁**（说话或做动作的人必须是焦点所在，对手只作前景轮廓；禁用 `rack focus / shallow depth of field`）：

- 焦点在前景：`the focus holds on the near figure, the far side of the room falls away softly`
- 焦点在后景：`the focus sits on the far figure, the near shoulder reads soft and out of register`

**全局块两处禁区**（`check` 会查）：

- 画幅词必须和「视频参数 → 宽高比」一字不差：`vertical 9:16 framing` 只配 9:16，改成 16:9 就必须同步改成
  `horizontal 16:9 framing`，否则提示词按竖屏构图、实际出横屏，人脸和站位全乱。
- 不要写 `focus held on the face in every shot`（每镜都锁脸），它会把"焦点给前景还是后景"这条废掉。

### 铁律 C：每段独立，禁止跨段上下文

ComfyUI 是**一段一个任务**送进去的，模型不知道上一段发生了什么。所以：

1. **禁止任何跨段指代**：`still / remains / continues / as before / same as the previous / 仍然 / 依旧 / 还是坐在 / 仍坐在 / 继续坐在 / 如前`。
   `check` 命中即报硬问题。
2. **每段必须在 `subject_definitions:` 里把"本段开场状态"重写一遍**：谁在哪、什么姿势、手里有什么、朝向谁。
   写在场景条（有场景图时是第一条 `<Subject 1>`）的末尾，环境写完后接 `Opening state:` 一句：

```
subject_definitions:
<Subject 1> is the living room in <Picture 1>, an oatmeal sofa, a glass of water on the walnut
tea table, a plain off-white wall. Opening state: CHEN YU sits slumped at the right end of the
sofa with a phone in his right hand; SU MO sits close on his left, her torso tilted toward him.
```

```
subject_definitions:
<Subject 1>是客厅场景，<Picture 1>，燕麦色沙发、胡桃木茶几上放着玻璃杯、暖白色墙面。
本段开场：陈屿瘫坐在沙发右侧，右手拿着手机；苏沫坐在他左侧，身体歪向他。
```

没有场景图时（只有人物图），把同一句 `Opening state:` 写在**第一个人物条**的末尾。
- 这段是**本段的起点**，后面每一镜的位置都从这里推。
- 姿势用实词：`sits / seated / slumped / sprawled / stands / leans / lies`，位置用锚点：`sofa / bed / door / window / desk / floor + left / right / centre`。
- 人换了地方（上一段在沙发、这一段在门口），就在场景条里直接写新位置 + 怎么到的（`standing at the doorway, keys still in hand`），不要写"她走过去"这种跨段动作。

### 铁律 D：Shot 里只写"这一镜发生的变化"

1. **人物没移动，就不写位置**。不要每镜复制"她在画面左侧、他在右侧"，模型会重排站位。
2. **人物动了，必须写"从哪到哪"**，起点与场景段的开场状态一致，终点能接上下一镜：
   - ✅ `she leans further in from his left, closing the gap to a hand's width`
   - ❌ 开场"两人坐在沙发上"，下一镜写 `she stands at the window`（中间没有起身走过去 → 瞬移）
3. **一段内只允许一次位移**；要换空间就拆段。
4. **Shot 里不写光影**。全局光影已在 `detailed_description:` 首句声明一次，每镜再写会把模型带到不同光位，也会和资产图的光打架。
   要写"看不看得清"就写材质和方向（`the sleeve catches the fold of the cushion`），不写灯、不写色温、不写亮边。

---

## 五、音色规则（本技能新增）

**每个人物必须有音色依据，两条路互斥，全剧同一个人物永远用同一套。**

| | 路 A：参考音频 | 路 B：固定音色提示词 |
|---|---|---|
| 前提 | `assets[].voice` 指向 `voices[]`，且音频文件真实存在 | 没挂参考音频，只有文字描述 |
| 存在哪 | 音频文件 `voices/vN.ext` | `assets[].voicePrompt`（英文）+ `voicePromptZh`（中文对照） |
| 写进提示词 | `<Audio N>` 参考句 | "整部剧只用这一种音色"句 |
| H3 行为 | 音频接 `ref_audio_0..N`，按参考音的音色/语速说话 | 不接任何参考音，按文字描述造声 |

**为什么音色描述不写在每一段里**：写进 `assets[]` 之后，同一个人物所有分镜共用同一条描述，
不会出现"第 1 段冷一点、第 4 段甜一点"。这也是"一个人的音色整部剧一样"的机器保证。

### 5.1 绑定 → 槽位 → 提示词标签（一一对应）

| 项 | 规则 |
|---|---|
| 绑定位置 | 资产 `voice` 字段（只对 `type = character` 生效），音频在 `voices[].file` |
| 取哪几路 | 按 `cast` 顺序取前 **3** 个"已绑定且音频文件真实存在"的人物 |
| 工作流槽位 | 第 1/2/3 路 → `ref_audio_0` / `ref_audio_1` / `ref_audio_2`（`TaiYangMultiAudioLoader` 的第 0/1/2 个输出，节点上限 3 路） |
| 提示词标签 | `<Audio 1>` / `<Audio 2>`（**1 起数**，与 `<Picture 1>` 同规矩；`ref_audio_0` = `<Audio 1>`） |
| 写在哪一段 | 该人物的 `<Subject K>` 段末尾，K = 该人物在 `cast` 里的下标 + 1 |
| 第 4 人起 | 挂不上参考音 → 自动退回路 B，写他的固定音色句，不会没有声音设定 |
| 参考音开关 | 新工作流没有 `audio_mode`：挂了 `ref_audio_*` 就是参考音，没挂就是模型原生生成 |

### 5.2 路 A 固定句（逐字，不许改写语义）

英文块：

```
<Audio 1> is the voice-timbre reference for <Subject 1> (S1), containing a spoken Chinese vocal layer; inherit its timbre alone — vocal texture, pitch and speaking pace — and never its recorded words, dialogue or content. This same voice is used for <Subject 1> in every shot of the whole drama.
```

中文块：

```
<Audio 1> 是 <Subject 1> 的音色参考：仅继承其音色（音质、音高、语速），不继承、不参考这段参考音里的台词与内容；整部剧的每一个镜头，<Subject 1> 都用这一种音色。
```

要点三条，缺一条就等于没写：

1. **指明这是"音色参考"**（timbre / voice reference），不是台词参考；
2. **明确否掉原台词**（never its recorded words, dialogue or content），否则 H3 会把参考音里说过的话当成台词复述；
3. **点明全剧同一音色**，避免每条分镜重新抽签。

### 5.3 路 B 固定句（把资产里的描述嵌进去）

英文块：

```
<Subject 1> keeps one fixed voice for the whole drama: {voicePrompt}. This same voice is used in every shot of the drama and never changes.
```

中文块：

```
<Subject 1> 在整部剧里只使用一种固定音色：{voicePromptZh}。这个音色在任何镜头、任何场景中都不改变。
```

`{}` 里的内容取自 `assets[].voicePrompt / voicePromptZh`，**一条描述全剧复用**；
描述本身写成"年龄段与性别呈现 + 音域 + 音色质感 + 语速 + 音量 + 句尾习惯 + 情绪变化 + 一句禁止项"，40–80 词。

### 5.4 谁维护这段文字

由 `drama.py` 的 `sync_voice_tags()` 自动维护，`build` 和 `videos` 都会跑一次：

- 每段把本轮写进去的句子记在 `seg.voiceTags` 里（含 `subject` / `kind` / `audio_no` / 原文）；
- 下次同步时**先按原文精确删除，再按最新绑定插入**，所以换音色、换参考音、撤销都不会叠成一堆重复句；
- 顺带清掉旧模板残留的两句：`S1 is always the speaker`（/`S1 永远是说话人`）直接删，
  `S1 always uses one fixed voice: …`（/`S1 始终使用一种固定的声音：…`）抽到 `assets[].voicePrompt` 后删；
- `check` 校验：每个人物有没有音色依据、`<Subject K>` 段是否存在、句子有没有真的落进提示词、
  有没有残留"永远是说话人"这类词。

### 5.5 三条硬禁令

1. **不要写 `S1 永远是说话人` / `S1 is always the speaker`**，也不要写"某人负责说话"这类旁白式说明；
   说话人由 `says:` + `<d>` 台词标签表达。
2. **不要在各段里重复写声线描述**：音色只存在于 `assets[]`，段里只留机器注入的那一句。
3. **同一个人物不许两套音色**：换了参考音或改了描述，就必须重跑 `build` 让所有段一起变。

---

## 六、数据落地（写到 drama.json）

```json
{
  "id": "P01",
  "title": "雨夜刑房 · 他亲手签了处决令",
  "chapter": "第一章",
  "sec": 18,
  "genSec": 15,
  "logline": "老何啐了他一口，他下令就地处理。",
  "cast": ["c1", "c2", "s1"],
  "refs": [{"asset": "c1"}, {"asset": "c2"}, {"asset": "s1"}],
  "promptSegs": [
    {"en": "【GLOBAL QUALITY ...】...", "zh": "【全局画质与摄影前置】...", "edited": false},
    {"en": "<Subject1>SHEN YAN is <Picture 1>...", "zh": "<Subject1>沈砚是<Picture 1>...", "edited": false}
  ],
  "video": "",
  "status": "pending"
}
```

- `cast` 必须是"本段真实出场"的资产 id，按 Subject 顺序排列（人物在前、场景在后）。
- `refs` 顺序 = Picture 编号顺序，**段内从 P1 连续重排**，与 `cast` 里的人物对应。
- `promptSegs` 的 `zh` 允许为空（AI 只写英文也能跑），但推荐成对写全，人才能改。

---

## 七、交付前检查（在 05 的 checklist 之上加这几条）

- [ ] 每个单元 `promptSegs` 的中英段数一致，一段对一段。
- [ ] 英文块里除结构标签外没有中文（台词例外，台词必须中文）。
- [ ] 台词都在 `<d>[Chinese]…</d>` 里，没有漏掉 `[Chinese]`。
- [ ] `sec` 在 5–18，`genSec` = round(sec×5/6)，两者没有被手改。
- [ ] `cast` 只写本段真出场的人，`refs` 顺序与 `<Picture N>` 一致。
- [ ] **六个块齐全且顺序正确**：`subject_definitions` → `summary` → `retention_analysis` → `detailed_description` → `overall_soundscape` → `non_diegetic_music`。
- [ ] `detailed_description` 首句写明风格 + 画幅 + 画质 + 禁止项（字幕/水印/UI/配乐）。
      禁止项里**必须**有 `no on-screen text, subtitles, watermark, logo or UI at any moment`（铁律 23）；
      漏了不会出事——`seg_prompt()` 会自动补到段尾——但手写版要自己带上，中文对照也写「全程无屏幕文字、无字幕、无水印、无台标、无 UI」。
- [ ] `retention_analysis` 覆盖 `subject_definitions` 里的每一个 `<Subject N>`。
- [ ] 每个 Shot 有运镜 + 景别 + 动作链，**Shot 内没有任何时长/时间码**。
- [ ] **画幅对得上同框规则**：窄屏（9:16 / 3:4）没有一镜两人；宽屏双人同框写了左右与前后。
- [ ] **关键对话用了过脸 / 过肩 / 过腰 / 正反打**之一，每个 Shot 都能说出前景是什么、后景是什么。
- [ ] **每段 `subject_definitions` 的场景条都重写了本段开场站位与姿势**（谁在哪、坐/站/靠/躺、手里有什么、朝向谁），不靠"仍然/如前"。
- [ ] **Shot 里没有光影词**（灯、光、色温、亮边、阴影都没有），也没有在人物没移动时写画面位置。
- [ ] 18 秒段台词 ≤ 56 字，其他段按密度表。
- [ ] **挂了参考音的人物，其 `<Subject K>` 段里有对应的 `<Audio N>` 句，并且写明了"只继承音色、不参考原台词"**（`check` 会查）。
